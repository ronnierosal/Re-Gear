#!/usr/bin/env node
// Read the whole-dock trial's outcome out of the running plugin. Read-only.
//
// The only record of where a Safe Disconnect stopped is in the plugin process:
// `_whole_dock_trial_status` (phase, release_stage, release.code, arm_stage,
// arm_code; on 0.3.110+ also in_flight), served by
// get_egpu_disconnect_status("whole_dock_trial"). It is not on disk and not
// readable over SSH. Held inhibitors and journey-log silence say nothing about
// it -- the trial lease is retained on every outcome after preflight, and
// nothing after the portable return writes the journey log -- so this read
// comes BEFORE any reasoning about phases, and before installing anything,
// because a plugin restart discards it.
//
// Usage, from the dev machine with an SSH tunnel to Steam's CDP port:
//   ssh -N -L 19224:127.0.0.1:8080 -i ~/.ssh/hdm_ally_deploy_v2 deck@steamdeck.local &
//   node scripts/probe_whole_dock_trial_status.mjs http://127.0.0.1:19224
//   node scripts/probe_whole_dock_trial_status.mjs http://127.0.0.1:19224 --watch
//
// It reaches the backend the way the plugin's own frontend does: the loader's
// plugin API (`connect(version, name).call(method, ...args)`, the same object
// @decky/api wraps), evaluated in Steam's SharedJSContext. Every method it
// calls is a read: the disconnect status views, sleep readiness, and the
// snapshot's sleep_guard. It never calls a consuming or mutating RPC, and a
// test pins that. Port 19223 belongs to another agent's session; use your own.

const debuggerBase = process.argv.slice(2).find((value) => !value.startsWith("--"))
  ?? "http://127.0.0.1:19224";
const watch = process.argv.includes("--watch");
const option = (name, fallback) => {
  const raw = process.argv.find((value) => value.startsWith(`${name}=`));
  if (!raw) return fallback;
  const value = Number(raw.slice(name.length + 1));
  if (!Number.isFinite(value) || value <= 0) throw new Error(`Invalid ${name}`);
  return value;
};
const intervalMs = option("--interval-ms", 250);
const timeoutMs = option("--timeout-ms", 120_000);

async function evaluate(expression) {
  const targets = await fetch(`${debuggerBase}/json`).then((response) => response.json());
  const target = targets.find((item) => item.title === "SharedJSContext");
  if (!target?.webSocketDebuggerUrl) throw new Error("SharedJSContext CDP target was not found");
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  const pending = new Map();
  let nextId = 0;
  const call = (method, params = {}) => {
    const id = ++nextId;
    socket.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
  };
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    const request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id);
    if (message.error) request.reject(new Error(message.error.message));
    else request.resolve(message.result);
  });
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  try {
    return await call("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  } finally {
    socket.close();
  }
}

// Read-only by construction. The list is data so the test can pin it.
export const READ_ONLY_CALLS = [
  ["get_egpu_disconnect_status", "whole_dock_trial"],
  ["get_egpu_disconnect_status", "whole_dock_record"],
  ["get_egpu_disconnect_status", "power_status"],
  ["get_egpu_disconnect_status"],
  ["get_sleep_readiness"],
];

const expression = String.raw`(async () => {
  const out = { resolved: false, api_version: null, calls: {}, pending_record: null, sleep_guard: null };
  try { out.pending_record = window.localStorage.getItem("regear.whole-dock.pending-request"); } catch { out.pending_record = "unreadable"; }
  const init = window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit;
  if (typeof init?.connect !== "function") { out.reason = "loader api init is absent"; return out; }
  let api = null;
  try { api = init.connect(2, "Re-Gear"); } catch (error) {
    try { api = init.connect(1, "Re-Gear"); } catch (fallback) { out.reason = "connect refused: " + String(fallback); return out; }
  }
  if (typeof api?.call !== "function") { out.reason = "plugin api has no call"; return out; }
  out.api_version = api._version ?? null;
  const calls = ${JSON.stringify(READ_ONLY_CALLS)};
  for (const [method, ...args] of calls) {
    const key = [method, ...args].join(":");
    try { out.calls[key] = await api.call(method, ...args); }
    catch (error) { out.calls[key] = { error: String(error) }; }
  }
  try {
    const snapshot = await api.call("get_snapshot");
    out.sleep_guard = snapshot?.snapshot?.sleep_guard ?? null;
  } catch (error) { out.sleep_guard = { error: String(error) }; }
  out.resolved = true;
  return out;
})()`;

const evaluation = await evaluate(expression);

const result = evaluation.result?.value;
if (!result?.resolved) {
  throw new Error(`plugin API could not be reached: ${result?.reason ?? "no result"}`);
}
if (!watch) {
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  process.exit(0);
}

// A Gamescope restart replaces SharedJSContext, so every sample reconnects to
// CDP. A brief unavailable sample is expected and is useful timing evidence;
// the probe never interprets it as teardown success or failure.
const watchExpression = String.raw`(async () => {
  const out = { resolved: false, status: null, pending_record_present: false, unplug_prompt_visible: false };
  const init = window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit;
  if (typeof init?.connect !== "function") return out;
  let api = null;
  try { api = init.connect(2, "Re-Gear"); } catch {
    try { api = init.connect(1, "Re-Gear"); } catch { return out; }
  }
  if (typeof api?.call !== "function") return out;
  try { out.status = await api.call("get_egpu_disconnect_status", "whole_dock_trial"); }
  catch { return out; }
  try { out.pending_record_present = window.localStorage.getItem("regear.whole-dock.pending-request") !== null; }
  catch { out.pending_record_present = null; }
  out.unplug_prompt_visible = Boolean(document.body?.innerText?.includes("Unplug the eGPU now"));
  out.resolved = true;
  return out;
})()`;

const sleep = (delay) => new Promise((resolve) => setTimeout(resolve, delay));
const started = Date.now();
const samples = [];
let lastSignature = "";
let sawRunning = false;
let terminalAt = null;

function addSample(reading, observedMs) {
  const status = reading?.status;
  const sample = reading?.resolved ? {
    observed_ms: observedMs,
    code: typeof status?.code === "string" ? status.code : "",
    busy: status?.busy === true,
    in_flight: status?.in_flight === true,
    phase: typeof status?.phase === "string" ? status.phase : "",
    backend_elapsed_s: Number.isInteger(status?.elapsed_s) ? status.elapsed_s : null,
    release_stage: typeof status?.release_stage === "string" ? status.release_stage : "",
    pending_record_present: reading.pending_record_present,
    unplug_prompt_visible: reading.unplug_prompt_visible === true,
  } : { observed_ms: observedMs, code: "probe.plugin_unavailable" };
  const signature = JSON.stringify({ ...sample, observed_ms: 0, backend_elapsed_s: null });
  if (signature !== lastSignature) {
    samples.push(sample);
    lastSignature = signature;
    process.stderr.write(`[${(observedMs / 1000).toFixed(2)}s] ${sample.code}${sample.phase ? ` / ${sample.phase}` : ""}\n`);
  }
  return sample;
}

while (Date.now() - started <= timeoutMs) {
  const observedMs = Date.now() - started;
  let reading = null;
  try {
    const next = await evaluate(watchExpression);
    reading = next.result?.value ?? null;
  } catch {
    // Gamescope can remove the target between discovery and evaluation.
  }
  const sample = addSample(reading, observedMs);
  if (sample.busy && sample.in_flight) sawRunning = true;
  if (sawRunning && sample.code !== "probe.plugin_unavailable" && !sample.busy && !terminalAt) {
    terminalAt = observedMs;
  }
  if (terminalAt !== null && (sample.unplug_prompt_visible || observedMs - terminalAt >= 15_000)) break;
  await sleep(intervalMs);
}

const final = samples.at(-1) ?? null;
const phaseEntries = samples.filter((sample, index) => sample.phase
  && sample.phase !== samples[index - 1]?.phase);
const phase_timeline = phaseEntries.map((sample, index) => {
  const next = phaseEntries[index + 1]?.observed_ms ?? terminalAt ?? final?.observed_ms ?? sample.observed_ms;
  return { phase: sample.phase, entered_ms: sample.observed_ms,
    observed_duration_ms: Math.max(0, next - sample.observed_ms) };
});
const transport_gaps = samples.flatMap((sample, index) => {
  if (sample.code !== "probe.plugin_unavailable") return [];
  const resumed = samples.slice(index + 1).find((candidate) => candidate.code !== "probe.plugin_unavailable");
  return [{ unavailable_ms: sample.observed_ms,
    resumed_ms: resumed?.observed_ms ?? null,
    observed_duration_ms: resumed ? resumed.observed_ms - sample.observed_ms : null }];
});
const popupObservedAt = samples.find((sample) => sample.unplug_prompt_visible)?.observed_ms ?? null;
const report = {
  schema_version: 1,
  read_only: true,
  interval_ms: intervalMs,
  timeout_ms: timeoutMs,
  saw_running: sawRunning,
  terminal_observed_ms: terminalAt,
  popup_observed_ms: popupObservedAt,
  popup_settle_ms: terminalAt !== null && popupObservedAt !== null
    ? Math.max(0, popupObservedAt - terminalAt) : null,
  phase_timeline,
  transport_gaps,
  samples,
  final,
};
process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
if (!sawRunning || terminalAt === null) process.exitCode = 2;
