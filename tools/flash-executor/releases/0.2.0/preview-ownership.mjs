import { execFile } from "node:child_process";
import path from "node:path";
import { promisify } from "node:util";

const exec = promisify(execFile);
const system = path.join(process.env.SystemRoot ?? "C:\\Windows", "System32");
const parentScript = [
  "$ErrorActionPreference = 'Stop'",
  "$ProgressPreference = 'SilentlyContinue'",
  "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)",
  "$processes = @(Get-CimInstance Win32_Process -Property ProcessId,ParentProcessId | Select-Object ProcessId,ParentProcessId)",
  "[Console]::Out.Write((ConvertTo-Json -InputObject $processes -Compress))",
].join("\r\n");

function unresolved(port, cause) {
  const error = new Error("Could not enumerate local TCP ownership for port " + port + ".", { cause });
  error.code = "preview_ownership_unresolved";
  return error;
}

async function listenerOwners(port, signal) {
  try {
    const { stdout } = await exec(path.join(system, "netstat.exe"), ["-ano"], { signal, timeout: 5000, windowsHide: true });
    const owners = new Set();
    for (const line of stdout.split(/\r?\n/)) {
      if (!/^\s*TCP\s/i.test(line)) continue;
      const [, local, foreign, , pid, extra] = line.trim().split(/\s+/);
      if (!local || !foreign || !/^\d+$/.test(pid ?? "") || extra) throw new Error("Invalid local socket listing.");
      // LISTEN rows have an unspecified remote address and port 0 in both address families.
      if (local.endsWith(":" + port) && (foreign === "0.0.0.0:0" || foreign === "[::]:0")) owners.add(Number(pid));
    }
    return [...owners];
  } catch (cause) {
    signal?.throwIfAborted();
    throw unresolved(port, cause);
  }
}

async function parentProcesses(port, signal) {
  try {
    const command = Buffer.from(parentScript, "utf16le").toString("base64");
    const { stdout } = await exec(path.join(system, "WindowsPowerShell", "v1.0", "powershell.exe"),
      ["-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", command],
      { signal, timeout: 8000, windowsHide: true });
    return new Map(JSON.parse(stdout).map((item) => [Number(item.ProcessId), Number(item.ParentProcessId)]));
  } catch (cause) {
    signal?.throwIfAborted();
    throw unresolved(port, cause);
  }
}

function reaches(pid, rootPid, parents) {
  let current = pid;
  const seen = new Set();
  while (Number.isSafeInteger(current) && current > 0 && !seen.has(current)) {
    seen.add(current);
    if (current === rootPid) return true;
    current = parents.get(current);
  }
  return false;
}

/**
 * Prove every LISTENING socket on the port belongs to rootPid or one of its
 * descendants. Returns the owning pids, or throws with a clear reason.
 */
export async function verifyOwnership(port, rootPid, signal) {
  if (!Number.isSafeInteger(rootPid) || rootPid <= 0) {
    throw new Error("preview_ownership_unresolved: no spawned process id to attribute the listener to.");
  }
  const owners = await listenerOwners(port, signal);
  if (!owners.length) return { ok: false, reason: "preview_port_not_listening" };
  const parents = await parentProcesses(port, signal);
  const foreign = owners.filter((pid) => !reaches(pid, rootPid, parents));
  if (foreign.length) {
    const error = new Error("Port " + port + " has a listener outside the job's preview process tree.");
    error.code = "preview_owner_mismatch";
    throw error;
  }
  return { ok: true, owners };
}

/** True when any local listener already occupies the port (pre-check before spawn). */
export async function portHasListeners(port, signal) {
  return (await listenerOwners(port, signal)).length > 0;
}
