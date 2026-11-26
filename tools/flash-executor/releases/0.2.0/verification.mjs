const good = new Set(["passed", "ready"]);

function sameTarget(left, right) {
  return new URL(left.url).href === new URL(right.url).href
    && (left.width ?? 1280) === (right.width ?? 1280)
    && (left.height ?? 720) === (right.height ?? 720)
    && (left.wait_for ?? "") === (right.wait_for ?? "");
}

function stamp(result, before, after) {
  const stale = (good.has(result.status) || result.status === "captured")
    && before.signature !== after.signature;
  return {
    ...result, file_state: after.signature,
    ...(stale ? { status: "stale", reason: "workspace_changed_during_verification" } : {}),
  };
}

export class Verification {
  constructor(workspace, dev, job, signal) {
    this.workspace = workspace;
    this.dev = dev;
    this.job = job;
    this.signal = signal;
    this.commands = new Map((job.commands ?? []).map((command) => [command.id, command]));
    this.previewIds = new Map([...this.commands.values()]
      .filter((command) => command.ready_url)
      .map((command) => [new URL(command.ready_url).origin, command.id]));
    this.checks = [];
    this.screenshots = [];
  }

  state() {
    return this.workspace.captureState(this.signal);
  }

  latest(id) {
    return this.checks.findLast((check) => check.id === id);
  }

  async run(id) {
    const command = this.commands.get(id);
    if (!command) throw new Error("Unknown command ID. Supply it in commands first.");
    const previous = this.latest(id);
    const before = await this.state();
    if (command.ready_url && previous && (previous.status !== "ready" || previous.file_state !== before.signature)) {
      await this.dev.stopService(id);
    }
    let result;
    try {
      result = await this.dev.run(id);
    } catch (error) {
      result = { id, status: "failed", reason: error.code ?? "command_failed", failure: error.message };
    }
    // Save the command's result even if the job is cancelled before it can be restamped.
    const index = this.checks.push({ ...result, file_state: null }) - 1;
    const after = await this.state();
    const evidence = stamp(result, before, after);
    this.checks[index] = evidence;
    return evidence;
  }

  async capture(args) {
    const url = new URL(args.url);
    const requested = this.job.screenshots ?? [];
    if (requested.length && !requested.some((target) => sameTarget(target, args))) {
      throw new Error("Choose an exact target listed in screenshots, with its viewport and wait_for.");
    }
    const previewId = this.previewIds.get(url.origin);
    let before = await this.state();
    if (previewId) {
      const preview = this.latest(previewId);
      if (preview?.status !== "ready" || preview.file_state !== before.signature) {
        const result = await this.run(previewId);
        if (result.status !== "ready") throw new Error(result.failure ?? "The preview did not become ready.");
        before = await this.state();
        if (result.file_state !== before.signature) throw new Error("Project files changed after the preview started.");
      }
    }
    const result = await this.dev.capture(args);
    const after = await this.state();
    const evidence = stamp({ ...result.evidence, wait_for: args.wait_for, status: "captured" }, before, after);
    this.screenshots.push(evidence);
    return { ...result, evidence };
  }

  currentShots(state) {
    return this.screenshots.filter((shot) => shot.status === "captured" && shot.file_state === state.signature);
  }

  missing(state) {
    const missing = [];
    for (const command of this.commands.values()) {
      if (command.required === false) continue;
      const last = this.latest(command.id);
      if (last?.status !== (command.ready_url ? "ready" : "passed") || last.file_state !== state.signature) {
        missing.push("check:" + command.id);
      }
    }
    const current = this.currentShots(state);
    for (const target of this.job.screenshots ?? []) {
      if (!current.some((shot) => sameTarget(shot, target))) missing.push("screenshot:" + target.url);
    }
    if (this.job.require_screenshot && !this.job.screenshots?.length && !current.length) {
      missing.push("screenshot:current_preview");
    }
    return missing;
  }

  async verify() {
    const required = [...this.commands.values()].filter((command) => command.required !== false);
    const wanted = this.job.mode === "verify" ? [...this.commands.values()] : required;
    for (const command of wanted) {
      const latest = this.latest(command.id);
      if (command.ready_url || !latest || latest.file_state !== (await this.state()).signature) {
        await this.run(command.id);
      }
    }
    // A generator can update files after an earlier check. Recheck stale evidence once.
    let state = await this.state();
    for (const command of required) {
      const last = this.latest(command.id);
      if (last?.status === "stale" || (good.has(last?.status) && last.file_state !== state.signature)) {
        await this.run(command.id);
        state = await this.state();
      }
    }
    for (const target of this.job.screenshots ?? []) {
      if (this.currentShots(state).some((shot) => sameTarget(shot, target))) continue;
      try {
        await this.capture(target);
      } catch (error) {
        this.signal.throwIfAborted();
        this.screenshots.push({ url: target.url, status: "failed", failure: error.message, file_state: state.signature });
      }
      state = await this.state();
    }
    return { state, missing: this.missing(state) };
  }
}
