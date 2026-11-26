import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { chromium } from "playwright-core";
import { portHasListeners, verifyOwnership } from "./preview-ownership.mjs";

function startProcess(command, cwd) {
  const script = [
    "$ErrorActionPreference = 'Stop'",
    "$ProgressPreference = 'SilentlyContinue'",
    "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)",
    "$OutputEncoding = [Console]::OutputEncoding",
    "$env:Path = (@($env:Path, [Environment]::GetEnvironmentVariable('Path', 'Machine'), [Environment]::GetEnvironmentVariable('Path', 'User')) -join ';')",
    "$global:LASTEXITCODE = 0",
    command,
    "exit $LASTEXITCODE",
  ].join("\r\n");
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) =>
    !/^(?:path$|pathext$|comspec$|CODEX_|MAGPIE_)|(?:^|_)(?:TOKEN|SECRET|PASSWORD|API_KEY|CREDENTIALS?)(?:_|$)/i.test(key)));
  env.Path = [path.dirname(process.execPath), process.env.Path ?? process.env.PATH].filter(Boolean).join(path.delimiter);
  env.PATHEXT = process.env.PATHEXT ?? ".COM;.EXE;.BAT;.CMD";
  env.ComSpec = process.env.ComSpec ?? path.join(process.env.SystemRoot ?? "C:\\Windows", "System32", "cmd.exe");
  const child = spawn("powershell.exe", ["-NoLogo", "-NoProfile", "-NonInteractive", "-OutputFormat", "Text",
    "-EncodedCommand", Buffer.from(script, "utf16le").toString("base64")], {
    cwd, env, windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
  });
  let output = "";
  function collect(stream) {
    stream.setEncoding("utf8");
    stream.on("data", (chunk) => { output = (output + chunk).slice(-10_000); });
  }
  collect(child.stdout);
  collect(child.stderr);
  let ended = false;
  const closed = new Promise((resolve) => {
    child.once("error", (error) => {
      ended = true;
      resolve({ exitCode: null, failure: error.message });
    });
    child.once("close", (exitCode) => {
      ended = true;
      resolve({ exitCode });
    });
  });
  async function stop() {
    if (ended || !child.pid) return;
    await new Promise((resolve) => {
      const kill = spawn("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], {
        windowsHide: true, stdio: "ignore",
      });
      const timer = setTimeout(() => kill.kill(), 5000);
      const done = () => {
        clearTimeout(timer);
        resolve();
      };
      kill.once("error", done);
      kill.once("close", done);
    });
    if (!ended) child.kill();
    await Promise.race([closed, delay(1000, undefined, { ref: false })]);
  }
  return { pid: child.pid, closed, ended: () => ended, output: () => output, stop };
}

function parseOrigin(value) {
  const url = new URL(value);
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) {
    throw new Error("Browser URLs must be HTTP(S) without credentials.");
  }
  return url.origin;
}

async function browserInstance() {
  try {
    return await chromium.launch({ channel: "chrome", headless: true, timeout: 12_000 });
  } catch {
    return chromium.launch({ channel: "msedge", headless: true, timeout: 12_000 });
  }
}

export class DevelopmentTools {
  constructor(workspace, job, screenshotDirectory, signal, redact) {
    this.workspace = workspace;
    this.commands = new Map((job.commands ?? []).map((command) => [command.id, command]));
    this.previewOrigins = new Map((job.browser_origins ?? []).map((origin) => {
      const parsed = parseOrigin(origin);
      return [parsed, { source: "explicit_url", id: null }];
    }));
    for (const [id, spec] of this.commands) {
      if (spec.ready_url) this.previewOrigins.set(parseOrigin(spec.ready_url), { source: "owned_preview", id });
    }
    this.screenshotDirectory = screenshotDirectory;
    this.signal = signal;
    this.redact = redact;
    this.previews = new Map();
    this.checks = [];
    this.screenshots = [];
  }

  async run(id) {
    const spec = this.commands.get(id);
    if (!spec) throw new Error("Unknown command id. Ask Codex to supply a command for this step.");
    this.signal.throwIfAborted();
    const started = Date.now();
    const timeout = AbortSignal.timeout(1000 * (spec.timeout_seconds ?? 60));
    const signal = AbortSignal.any([this.signal, timeout]);
    const failure = (error) => {
      const evidence = {
        id, status: signal.aborted ? (this.signal.aborted ? "cancelled" : "timeout") : "failed",
        reason: error.code ?? "preview_start_failed", failure: this.redact(error.message),
        revision: this.workspace.revision, ms: Date.now() - started,
      };
      this.checks.push(evidence);
      return evidence;
    };
    const preview = this.previews.get(id);
    if (preview && !preview.process.ended()) {
      try {
        const { ok, reason, owners } = await verifyOwnership(preview.port, preview.process.pid, signal);
        if (!ok) throw new Error(reason);
        preview.owners = owners;
        return { id, status: "ready", url: preview.url, pid: preview.process.pid };
      } catch (error) {
        await this.stopService(id);
        return failure(error);
      }
    }
    let previewUrl = null;
    let port = null;
    if (spec.ready_url) {
      const url = new URL(spec.ready_url);
      if (!["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)) {
        return failure(new Error("ready_url must use localhost, 127.0.0.1, or [::1]."));
      }
      previewUrl = url.href;
      port = Number(url.port) || (url.protocol === "https:" ? 443 : 80);
      try {
        if (await portHasListeners(port, signal)) {
          const error = new Error("preview_port_in_use: a listener already occupies port " + port + ".");
          error.code = "preview_port_in_use";
          return failure(error);
        }
        signal.throwIfAborted();
      } catch (error) {
        return failure(error);
      }
    }
    const process = startProcess(spec.command, this.workspace.root);
    let keepAlive = false;
    let previewRecord = null;
    let outcome;
    try {
      if (spec.ready_url) {
        previewRecord = { id, url: previewUrl, port, process, owners: [] };
        let ready = false;
        while (!process.ended()) {
          signal.throwIfAborted();
          const response = await fetch(spec.ready_url, { signal: AbortSignal.any([signal, AbortSignal.timeout(1500)]), redirect: "manual" })
            .then((r) => {
              r.body?.cancel().catch(() => {});
              return r.ok ? r : null;
            })
            .catch(() => null);
          if (response && !process.ended()) {
            const proof = await verifyOwnership(port, process.pid, signal);
            if (!proof.ok) throw new Error(proof.reason ?? "preview_ownership_unresolved");
            signal.throwIfAborted();
            if (process.ended()) break;
            previewRecord.owners = proof.owners;
            this.previews.set(id, previewRecord);
            keepAlive = true;
            ready = true;
            break;
          }
          await delay(250, undefined, { signal });
        }
        outcome = ready
          ? { status: "ready", url: previewUrl, pid: process.pid }
          : { status: "failed", ...(await process.closed) };
      } else {
        const closed = await Promise.race([
          process.closed,
          delay(1000 * (spec.timeout_seconds ?? 60), null, { signal }),
        ]);
        outcome = closed ? { status: closed.exitCode === 0 ? "passed" : "failed", ...closed } : { status: "timeout" };
      }
    } catch (error) {
      outcome = {
        status: signal.aborted ? (this.signal.aborted ? "cancelled" : "timeout") : "failed",
        ...(error.code ? { reason: error.code } : {}),
        failure: this.redact(error.message),
      };
    } finally {
      if (!keepAlive) await process.stop();
    }
    const evidence = {
      id, ...outcome, revision: this.workspace.revision, ms: Date.now() - started,
      output: this.redact(process.output()).slice(-2800),
    };
    this.checks.push(evidence);
    return evidence;
  }

  async capture(args) {
    this.signal.throwIfAborted();
    const origin = parseOrigin(args.url);
    const registered = this.previewOrigins.get(origin);
    if (!registered) {
      throw new Error("The preview origin needs to be included in the Codex job's browser_origins or ready_url.");
    }
    const source = registered.source;
    const previewId = source === "owned_preview" ? registered.id : null;
    const assertPreview = async () => {
      if (source !== "owned_preview") return;
      const preview = this.previews.get(registered.id);
      if (!preview || preview.process.ended()) {
        throw new Error("The ready_url preview for this origin is no longer running; re-run the command before capturing.");
      }
      const { ok, reason, owners } = await verifyOwnership(preview.port, preview.process.pid, this.signal);
      this.signal.throwIfAborted();
      if (!ok || preview.process.ended()) throw new Error("Preview ownership could not be confirmed: " + (reason ?? origin));
      preview.owners = owners;
    };
    await assertPreview();
    if (this.screenshots.length >= 8) throw new Error("This job has used its screenshot slots.");
    await mkdir(this.screenshotDirectory, { recursive: true });
    const browser = await browserInstance();
    const abort = () => { void browser.close().catch(() => {}); };
    this.signal.addEventListener("abort", abort, { once: true });
    try {
      this.signal.throwIfAborted();
      const context = await browser.newContext({
        viewport: { width: args.width ?? 1280, height: args.height ?? 720 },
        serviceWorkers: "block",
      });
      await context.route("**/*", (route) => {
        const requestOrigin = new URL(route.request().url()).origin;
        return this.previewOrigins.has(requestOrigin) ? route.continue() : route.abort();
      });
      const page = await context.newPage();
      const response = await page.goto(args.url, { waitUntil: "domcontentloaded", timeout: 15_000 });
      if (!response?.ok()) throw new Error("Preview returned HTTP " + (response?.status() ?? "unknown") + ".");
      const requested = new URL(args.url).href;
      const assertTarget = () => {
        if (new URL(page.url()).href !== requested) throw new Error("The page does not match the requested URL.");
      };
      assertTarget();
      if (args.wait_for) await page.locator(args.wait_for).first().waitFor({ state: "visible", timeout: 8_000 });
      assertTarget();
      const safeName = (args.name ?? "preview").replace(/[^a-zA-Z0-9_-]/g, "-").slice(0, 48) || "preview";
      const file = path.join(this.screenshotDirectory, safeName + "-" + randomUUID().slice(0, 8) + ".png");
      const bytes = await page.screenshot({ animations: "disabled", timeout: 10_000 });
      const image = bytes.length <= 1_000_000
        ? { mime: "image/png", bytes }
        : { mime: "image/jpeg", bytes: await page.screenshot({ type: "jpeg", quality: 70, timeout: 10_000 }) };
      await assertPreview();
      assertTarget();
      const evidence = {
        path: file, url: page.url(), title: await page.title(), revision: this.workspace.revision,
        visibleText: this.redact((await page.locator("body").innerText({ timeout: 3000 })).slice(0, 650)),
        source,
        ...(previewId ? { preview_id: previewId } : {}),
        width: args.width ?? 1280, height: args.height ?? 720,
      };
      assertTarget();
      this.signal.throwIfAborted();
      await writeFile(file, bytes, { flag: "wx" });
      this.screenshots.push(evidence);
      return { evidence, image };
    } finally {
      this.signal.removeEventListener("abort", abort);
      await browser.close().catch(() => {});
    }
  }

  async stopService(id) {
    const preview = this.previews.get(id);
    if (!preview) return { id, stopped: false };
    this.previews.delete(id);
    await preview.process.stop();
    return { id, stopped: true, url: preview.url, pid: preview.process.pid };
  }

  async close() {
    await Promise.allSettled(Array.from(this.previews.values(), (preview) => preview.process.stop()));
    this.previews.clear();
  }
}
