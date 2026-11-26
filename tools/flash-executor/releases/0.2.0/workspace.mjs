import { createHash, randomUUID } from "node:crypto";
import { execFile } from "node:child_process";
import { createReadStream } from "node:fs";
import * as fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { promisify } from "node:util";

const maxFileBytes = 1024 * 1024;
const ignoredDirectories = new Set(["node_modules", ".venv", "__pycache__", ".next", ".git", ".codex"]);
const generatedDirectories = new Set([...ignoredDirectories, ".vite", ".nuxt", ".turbo", ".cache", "coverage", "dist", "build", "out", "target"]);
const exec = promisify(execFile);

export function digest(data) {
  return createHash("sha256").update(data).digest("hex");
}

function permittedComponent(name) {
  const lower = name.toLowerCase();
  if (lower === ".env.example" || lower === ".env.sample" || lower === ".env.template") return true;
  return lower !== ".."
    && !/[<>:"|?*\u0000-\u001f]|[. ]$/.test(name)
    && !/^(?:con|nul|aux|prn|com[1-9]|lpt[1-9])(?:\.|$)/i.test(name)
    && !/^(\.env($|\.)|\.git$|\.codex$|\.ssh$|\.aws$|\.npmrc$|\.pypirc$)/.test(lower)
    && !/\.(?:key|pfx|p12)$/.test(lower);
}

function inside(parent, child) {
  const relative = path.relative(parent, child);
  return relative === "" || (!relative.startsWith(".." + path.sep) && relative !== ".." && !path.isAbsolute(relative));
}

export async function workspaceRoot(value) {
  if (!path.isAbsolute(value) || value.startsWith("\\\\")) {
    throw new Error("workspace must be the absolute path to a local project folder.");
  }
  const root = await fs.realpath(value);
  if (!(await fs.stat(root)).isDirectory() || inside(root, os.homedir()) || root === path.parse(root).root) {
    throw new Error("workspace must name the project folder, below a drive or user-profile root.");
  }
  const privateDirectories = [".codex", ".ssh", ".aws"].map((name) => path.join(os.homedir(), name));
  privateDirectories.push(...[process.env.SystemRoot, process.env.ProgramFiles, process.env["ProgramFiles(x86)"]].filter(Boolean));
  if (privateDirectories.some((directory) => inside(directory, root))) throw new Error("workspace is outside the project area.");
  return root;
}

function missingFile(error) {
  if (error.code === "ENOENT" || error.code === "ENOTDIR") return null;
  throw error;
}

function fileIdentity(stat) {
  return [stat.dev, stat.ino, stat.size, stat.mtimeNs, stat.ctimeNs].join(":");
}

async function staleLock(lock) {
  const owner = Number(await fs.readFile(lock, "utf8").catch(missingFile));
  if (Number.isSafeInteger(owner) && owner > 0) {
    try {
      process.kill(owner, 0);
      return false;
    } catch (error) {
      return error.code === "ESRCH";
    }
  }
  const stat = await fs.stat(lock).catch(missingFile);
  return stat !== null && Date.now() - stat.mtimeMs > 30_000;
}

async function reclaimLock(lock) {
  const observed = await fs.stat(lock, { bigint: true }).catch(missingFile);
  if (!observed || !(await staleLock(lock))) return !observed;
  const recovery = lock + ".recovering";
  const guard = await fs.open(recovery, "wx").catch((error) => {
    if (error.code !== "EEXIST") throw error;
    return null;
  });
  if (!guard) return false;
  try {
    const current = await fs.stat(lock, { bigint: true }).catch(missingFile);
    if (!current) return true;
    if (fileIdentity(current) !== fileIdentity(observed) || !(await staleLock(lock))) return false;
    await fs.unlink(lock).catch(missingFile);
    return true;
  } finally {
    try {
      await guard.close();
    } finally {
      await fs.unlink(recovery).catch(missingFile);
    }
  }
}

export async function lockWorkspace(root, lockDirectory, { signal, waitMs = 0 } = {}) {
  await fs.mkdir(lockDirectory, { recursive: true });
  const lock = path.join(lockDirectory, digest(root.toLowerCase()) + ".lock");
  const deadline = Date.now() + waitMs;
  let attemptedRecovery = false;
  for (;;) {
    signal?.throwIfAborted();
    const handle = await fs.open(lock, "wx").catch((error) => {
      if (error.code !== "EEXIST") throw error;
      return null;
    });
    if (handle) {
      try {
        await handle.writeFile(String(process.pid));
      } catch (error) {
        await handle.close();
        await fs.unlink(lock).catch(missingFile);
        throw error;
      }
      await handle.close();
      let released = false;
      return async () => {
        if (released) return;
        released = true;
        await fs.unlink(lock).catch(missingFile);
      };
    }
    if (!attemptedRecovery && await reclaimLock(lock)) {
      attemptedRecovery = true;
      continue;
    }
    const remaining = deadline - Date.now();
    if (remaining <= 0) {
      const error = new Error("This workspace still has an active Flash job. Retry after it returns.");
      error.code = "WORKSPACE_BUSY";
      throw error;
    }
    await delay(Math.min(300, remaining), undefined, { signal });
    attemptedRecovery = false;
  }
}

async function gitPaths(root, signal) {
  if (!process.env.GIT_DIR && !process.env.GIT_WORK_TREE) {
    let directory = root;
    for (;;) {
      signal?.throwIfAborted();
      if (await fs.lstat(path.join(directory, ".git")).catch(missingFile)) break;
      const parent = path.dirname(directory);
      if (parent === directory) return null;
      directory = parent;
    }
  }
  try {
    const { stdout } = await exec("git", ["ls-files", "-z", "--cached", "--others", "--exclude-standard"], {
      cwd: root, signal, maxBuffer: 16 * 1024 * 1024, windowsHide: true,
      env: { ...process.env, LC_ALL: "C", GIT_OPTIONAL_LOCKS: "0" },
    });
    return [...new Set(stdout.split("\0").filter(Boolean))];
  } catch (error) {
    if (error.code === "ENOENT" || (error.code === 128 && error.stderr?.includes("not a git repository"))) return null;
    throw error;
  }
}

async function walkPaths(root, signal) {
  const files = [];
  const pending = [""];
  while (pending.length) {
    signal?.throwIfAborted();
    const relative = pending.pop();
    const directory = await fs.opendir(path.join(root, relative));
    for await (const entry of directory) {
      if (!permittedComponent(entry.name) || entry.isSymbolicLink()) continue;
      const child = path.posix.join(relative, entry.name);
      if (entry.isFile()) files.push(child);
      if (entry.isDirectory() && !generatedDirectories.has(entry.name.toLowerCase())) pending.push(child);
    }
  }
  return files;
}

async function hashFile(absolute, metadata, cached, signal) {
  const identity = fileIdentity(metadata);
  if (cached?.identity === identity) return cached;
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(absolute, { signal })) hash.update(chunk);
  const latest = await fs.lstat(absolute, { bigint: true });
  if (!latest.isFile() || fileIdentity(latest) !== identity) {
    throw new Error("A project file changed during verification. Retry the check on a stable workspace.");
  }
  return { identity, sha256: hash.digest("hex") };
}

export function compareStates(before, after) {
  const paths = new Set([...before.files.keys(), ...after.files.keys()]);
  const changes = [];
  for (const relative of [...paths].sort()) {
    const oldHash = before.files.get(relative);
    const hash = after.files.get(relative);
    if (oldHash === hash) continue;
    if (hash === undefined) changes.push({ path: relative, action: "deleted" });
    else changes.push({ path: relative, action: oldHash === undefined ? "created" : "edited", sha256: hash });
  }
  return changes;
}

export class Workspace {
  constructor(root) {
    this.root = root;
    this.revision = 0;
    this.changes = new Map();
    this.stateCache = new Map();
  }

  async captureState(signal) {
    signal?.throwIfAborted();
    const candidates = await gitPaths(this.root, signal) ?? await walkPaths(this.root, signal);
    const pending = [...new Set(candidates)].sort();
    const cache = new Map();
    for (let offset = 0; offset < pending.length; offset += 24) {
      signal?.throwIfAborted();
      await Promise.all(pending.slice(offset, offset + 24).map(async (relative) => {
        const components = relative.split("/");
        if (components.some((name) => !permittedComponent(name))) return;
        const absolute = path.join(this.root, ...components);
        const stat = await fs.lstat(absolute, { bigint: true }).catch(missingFile);
        if (!stat || stat.isSymbolicLink()) return;
        const real = await fs.realpath(absolute);
        const canonical = path.relative(this.root, real).split(path.sep).join("/");
        const expected = process.platform === "win32" ? relative.toLowerCase() : relative;
        const actual = process.platform === "win32" ? canonical.toLowerCase() : canonical;
        if (!inside(this.root, real) || actual !== expected) return;
        if (stat.isDirectory()) {
          const nested = await walkPaths(absolute, signal);
          for (const child of nested) pending.push(relative + "/" + child);
        } else if (stat.isFile()) {
          cache.set(relative, await hashFile(absolute, stat, this.stateCache.get(relative), signal));
        }
      }));
    }
    signal?.throwIfAborted();
    this.stateCache = cache;
    const files = new Map([...cache.keys()].sort().map((relative) => [relative, cache.get(relative).sha256]));
    return { files, signature: digest(JSON.stringify([...files])) };
  }

  async resolve(relative) {
    if (path.isAbsolute(relative) || relative.length > 500) throw new Error("Use a path relative to the workspace.");
    const components = relative.split(/[\\/]/).filter((part) => part && part !== ".");
    let absolute = this.root;
    let stat;
    for (const component of components) {
      if (!permittedComponent(component)) throw new Error("Path is outside the job's file scope: " + relative);
      absolute = path.join(absolute, component);
      stat = await fs.lstat(absolute).catch((error) => {
        if (error.code === "ENOENT") return undefined;
        throw error;
      });
      if (stat?.isSymbolicLink() || (stat && !inside(this.root, await fs.realpath(absolute)))) {
        throw new Error("Select a regular project path without symlinks or junctions.");
      }
    }
    return { absolute, relative: components.join("/") || ".", stat };
  }

  async *files(directory) {
    const start = await this.resolve(directory);
    const pending = [start.absolute];
    let directoriesVisited = 0;
    let filesVisited = 0;
    while (pending.length && directoriesVisited < 400 && filesVisited < 4000) {
      const current = pending.pop();
      directoriesVisited++;
      const handle = await fs.opendir(current);
      for await (const entry of handle) {
        if (!permittedComponent(entry.name) || entry.isSymbolicLink()) continue;
        const absolute = path.join(current, entry.name);
        if (entry.isDirectory() && !ignoredDirectories.has(entry.name.toLowerCase())) pending.push(absolute);
        if (entry.isFile()) {
          yield path.relative(this.root, absolute).split(path.sep).join("/");
          if (++filesVisited >= 4000) break;
        }
      }
    }
  }

  async snapshot(relative) {
    const file = await this.resolve(relative);
    if (!file.stat?.isFile() || file.stat.size > maxFileBytes) {
      throw new Error("Select an existing UTF-8 text file up to 1 MiB.");
    }
    const bytes = await fs.readFile(file.absolute);
    if (bytes.includes(0)) throw new Error("Select a UTF-8 text file.");
    return {
      ...file,
      text: new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes),
      sha256: digest(bytes),
    };
  }

  async read(relative, start, lines) {
    const file = await this.snapshot(relative);
    const content = file.text.split(/\r?\n/);
    const selection = content.slice(start - 1, start - 1 + lines);
    while (selection.length > 1 && selection.join("\n").length > 18_000) selection.pop();
    return {
      path: file.relative,
      sha256: file.sha256,
      from: start,
      to: start + selection.length - 1,
      lineCount: content.length,
      text: selection.join("\n").slice(0, 18_000),
    };
  }

  async write(relative, text, expectedHash) {
    const file = await this.resolve(relative);
    if (file.relative === "." || (file.stat && !file.stat.isFile())) throw new Error("Select a regular project file.");
    if (Buffer.byteLength(text) > maxFileBytes) throw new Error("File content exceeds 1 MiB.");
    const previous = file.stat ? await this.snapshot(relative) : null;
    if (previous ? previous.sha256 !== expectedHash : expectedHash != null) {
      throw new Error("File has changed or needs its current hash. Read it before updating.");
    }
    const sha256 = digest(text);
    if (sha256 === previous?.sha256) return { path: file.relative, sha256, changed: false };

    await fs.mkdir(path.dirname(file.absolute), { recursive: true });
    if (!previous) {
      await fs.writeFile(file.absolute, text, { flag: "wx" });
    } else {
      const temp = path.join(path.dirname(file.absolute), ".flash-" + randomUUID() + ".tmp");
      try {
        await fs.writeFile(temp, text, { flag: "wx", mode: file.stat.mode });
        const current = await this.snapshot(relative);
        if (current.sha256 !== expectedHash) throw new Error("File changed while editing. Read it and retry.");
        await fs.rename(temp, file.absolute);
      } finally {
        await fs.unlink(temp).catch(() => {});
      }
    }
    this.revision++;
    this.changes.set(file.relative, { path: file.relative, sha256, action: this.changes.get(file.relative)?.action ?? (previous ? "edited" : "created") });
    return { path: file.relative, sha256, changed: true };
  }

  async replace(relative, oldText, newText, count) {
    const file = await this.snapshot(relative);
    const crlf = file.text.includes("\r\n");
    const before = file.text.replaceAll("\r\n", "\n");
    const parts = before.split(oldText.replaceAll("\r\n", "\n"));
    if (parts.length !== count + 1) throw new Error("Expected " + count + " exact matches, found " + (parts.length - 1) + ".");
    const updated = parts.join(newText.replaceAll("\r\n", "\n"));
    return this.write(relative, crlf ? updated.replaceAll("\n", "\r\n") : updated, file.sha256);
  }
}
