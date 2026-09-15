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
//
// It reaches the backend the way the plugin's own frontend does: the loader's
// plugin API (`connect(version, name).call(method, ...args)`, the same object
// @decky/api wraps), evaluated in Steam's SharedJSContext. Every method it
// calls is a read: the disconnect status views, sleep readiness, and the
// snapshot's sleep_guard. It never calls a consuming or mutating RPC, and a
// test pins that. Port 19223 belongs to another agent's session; use your own.

const debuggerBase = process.argv[2] ?? "http://127.0.0.1:19224";
const targets = await fetch(`${debuggerBase}/json`).then((response) => response.json());
const target = targets.find((item) => item.title === "SharedJSContext");
if (!target?.webSocketDebuggerUrl) {
  throw new Error("SharedJSContext CDP target was not found");
}

const socket = new WebSocket(target.webSocketDebuggerUrl);
const pending = new Map();
let nextId = 0;

function call(method, params = {}) {
  const id = ++nextId;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  const request = pending.get(message.id);
  if (!request) {
    return;
  }
  pending.delete(message.id);
  if (message.error) {
    request.reject(new Error(message.error.message));
  } else {
    request.resolve(message.result);
  }
});

await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});

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

const evaluation = await call("Runtime.evaluate", {
  expression,
  awaitPromise: true,
  returnByValue: true,
});
socket.close();

const result = evaluation.result?.value;
if (!result?.resolved) {
  throw new Error(`plugin API could not be reached: ${result?.reason ?? "no result"}`);
}
process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
