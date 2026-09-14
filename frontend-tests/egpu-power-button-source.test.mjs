import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";
const compile = (file) => ts.transpileModule(readFileSync(new URL(`../src/${file}`, import.meta.url), "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText.replace(/^import[^;]*;$/gm, "");
const bundle = ["power-request-coordinator.ts", "quick-access/expanded-command-center/power-choice-binding.ts",
  "quick-access/expanded-command-center/egpu-power-button-source.ts"].map(compile).join("\n");
const { createEgpuPowerButtonSource } = await import(`data:text/javascript;base64,${Buffer.from(bundle).toString("base64")}`);
const token = `${"a".repeat(64)}:${"b".repeat(64)}`;
const response = (call, overrides = {}) => ({ schema_version: 1, request_id: call[2],
  power_action: call[0] === "whole_dock_shutdown" ? "shutdown" : "sleep", route_action: call[0],
  busy: false, power_requested: true, ok: true, code: "dock_power.request_accepted_unverified", ...overrides });
const deferred = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; };
function setup() {
  let id = 0;
  const calls = [], evidenceReads = [];
  let statusReads = 0;
  const state = { evidence: { available: true, request: { attachmentToken: token, connectionLabel: "Observed dock" } },
    execute: (call) => response(call), status: () => response(calls.at(-1)) };
  const source = createEgpuPowerButtonSource({
    execute: async (...call) => { calls.push(call); return state.execute(call); },
    readStatus: async () => { statusReads++; return state.status(); },
  }, (intent) => { evidenceReads.push(intent); return state.evidence; },
  { requestId: () => (++id).toString(16).padStart(32, "0") });
  return { source, state, calls, evidenceReads, statusReads: () => statusReads };
}
for (const intent of ["sleep", "shutdown"]) {
  test(`${intent}: capture-only uses current caller facts and dispatches exact action once`, async () => {
    const h = setup();
    assert.equal(h.evidenceReads.length, 0);
    h.state.evidence.request = { attachmentToken: "", connectionLabel: "Observed ordinary/already-down route" };
    assert.deepEqual(h.source[intent === "sleep" ? "beginSleep" : "beginShutdown"](), { captured: true });
    const choice = h.source.read().choice;
    assert.equal(choice.connectionLabel, h.state.evidence.request.connectionLabel);
    assert.deepEqual(h.evidenceReads, [intent]);
    assert.equal(h.calls.length, 0);
    assert.equal(choice.keepConnectedAndSleep, undefined);
    await Promise.all([choice.confirm(), choice.confirm()]);
    assert.equal(h.calls.length, 1);
    assert.equal(h.calls[0][0], `whole_dock_${intent}`);
    assert.equal(h.calls[0][1], "");
    assert.equal(h.source.read().power.phase, "requested");
    choice.cancel();
    assert.equal(h.source.beginShutdown().captured, false);
    await choice.confirm();
    assert.equal(h.calls.length, 1);
    h.source.dispose();
  });
}
test("unavailable evidence retains reason; absent token/label never become empty facts", () => {
  const h = setup();
  h.state.evidence = { available: false, reason: "Attachment observation unavailable" };
  assert.deepEqual(h.source.beginSleep(), { captured: false, reason: "Attachment observation unavailable" });
  for (const request of [{ connectionLabel: "dock" }, { attachmentToken: token }]) {
    h.state.evidence = { available: true, request };
    assert.equal(h.source.beginSleep().captured, false);
    assert.equal(h.source.read().choice, null);
  }
  assert.equal(h.calls.length, 0);
});
test("cancel retires choosing; stale same-intent confirmation and cancel cannot operate replacement", async () => {
  const h = setup();
  h.source.beginSleep();
  const old = h.source.read().choice;
  old.cancel();
  assert.equal(h.source.read().power.phase, "idle");
  h.source.beginSleep();
  const current = h.source.read().choice;
  await old.confirm(); old.cancel();
  assert.equal(h.source.read().choice, current);
  assert.equal(h.calls.length, 0);
  await current.confirm();
  assert.equal(h.calls.length, 1);
});
for (const code of ["safe_disconnect.poweroff_timeout", "dock_power.unresolved"]) {
  test(`${code}: false flags retain uncertain guard through hide/reopen and refresh`, async () => {
    const h = setup();
    h.state.execute = (call) => response(call, { code, power_requested: false, ok: false });
    const seen = [];
    const hide = h.source.subscribe((v) => seen.push(v));
    h.source.beginShutdown(); const choice = h.source.read().choice;
    await choice.confirm();
    assert.equal(h.source.read().power.phase, "uncertain");
    hide(); const hidden = h.source.read();
    const reopen = h.source.subscribe((v) => seen.push(v));
    assert.equal(h.source.read(), hidden);
    choice.cancel(); await choice.confirm();
    assert.equal(h.source.beginSleep().captured, false);
    assert.equal(h.calls.length, 1);
    assert.equal(h.statusReads(), 0);
    h.state.status = () => response(h.calls[0], { code, power_requested: false, ok: false });
    await h.source.refresh();
    assert.equal(h.statusReads(), 1);
    assert.equal(h.source.read().choice, null);
    assert.equal(h.calls.length, 1);
    reopen(); h.source.dispose();
  });
}
test("proven refusal retires choice, preserves outcome, and permits fresh explicit request", async () => {
  const h = setup();
  h.state.execute = (call) => response(call, { code: "dock_power.preflight_changed", power_requested: false, ok: false });
  h.source.beginSleep(); await h.source.read().choice.confirm();
  assert.equal(h.source.read().choice, null);
  assert.equal(h.source.read().power.phase, "refused");
  assert.equal(h.source.read().power.code, "dock_power.preflight_changed");
  assert.equal(h.source.beginShutdown().captured, true);
  assert.equal(h.calls.length, 1);
});
test("pending and requested survive visibility changes; observed sleep remains after choice retires", async () => {
  const h = setup();
  h.state.execute = (call) => response(call, { code: "dock_power.request_pending", busy: true, power_requested: false });
  h.source.beginSleep(); const choice = h.source.read().choice;
  await choice.confirm();
  assert.equal(h.source.read().power.phase, "pending");
  for (const phase of ["pending", "requested"]) {
    const snapshot = h.source.read();
    const hide = h.source.subscribe(() => {}); hide();
    const reopen = h.source.subscribe(() => {});
    assert.equal(h.source.read(), snapshot);
    assert.equal(snapshot.power.phase, phase);
    assert.equal(h.source.beginShutdown().captured, false);
    choice.cancel(); await choice.confirm(); reopen();
    await h.source.refresh();
  }
  h.state.status = () => response(h.calls[0], { code: "dock_power.sleep_cycle_observed", sleep_cycle_observed: true });
  await h.source.refresh();
  assert.equal(h.source.read().choice, null);
  assert.equal(h.source.read().power.phase, "sleep_observed");
  assert.equal(h.calls.length, 1);
});
test("mismatched action reply cannot retire live choice", async () => {
  const h = setup();
  h.state.execute = (call) => response(call, { route_action: "whole_dock_sleep_connected" });
  h.source.beginSleep(); await h.source.read().choice.confirm();
  assert.equal(h.source.read().power.phase, "uncertain");
  assert.equal(h.source.beginShutdown().captured, false);
});
test("late status refusal cannot overtake direct accepted reply", async () => {
  const h = setup(), execution = deferred(), status = deferred();
  h.state.execute = () => execution.promise;
  h.state.status = () => status.promise;
  h.source.beginSleep(); const choice = h.source.read().choice;
  const submitted = choice.confirm();
  assert.equal(h.source.read().choice, null);
  const refreshed = h.source.refresh();
  execution.resolve(response(h.calls[0])); await submitted;
  status.resolve(response(h.calls[0], { code: "dock_power.preflight_changed", power_requested: false, ok: false }));
  await refreshed;
  assert.equal(h.source.read().power.phase, "requested");
  assert.equal(h.source.read().choice, null);
  assert.equal(h.source.beginShutdown().captured, false);
});
test("unload ignores late replies and forbids retained callbacks or new captures", async () => {
  const h = setup(), execution = deferred();
  h.state.execute = () => execution.promise;
  h.source.beginShutdown(); const choice = h.source.read().choice;
  const submitted = choice.confirm();
  assert.equal(h.source.read().choice, null);
  h.source.dispose();
  execution.resolve(response(h.calls[0])); await submitted;
  await choice.confirm(); choice.cancel(); await h.source.refresh();
  assert.equal(h.source.read().power.phase, "disposed");
  assert.equal(h.source.read().choice, null);
  assert.equal(h.source.beginSleep().captured, false);
  assert.equal(h.calls.length, 1);
  assert.equal(h.statusReads(), 0);
});
test("transport interruption remains guarded; idle render/subscription makes no calls", async () => {
  const h = setup();
  const hide = h.source.subscribe(() => {});
  h.source.read(); hide(); await h.source.refresh();
  assert.equal(h.calls.length, 0); assert.equal(h.statusReads(), 0);
  h.state.execute = () => { throw new Error("transport interrupted"); };
  h.source.beginSleep(); await h.source.read().choice.confirm();
  assert.equal(h.source.read().power.phase, "uncertain");
  assert.equal(h.source.beginSleep().captured, false);
  assert.equal(h.calls.length, 1);
});
