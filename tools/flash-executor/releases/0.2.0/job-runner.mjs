import { randomUUID } from "node:crypto";
import path from "node:path";
import { DevelopmentTools } from "./dev-tools.mjs";
import { compareStates, lockWorkspace, Workspace, workspaceRoot } from "./workspace.mjs";
import { Verification } from "./verification.mjs";
import { readCheckpoint, removeCheckpoint, writeCheckpoint, writeEvidence, compactResult } from "./job-record.mjs";
import { runWorker } from "./worker-loop.mjs";

function invalid(message) {
  const error = new Error(message);
  error.code = "INVALID_JOB";
  return error;
}

function validate(job) {
  const commands = job.commands ?? [];
  if (job.mode === "edit" && !job.task?.trim()) throw invalid("Provide task for an edit job.");
  if (job.mode === "verify" && !commands.length && !job.screenshots?.length) {
    throw invalid("Provide commands or screenshots for verification.");
  }
  if (job.mode === "verify" && job.require_screenshot && !job.screenshots?.length) {
    throw invalid("Provide the exact screenshot targets for verify mode.");
  }
  if (new Set(commands.map(({ id }) => id)).size !== commands.length) throw invalid("Use distinct command IDs.");
  const origins = new Set();
  for (const command of commands) {
    if (!command.ready_url) continue;
    const ready = new URL(command.ready_url);
    if (origins.has(ready.origin)) throw invalid("Supply one preview command per origin.");
    origins.add(ready.origin);
  }
}

function resolveJob(request, record) {
  const { workspace, resume_job_id, details, ...input } = request;
  if (!record) return { ...input, mode: input.mode ?? "edit" };
  const { model, context, commands, ...overrides } = input;
  if (Object.values(overrides).some((value) => value !== undefined)) {
    throw invalid("A continuation accepts workspace, resume_job_id and optional context, commands, model and details.");
  }
  if (commands && new Set(commands.map(({ id }) => id)).size !== commands.length) {
    throw invalid("Use distinct command IDs in continuation overrides.");
  }
  const merged = new Map((record.job.commands ?? []).map((command) => [command.id, command]));
  for (const command of commands ?? []) merged.set(command.id, command);
  const expanded = [record.job.context, context].filter(Boolean).join("\n\n");
  if (expanded.length > 30_000) throw invalid("Continuation context exceeds the remaining 30,000-character limit.");
  return { ...record.job, model: model ?? record.job.model, context: expanded, commands: [...merged.values()] };
}

function sanitize(data, redact) {
  return Object.fromEntries(Object.entries(data).map(([key, value]) =>
    [key, typeof value === "string" && !["path", "sha256", "file_state"].includes(key) ? redact(value) : value]));
}

function resumableInput(job, redact) {
  const { task, context, acceptance, ...operational } = job;
  const raw = JSON.stringify(operational);
  if (redact(raw) !== raw) return null; // Never persist a recognized credential from executable input.
  return {
    ...operational,
    ...(task ? { task: redact(task) } : {}),
    ...(context ? { context: redact(context) } : {}),
    ...(acceptance ? { acceptance: acceptance.map(redact) } : {}),
  };
}

export async function runJob(request, extra, {
  dataDirectory, makeTools, chat, redact, models, workerInstructions, parseJob,
}) {
  const started = Date.now();
  const root = await workspaceRoot(request.workspace);
  const signal = AbortSignal.any([extra.signal, AbortSignal.timeout(8 * 60_000)].filter(Boolean));
  const artifacts = path.join(dataDirectory, "artifacts");
  const jobs = path.join(dataDirectory, "jobs");
  const jobId = request.resume_job_id ?? randomUUID();
  const release = await lockWorkspace(root, path.join(dataDirectory, "locks"), { signal, waitMs: 25_000 });
  let dev;
  try {
    const prior = request.resume_job_id ? await readCheckpoint(jobs, jobId, root) : null;
    const job = parseJob({ ...resolveJob(request, prior), workspace: root });
    validate(job);
    const workspace = new Workspace(root);
    dev = new DevelopmentTools(workspace, job, path.join(artifacts, jobId), signal, redact);
    const verifier = new Verification(workspace, dev, job, signal);
    const startState = await workspace.captureState(signal);
    const baseline = prior ? { files: new Map(prior.baseline) } : startState;
    const resumeInput = resumableInput(job, redact);
    const overriddenIds = new Set(request.resume_job_id ? (request.commands ?? []).map(({ id }) => id) : []);
    const oldChecks = prior?.checks ?? [];
    verifier.checks.push(...oldChecks.filter((check) =>
      check.status === "passed" && check.exitCode === 0 && check.file_state === startState.signature && !overriddenIds.has(check.id)));

    let phase = prior?.phase ?? job.mode;
    if (job.mode === "edit" && request.resume_job_id && request.context) phase = "edit";
    let finish;
    let failure;
    let state;
    let activeModel;
    let usage = { calls: 0 };
    let record = prior;
    let step = 0;
    const progress = (message) => {
      const token = extra._meta?.progressToken;
      if (token === undefined) return;
      return extra.sendNotification({
        method: "notifications/progress",
        params: { progressToken: token, progress: ++step, message: "Flash " + jobId + " " + message },
      }).catch(() => {});
    };
    const save = async (note) => {
      if (!resumeInput) return;
      const latest = new Map(verifier.checks.map((check) => [check.id, check]));
      record = await writeCheckpoint(jobs, {
        ...record, job_id: jobId, workspace: root, job: resumeInput, baseline: [...baseline.files],
        phase, note: redact(note ?? ""),
        checks: [...latest.values()].filter((check) => check.status === "passed" && check.exitCode === 0 && check.file_state)
          .map(({ id, status, exitCode, file_state }) =>
          ({ id, status, exitCode, file_state })),
      });
    };
    await save(prior?.note);
    await progress(phase === "verify" ? "verifying" : "started");
    try {
      if (phase === "edit") {
        const previousChanges = compareStates(baseline, startState);
        const worker = await runWorker({
          initialMessages: [
            { role: "system", content: workerInstructions },
            { role: "user", content: JSON.stringify({
              task: redact(job.task), context: redact(job.context), acceptance: (job.acceptance ?? []).map(redact),
              commands: (job.commands ?? []).map(({ id, ready_url, required }) => ({ id, ready_url: ready_url && redact(ready_url), required })),
              preview_targets: (job.screenshots ?? []).map((target) => sanitize(target, redact)),
              browser_origins: (job.browser_origins ?? []).map(redact),
              require_screenshot: job.require_screenshot ?? false,
            }) },
          ],
          tools: makeTools(workspace, verifier, signal),
          chat, model: job.model, signal, redact,
          progress: (round, model) => progress(model + " round " + round),
          getProgress: () => JSON.stringify({
            previous: record?.note,
            changes: [...previousChanges.slice(0, 8), ...[...workspace.changes.values()].slice(-8)]
              .map(({ path, action }) => ({ path, action })),
            checks: verifier.checks.slice(-8).map(({ id, status }) => ({ id, status })),
            screenshots: verifier.screenshots.slice(-4).map(({ url, status }) => ({ url, status })),
          }),
        });
        activeModel = models[worker.model];
        usage = worker.usage;
        finish = worker.finish;
        failure = worker.failure;
        if (finish?.status === "done" && !failure) {
          phase = "verify";
          await save(finish.summary);
          await progress("verifying");
        } else if (!failure) {
          failure = { reason: "worker_blocked", message: finish?.summary ?? "Flash stopped before it finished the edit." };
        }
      }
      if (!failure && phase === "verify") ({ state } = await verifier.verify());
    } catch (error) {
      const reason = signal.aborted
        ? (signal.reason?.name === "TimeoutError" ? "job_timeout" : "cancelled")
        : (error.code ?? "verification_failed");
      failure = { reason, message: error.message };
    }
    if (!state) {
      try {
        state = await workspace.captureState(AbortSignal.timeout(12_000));
      } catch (error) {
        failure ??= { reason: "workspace_scan_failed", message: error.message };
      }
    }

    const missing = state ? verifier.missing(state) : ["workspace:file_state"];
    if (!failure && missing.length) failure = { reason: "verification_missing", message: "Required verification did not pass." };
    if (missing.includes("screenshot:current_preview") && job.mode === "edit") phase = "edit";
    const completed = !failure && phase === "verify";
    const changes = state ? compareStates(baseline, state) : [...workspace.changes.values()];
    const report = {
      status: completed ? "completed" : (failure?.reason === "worker_blocked" ? "needs_input" : "partial"),
      job_id: jobId,
      summary: redact(failure?.message ?? finish?.summary ?? "Verification passed.").slice(0, 1700) || "Verification passed.",
      ...(failure ? { reason: failure.reason } : {}),
      ...(activeModel ? { model: activeModel } : {}),
      ...(missing.length ? { missing: missing.map(redact) } : {}),
      changed_files: changes,
      ...(state ? {} : { file_scan_incomplete: true }),
      observations: (finish?.observations ?? []).map(redact),
      checks: verifier.checks.map((check) => sanitize(
        ["passed", "ready"].includes(check.status) && check.file_state !== state?.signature
          ? { ...check, status: "stale", reason: "workspace_changed_after_check" } : check, redact)),
      screenshots: verifier.screenshots.map((shot) => sanitize(
        shot.status === "captured" && shot.file_state !== state?.signature ? { ...shot, status: "stale" } : shot, redact)),
      usage: { ...usage, elapsed_ms: Date.now() - started },
      ...(!completed ? { resume_available: Boolean(record && resumeInput) } : {}),
    };
    if (!completed) await save(report.summary);
    report.evidence_path = await writeEvidence(artifacts, jobId, report);
    if (completed && record) await removeCheckpoint(jobs, jobId);
    return compactResult(report, request.details);
  } finally {
    try {
      await dev?.close();
    } finally {
      await release();
    }
  }
}
