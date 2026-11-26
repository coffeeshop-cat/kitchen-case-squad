// job-record.mjs — durable checkpoint + compact evidence for Flash MCP jobs.
// No dependencies; no state outside the supplied paths; no provider transcripts.

import { randomUUID } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';

export const CHECKPOINT_VERSION = 1;
export const CHECKPOINT_TTL_MS = 7 * 24 * 60 * 60 * 1000; // 7 days, predictable.

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const PHASES = new Set(['edit', 'verify']);
const COMPACT_SUMMARY_MAX = 400;
const COMPACT_CHANGED_MAX = 16;
const FAIL_TAIL_CHARS = 320;

function isUuid(value) {
  return typeof value === 'string' && UUID_RE.test(value);
}

function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isIsoString(value) {
  if (typeof value !== 'string' || value.length < 10) return false;
  const t = Date.parse(value);
  return Number.isFinite(t);
}

function sameWorkspace(a, b) {
  if (a === b) return true;
  // Windows paths are case-insensitive (and slash-insensitive) for identity.
  if (process.platform === 'win32') {
    const norm = (p) => String(p).replace(/[\\/]+/g, '\\').toLowerCase();
    return norm(a) === norm(b);
  }
  return false;
}

function fail(code, message) {
  const err = new Error(message);
  err.code = code;
  return err;
}

function checkpointPath(directory, jobId) {
  if (!isUuid(jobId)) {
    throw fail('INVALID_CHECKPOINT', `job id is not a UUID: unsafe path rejected`);
  }
  return path.join(directory, `${jobId}.json`);
}

function assertRecordShape(record) {
  if (!isPlainObject(record)) {
    throw fail('INVALID_CHECKPOINT', 'checkpoint record must be a plain object');
  }
  if (record.version !== CHECKPOINT_VERSION) {
    throw fail('INVALID_CHECKPOINT', `unsupported checkpoint version ${String(record.version)}`);
  }
  if (!isUuid(record.job_id)) {
    throw fail('INVALID_CHECKPOINT', 'checkpoint job_id must be a UUID');
  }
  if (typeof record.workspace !== 'string' || record.workspace.length === 0) {
    throw fail('INVALID_CHECKPOINT', 'checkpoint workspace must be a non-empty string');
  }
  if (!path.isAbsolute(record.workspace)) {
    throw fail('INVALID_CHECKPOINT', 'checkpoint workspace must be an absolute path');
  }
  if (!isPlainObject(record.job)) {
    throw fail('INVALID_CHECKPOINT', 'checkpoint record is missing job input');
  }
  if (!Array.isArray(record.baseline)) {
    throw fail('INVALID_CHECKPOINT', 'checkpoint baseline must be an array of [path, sha256] pairs');
  }
  for (const pair of record.baseline) {
    if (!Array.isArray(pair) || pair.length !== 2
      || typeof pair[0] !== 'string' || typeof pair[1] !== 'string'
      || !/^[0-9a-f]{64}$/i.test(pair[1])) {
      throw fail('INVALID_CHECKPOINT', 'checkpoint baseline entries must be [relativePath, sha256]');
    }
  }
  if (!PHASES.has(record.phase)) {
    throw fail('INVALID_CHECKPOINT', 'checkpoint phase must be "edit" or "verify"');
  }
  if (typeof record.note !== 'string') {
    throw fail('INVALID_CHECKPOINT', 'checkpoint note must be a short string');
  }
  if (!isIsoString(record.updated_at)) {
    throw fail('INVALID_CHECKPOINT', 'checkpoint updated_at must be an ISO timestamp');
  }
  if (record.checks !== undefined && (!Array.isArray(record.checks) || record.checks.some((check) =>
    !isPlainObject(check) || typeof check.id !== 'string' || check.status !== 'passed'
    || !/^[0-9a-f]{64}$/i.test(check.file_state)))) {
    throw fail('INVALID_CHECKPOINT', 'invalid saved check evidence');
  }
}

async function atomicWriteJson(filePath, value) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  const tmp = `${filePath}.${randomUUID()}.tmp`;
  const body = JSON.stringify(value, null, 2);
  try {
    // 'wx' + rename keeps concurrent writers from clobbering each other's temp.
    await fs.writeFile(tmp, body, { encoding: 'utf8', flag: 'wx' });
    await fs.rename(tmp, filePath); // atomic on POSIX and Windows (same volume).
  } finally {
    await fs.rm(tmp, { force: true }).catch(() => {});
  }
}

export async function writeCheckpoint(directory, record) {
  const base = isPlainObject(record) ? record : {};
  const next = {
    version: CHECKPOINT_VERSION,
    job_id: base.job_id || randomUUID(),
    workspace: base.workspace,
    job: base.job,
    baseline: base.baseline || [],
    phase: base.phase,
    note: typeof base.note === 'string' ? base.note.slice(0, 500) : '',
    ...(base.checks?.length ? { checks: base.checks } : {}),
    created_at: isIsoString(base.created_at) ? base.created_at : new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  assertRecordShape(next);
  await atomicWriteJson(checkpointPath(directory, next.job_id), next);
  return next;
}

export async function readCheckpoint(directory, jobId, canonicalWorkspace) {
  const file = checkpointPath(directory, jobId); // rejects non-UUID job ids
  let raw;
  try {
    raw = await fs.readFile(file, 'utf8');
  } catch (err) {
    if (err && (err.code === 'ENOENT' || err.code === 'ENOTDIR')) {
      throw fail('CHECKPOINT_NOT_FOUND', `no checkpoint for job ${jobId}`);
    }
    throw err; // unexpected I/O errors propagate
  }
  let record;
  try {
    record = JSON.parse(raw);
  } catch {
    throw fail('INVALID_CHECKPOINT', 'checkpoint file is not valid JSON');
  }
  assertRecordShape(record);
  if (record.job_id !== jobId) {
    throw fail('CHECKPOINT_MISMATCH', `checkpoint job_id ${record.job_id} does not match requested ${jobId}`);
  }
  if (!sameWorkspace(record.workspace, canonicalWorkspace)) {
    throw fail('CHECKPOINT_MISMATCH', 'checkpoint workspace does not match the requesting workspace');
  }
  const updated = Date.parse(record.updated_at);
  if (!Number.isFinite(updated) || Date.now() - updated > CHECKPOINT_TTL_MS) {
    throw fail('CHECKPOINT_NOT_FOUND', `checkpoint for job ${jobId} expired (older than 7 days)`);
  }
  return record;
}

export async function removeCheckpoint(directory, jobId) {
  const file = checkpointPath(directory, jobId);
  try {
    await fs.rm(file, { force: true });
  } catch (err) {
    if (err && err.code === 'ENOENT') return false;
    throw err;
  }
  return true;
}

export async function writeEvidence(artifactsDirectory, jobId, result) {
  if (!isUuid(jobId)) {
    throw fail('INVALID_CHECKPOINT', 'job id must be a UUID for evidence paths');
  }
  const reportPath = path.join(artifactsDirectory, jobId, 'report.json');
  await atomicWriteJson(reportPath, result === undefined ? null : result);
  return path.resolve(reportPath);
}

// ---- compact result -------------------------------------------------------

function terse(text) {
  const s = String(text ?? '').replace(/\s+/g, ' ').trim();
  return s.length <= COMPACT_SUMMARY_MAX ? s : `${s.slice(0, COMPACT_SUMMARY_MAX - 1).trimEnd()}…`;
}

function compactChecks(checks) {
  const latest = new Map(checks.map((check) => [check.id, check]));
  return [...latest.values()].map(({ id, status, exitCode, reason, failure, output }) => {
    const out = { id, status, ...(exitCode !== undefined ? { exitCode } : {}), ...(reason ? { reason } : {}) };
    if (status === 'passed' || status === 'ready') return out;
    const message = String(failure ?? output ?? '').trim();
    if (message.length > FAIL_TAIL_CHARS) {
      const firstLine = message.split('\n', 1)[0].slice(0, 100);
      out.output_tail = firstLine + '\n…\n' + message.slice(-(FAIL_TAIL_CHARS - firstLine.length - 3));
    } else if (message) out.output_tail = message;
    return out;
  });
}

function compactScreenshots(screenshots) {
  if (!Array.isArray(screenshots)) return screenshots;
  return screenshots.map((shot) => {
    if (!isPlainObject(shot)) return shot;
    const out = {};
    for (const key of ['path', 'url', 'source', 'preview_id', 'status']) {
      if (shot[key] !== undefined) out[key] = shot[key];
    }
    if (shot.failure) out.failure = String(shot.failure).slice(0, 180);
    return Object.keys(out).length ? out : shot;
  });
}

export function compactResult(result, details = false) {
  if (details) return result; // full report stays available on demand
  if (!isPlainObject(result)) return result;
  const out = {};
  // Backward-compatible passthrough, only where present.
  for (const key of ['status', 'job_id', 'reason', 'missing', 'model', 'usage', 'evidence_path', 'resume_available', 'file_scan_incomplete']) {
    if (result[key] !== undefined) out[key] = result[key];
  }
  out.summary = terse(result.summary ?? result.message ?? '');
  if (Array.isArray(result.changed_files)) {
    out.changed_files = result.changed_files.slice(0, COMPACT_CHANGED_MAX).map(({ path, action }) => ({ path, action }));
    if (result.changed_files.length > COMPACT_CHANGED_MAX) out.changed_files_total = result.changed_files.length;
  }
  if (result.checks !== undefined) out.checks = compactChecks(result.checks);
  if (result.screenshots !== undefined) out.screenshots = compactScreenshots(result.screenshots);
  // Deliberately omitted: logs, observations, per-file hashes, raw output of passing checks.
  return out;
}
