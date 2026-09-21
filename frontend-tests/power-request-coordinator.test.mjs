import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/power-request-coordinator.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { createPowerRequestCoordinator, startPowerStatusRefresh } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`,
);

const firstId = "a".repeat(32);
const secondId = "b".repeat(32);
const attachment = `${"c".repeat(64)}:${"d".repeat(64)}`;
const otherAttachment = `${"e".repeat(64)}:${"f".repeat(64)}`;
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const reply = (overrides = {}) => ({
  schema_version: 1, request_id: firstId, power_action: "sleep", route_action: "whole_dock_sleep_connected",
  busy: false, power_requested: true, ok: true,
  code: "dock_power.request_accepted_unverified", ...overrides,
});
function harness(options = {}) {
  const calls = [];
  let reading;
  let reads = 0;
  let issued = 0;
  const coordinator = createPowerRequestCoordinator({
    execute: async (...args) => {
      calls.push(args);
      return options.execute ? options.execute(...args) : reply({ route_action: args[0] });
    },
    readStatus: async () => { reads++; return options.readStatus ? options.readStatus() : reading; },
  }, { requestId: options.requestId ?? (() => issued++ === 0 ? firstId : secondId), onChange: options.onChange });
  return { coordinator, calls, setReading(value) { reading = value; }, get reads() { return reads; } };
}

test("capture alone neither executes nor polls; cancel before choice returns to idle", () => {
  const h = harness();
  const choice = h.coordinator.captureSleep(attachment);
  assert.ok(choice);
  assert.equal(h.coordinator.read().phase, "choosing");
  assert.equal(h.coordinator.read().intent, "sleep");
  assert.equal(h.calls.length, 0);
  assert.equal(h.reads, 0);
  choice.cancel();
  assert.equal(h.coordinator.read().phase, "idle");
});

test("sleep capture does not expose the cable-retained disconnect route", async () => {
  const h = harness();
  const choice = h.coordinator.captureSleep(attachment);
  assert.deepEqual(Object.keys(choice).sort(), ["cancel", "keepConnectedAndSleep"]);
  assert.equal(choice.disconnectAndSleep, undefined);
  await choice.keepConnectedAndSleep();
  assert.deepEqual(h.calls, [["whole_dock_sleep_connected", attachment, firstId]]);
  assert.equal(h.coordinator.read().action, "whole_dock_sleep_connected");
  assert.equal(h.coordinator.read().phase, "requested");
  await choice.keepConnectedAndSleep();
  assert.equal(h.calls.length, 1);
});

test("keep-connected sleep uses its explicit route without local teardown or reconnect", async () => {
  const h = harness();
  await h.coordinator.captureSleep(attachment).keepConnectedAndSleep();
  assert.deepEqual(h.calls, [["whole_dock_sleep_connected", attachment, firstId]]);
  assert.equal(h.coordinator.read().intent, "sleep");
});

test("no-dock empty token preserves ordinary shutdown and sleep intents", async () => {
  for (const intent of ["sleep", "shutdown"]) {
    const h = harness({ execute: async (route_action) => reply({ power_action: intent, route_action }) });
    if (intent === "sleep") await h.coordinator.captureSleep().keepConnectedAndSleep();
    else await h.coordinator.captureShutdown().confirm();
    assert.deepEqual(h.calls, [[intent === "sleep" ? "whole_dock_sleep_connected" : "whole_dock_shutdown", "", firstId]]);
    assert.equal(h.coordinator.read().intent, intent);
    assert.equal(h.coordinator.read().phase, "requested");
  }
});

test("invalid identity or request ids cannot enter confirmation or dispatch", () => {
  for (const token of [null, 7, "invalid", "c".repeat(129)]) {
    const h = harness();
    assert.equal(h.coordinator.captureSleep(token), null);
    assert.equal(h.coordinator.captureShutdown(token), null);
    assert.equal(h.calls.length, 0);
  }
  for (const id of ["", "A".repeat(32), "a".repeat(31), null]) {
    const h = harness({ requestId: () => id });
    assert.equal(h.coordinator.captureShutdown(attachment), null);
    assert.equal(h.calls.length, 0);
  }
});

test("old confirmation handles cannot cancel or execute a newer captured request", async () => {
  let id = firstId;
  const h = harness({ requestId: () => id, execute: async () => reply({ request_id: secondId, power_action: "shutdown", route_action: "whole_dock_shutdown" }) });
  const old = h.coordinator.captureSleep(attachment);
  old.cancel();
  id = secondId;
  const current = h.coordinator.captureShutdown(otherAttachment);
  old.cancel();
  await old.keepConnectedAndSleep();
  assert.equal(h.coordinator.read().intent, "shutdown");
  assert.equal(h.coordinator.read().phase, "choosing");
  await current.confirm();
  assert.deepEqual(h.calls, [["whole_dock_shutdown", otherAttachment, secondId]]);
});

test("in-flight execution cannot be canceled, replaced, or double dispatched", async () => {
  const waiting = deferred();
  const h = harness({ execute: () => waiting.promise });
  const choice = h.coordinator.captureSleep(attachment);
  const executing = choice.keepConnectedAndSleep();
  choice.cancel();
  assert.equal(h.coordinator.captureShutdown(otherAttachment), null);
  await choice.keepConnectedAndSleep();
  assert.equal(h.calls.length, 1);
  waiting.resolve(reply());
  await executing;
  assert.equal(h.coordinator.read().phase, "requested");
});

test("reentrant change notifications cannot create a second active capture", () => {
  let coordinator;
  const attempts = [];
  const h = harness({ onChange: () => {
    if (coordinator?.read().phase === "choosing") attempts.push(coordinator.captureShutdown(otherAttachment));
  } });
  coordinator = h.coordinator;
  assert.ok(coordinator.captureSleep(attachment));
  assert.ok(attempts.length > 0);
  assert.ok(attempts.every(value => value === null));
  assert.equal(h.calls.length, 0);
});

test("sleep observation requires the complete correlated success contract", async () => {
  const h = harness({ execute: async () => reply({ sleep_cycle_observed: true, code: "dock_power.sleep_cycle_observed" }) });
  await h.coordinator.captureSleep(attachment).keepConnectedAndSleep();
  assert.equal(h.coordinator.read().phase, "sleep_observed");
  for (const changed of [
    { sleep_cycle_observed: false }, { code: "dock_power.request_accepted_unverified" },
    { busy: true }, { ok: false }, { power_requested: false },
    { power_action: "shutdown" }, { route_action: "whole_dock_shutdown" },
    { request_id: secondId }, { schema_version: 2 },
  ]) {
    const alternate = harness({ execute: async () => reply({ sleep_cycle_observed: true, code: "dock_power.sleep_cycle_observed", ...changed }) });
    await alternate.coordinator.captureSleep(attachment).keepConnectedAndSleep();
    assert.notEqual(alternate.coordinator.read().phase, "sleep_observed", JSON.stringify(changed));
  }
});

test("unequivocal refusal releases the active guard for a new user choice", async () => {
  const h = harness({ execute: async () => reply({ power_requested: false, ok: false, code: "dock_power.sleep_unverified" }) });
  await h.coordinator.captureSleep(attachment).keepConnectedAndSleep();
  assert.equal(h.coordinator.read().phase, "refused");
  assert.ok(h.coordinator.captureShutdown(attachment));
  assert.equal(h.calls.length, 1);
});

test("reply loss and malformed replies retain uncertainty without automatic replay", async () => {
  for (const response of [null, {}, reply({ request_id: secondId }), reply({ power_action: "shutdown" }), reply({ route_action: "whole_dock_shutdown" })]) {
    const h = harness({ execute: async () => response });
    await h.coordinator.captureSleep(attachment).keepConnectedAndSleep();
    assert.equal(h.coordinator.read().phase, "uncertain");
    assert.equal(h.coordinator.captureShutdown(attachment), null);
    assert.equal(h.calls.length, 1);
  }
  const h = harness({ execute: async () => { throw new Error("reply lost"); } });
  await h.coordinator.captureSleep(attachment).keepConnectedAndSleep();
  assert.equal(h.coordinator.read().phase, "uncertain");
  h.setReading(reply({ sleep_cycle_observed: true, code: "dock_power.sleep_cycle_observed" }));
  await h.coordinator.refresh();
  assert.equal(h.coordinator.read().phase, "sleep_observed");
  assert.equal(h.calls.length, 1);
});

test("an unrelated global status cannot replace this request's state", async () => {
  const h = harness({ execute: async () => reply({ busy: true, power_requested: false, ok: false, code: "dock_teardown.trial_running" }) });
  await h.coordinator.captureSleep(attachment).keepConnectedAndSleep();
  assert.equal(h.coordinator.read().phase, "pending");
  const before = { ...h.coordinator.read() };
  h.setReading(reply({ request_id: secondId, sleep_cycle_observed: true, code: "dock_power.sleep_cycle_observed" }));
  await h.coordinator.refresh();
  assert.deepEqual(h.coordinator.read(), before);
  assert.equal(h.calls.length, 1);
});

test("late status from a canceled capture cannot overwrite a newer intent", async () => {
  const waiting = deferred();
  let id = firstId;
  const h = harness({ requestId: () => id, readStatus: () => waiting.promise });
  const old = h.coordinator.captureSleep(attachment);
  const refreshing = h.coordinator.refresh();
  old.cancel();
  id = secondId;
  assert.ok(h.coordinator.captureShutdown(otherAttachment));
  waiting.resolve(reply({ sleep_cycle_observed: true, code: "dock_power.sleep_cycle_observed" }));
  await refreshing;
  assert.equal(h.coordinator.read().intent, "shutdown");
  assert.equal(h.coordinator.read().phase, "choosing");
  assert.equal(h.calls.length, 0);
});

test("dispose retires handlers and ignores late execution; a new instance does not replay", async () => {
  const waiting = deferred();
  const h = harness({ execute: () => waiting.promise });
  const handle = h.coordinator.captureShutdown(attachment);
  const running = handle.confirm();
  h.coordinator.dispose();
  waiting.resolve(reply({ power_action: "shutdown" }));
  await running;
  await handle.confirm();
  handle.cancel();
  assert.equal(h.coordinator.read().phase, "disposed");
  assert.equal(h.coordinator.captureSleep(), null);
  assert.equal(h.calls.length, 1);
  const fresh = harness();
  assert.equal(fresh.coordinator.read().phase, "idle");
  assert.equal(fresh.calls.length, 0);
  assert.equal(fresh.reads, 0);
});

test("a late pending poll cannot overwrite a newer direct accepted reply", async () => {
  const execution = deferred();
  const observation = deferred();
  const h = harness({ execute: () => execution.promise, readStatus: () => observation.promise });
  const submitting = h.coordinator.captureSleep(attachment).keepConnectedAndSleep();
  const refreshing = h.coordinator.refresh();
  execution.resolve(reply());
  await submitting;
  assert.equal(h.coordinator.read().phase, "requested");
  observation.resolve(reply({ busy: true, power_requested: false, ok: false, code: "dock_teardown.trial_running" }));
  await refreshing;
  assert.equal(h.coordinator.read().phase, "requested");
  assert.equal(h.calls.length, 1);
});

test("newer correlated readback wins over an older delayed status response", async () => {
  const first = deferred();
  const second = deferred();
  let reads = 0;
  const h = harness({
    execute: async () => { throw new Error("reply lost"); },
    readStatus: () => reads++ === 0 ? first.promise : second.promise,
  });
  await h.coordinator.captureSleep(attachment).keepConnectedAndSleep();
  const earlier = h.coordinator.refresh();
  const later = h.coordinator.refresh();
  second.resolve(reply());
  await later;
  assert.equal(h.coordinator.read().phase, "requested");
  first.resolve(reply({ power_requested: false, ok: false, code: "dock_power.sleep_unverified" }));
  await earlier;
  assert.equal(h.coordinator.read().phase, "requested");
  assert.equal(h.coordinator.captureShutdown(otherAttachment), null);
});

test("RPC adapter sends exactly the selected route, captured token, and correlation id", async () => {
  const calls = [];
  const portSource = readFileSync(new URL("../src/power-request-port.ts", import.meta.url), "utf8");
  const js = ts.transpileModule(portSource, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
  }).outputText.replace(/^import[^;]*;$/gm, "").replace(/export /g, "");
  const callable = (name) => async (...args) => { calls.push([name, args]); return { marker: name }; };
  const port = new Function("callable", `${js}\nreturn powerRequestPort;`)(callable);
  assert.equal(calls.length, 0, "loading the adapter must not submit or poll");
  for (const action of ["whole_dock_sleep_connected", "whole_dock_shutdown"]) {
    const result = await port.execute(action, attachment, firstId);
    assert.deepEqual(calls.at(-1), ["execute_egpu_disconnect", [true, "", "disconnect", action, true, attachment, firstId]]);
    assert.deepEqual(result, { marker: "execute_egpu_disconnect" });
  }
  await port.readStatus();
  assert.deepEqual(calls.at(-1), ["get_egpu_disconnect_status", ["power_status"]]);
  assert.equal(calls.length, 3);
});

test("observed submission prevents an older direct refusal from releasing ownership", async () => {
  const execution = deferred();
  const h = harness({ execute: () => execution.promise });
  const submitting = h.coordinator.captureSleep(attachment).keepConnectedAndSleep();
  h.setReading(reply());
  await h.coordinator.refresh();
  assert.equal(h.coordinator.read().phase, "requested");
  execution.resolve(reply({ power_requested: false, ok: false, code: "dock_power.sleep_unverified" }));
  await submitting;
  assert.equal(h.coordinator.read().phase, "uncertain");
  assert.equal(h.coordinator.captureShutdown(otherAttachment), null);
  assert.equal(h.calls.length, 1);
});

test("submission latch survives reply loss or malformed response and a later refusal", async () => {
  for (const failure of ["transport", "malformed"]) {
    const execution = deferred();
    const h = harness({ execute: () => execution.promise });
    const submitting = h.coordinator.captureSleep(attachment).keepConnectedAndSleep();
    h.setReading(reply());
    await h.coordinator.refresh();
    assert.equal(h.coordinator.read().phase, "requested");
    if (failure === "transport") execution.reject(new Error("transport interrupted"));
    else execution.resolve({ schema_version: 1, request_id: firstId });
    await submitting;
    assert.equal(h.coordinator.read().phase, "uncertain", failure);
    h.setReading(reply({ power_requested: false, ok: false, code: "dock_power.sleep_unverified" }));
    await h.coordinator.refresh();
    assert.equal(h.coordinator.read().phase, "uncertain", failure);
    assert.equal(h.coordinator.captureShutdown(otherAttachment), null, failure);
    assert.equal(h.calls.length, 1);
  }
});

test("busy status recording power submission also prevents a later refusal from unlocking", async () => {
  const execution = deferred();
  const h = harness({ execute: () => execution.promise });
  const submitting = h.coordinator.captureSleep(attachment).keepConnectedAndSleep();
  h.setReading(reply({ busy: true }));
  await h.coordinator.refresh();
  execution.resolve(reply({ power_requested: false, ok: false, code: "dock_power.sleep_unverified" }));
  await submitting;
  assert.equal(h.coordinator.read().phase, "uncertain");
  assert.equal(h.coordinator.captureShutdown(otherAttachment), null);
  assert.equal(h.calls.length, 1);
});

test("refusal poll cannot release ownership before the unresolved direct execution replies", async () => {
  const execution = deferred();
  const h = harness({ execute: () => execution.promise });
  const submitting = h.coordinator.captureSleep(attachment).keepConnectedAndSleep();
  h.setReading(reply({ power_requested: false, ok: false, code: "dock_power.sleep_unverified" }));
  await h.coordinator.refresh();
  assert.equal(h.coordinator.read().phase, "pending");
  assert.equal(h.coordinator.read().code, "power.awaiting_direct_reply");
  assert.equal(h.coordinator.captureShutdown(otherAttachment), null);
  execution.resolve(reply());
  await submitting;
  assert.equal(h.coordinator.read().phase, "requested");
  assert.equal(h.coordinator.captureShutdown(otherAttachment), null);
  assert.equal(h.calls.length, 1);
});

test("after transport failure a fresh unequivocal non-submission permits a new user choice", async () => {
  const h = harness({ execute: async () => { throw new Error("transport interrupted"); } });
  await h.coordinator.captureSleep(attachment).keepConnectedAndSleep();
  assert.equal(h.coordinator.read().phase, "uncertain");
  assert.equal(h.coordinator.captureShutdown(otherAttachment), null);
  h.setReading(reply({ power_requested: false, ok: false, code: "dock_power.sleep_unverified" }));
  await h.coordinator.refresh();
  assert.equal(h.coordinator.read().phase, "refused");
  assert.equal(h.calls.length, 1, "readback must not automatically retry");
  const fresh = h.coordinator.captureShutdown(otherAttachment);
  assert.ok(fresh);
  assert.equal(h.coordinator.read().phase, "choosing");
  assert.equal(h.coordinator.read().intent, "shutdown");
  assert.equal(h.calls.length, 1, "new capture still requires explicit confirmation");
});

test("real ordinary shutdown acceptance and refusal codes are recognized", async () => {
  for (const [code, requested, phase] of [
    ["safe_disconnect.poweroff_request_accepted_unverified", true, "requested"],
    ["safe_disconnect.poweroff_failed", false, "refused"],
    ["safe_disconnect.root_required", false, "refused"],
  ]) {
    const h = harness({ execute: async () => reply({ power_action: "shutdown",
      route_action: "whole_dock_shutdown", code, power_requested: requested, ok: requested }) });
    await h.coordinator.captureShutdown().confirm();
    assert.equal(h.coordinator.read().phase, phase, code);
    assert.equal(!!h.coordinator.captureSleep(), !requested, code);
    assert.equal(h.calls.length, 1);
  }
});

test("unverified backend submissions never unlock a new power choice", async () => {
  for (const [intent, code] of [
    ["sleep", "dock_power.request_unverified"], ["sleep", "dock_power.unresolved"],
    ["sleep", "dock_power.sleep_protection_unverified"],
    ["shutdown", "safe_disconnect.poweroff_timeout"],
    ["shutdown", "safe_disconnect.poweroff_unavailable"],
    ["shutdown", "dock_teardown.trial_unresolved"],
    ["shutdown", "dock_power.already_consumed"],
  ]) {
    const route = intent === "sleep" ? "whole_dock_sleep_connected" : "whole_dock_shutdown";
    const payload = reply({ power_action: intent, route_action: route,
      code, power_requested: false, ok: false });
    const h = harness({ execute: async () => payload });
    if (intent === "sleep") await h.coordinator.captureSleep().keepConnectedAndSleep();
    else await h.coordinator.captureShutdown().confirm();
    assert.equal(h.coordinator.read().phase, "uncertain", code);
    assert.equal(h.coordinator.captureSleep(), null, code);
    h.setReading(payload);
    await h.coordinator.refresh();
    assert.equal(h.coordinator.read().phase, "uncertain", code);
    assert.equal(h.coordinator.captureShutdown(), null, code);
    assert.equal(h.calls.length, 1);
  }
});

test("only exact producer codes for the captured intent may settle refusal", async () => {
  for (const code of ["dock_power.invented", "dock_teardown.invented", "dock_mutation.invented",
    "safe_disconnect.root_required", "safe_disconnect.poweroff_failed",
    "dock_power.request_accepted_unverified", "dock_power.sleep_cycle_observed"]) {
    const h = harness({ execute: async () => reply({ code, power_requested: false, ok: false }) });
    await h.coordinator.captureSleep().keepConnectedAndSleep();
    assert.equal(h.coordinator.read().phase, "uncertain", code);
    assert.equal(h.coordinator.captureShutdown(), null, code);
  }
});

test("ordinary shutdown readback preserves accepted submission against later refusal", async () => {
  const h = harness({ execute: async () => { throw new Error("reply interrupted"); } });
  await h.coordinator.captureShutdown().confirm();
  h.setReading(reply({ power_action: "shutdown", route_action: "whole_dock_shutdown",
    code: "safe_disconnect.poweroff_request_accepted_unverified" }));
  await h.coordinator.refresh();
  assert.equal(h.coordinator.read().phase, "requested");
  h.setReading(reply({ power_action: "shutdown", route_action: "whole_dock_shutdown",
    code: "safe_disconnect.poweroff_failed", power_requested: false, ok: false }));
  await h.coordinator.refresh();
  assert.equal(h.coordinator.read().phase, "uncertain");
  assert.equal(h.coordinator.captureSleep(), null);
  assert.equal(h.calls.length, 1);
});

test("status refresh is single-flight and survives presentation changes until owner cleanup", async () => {
  const slow = deferred();
  const queued = [];
  let reads = 0;
  const owner = { refresh: () => { reads++; return reads === 1 ? slow.promise : Promise.resolve(); } };
  let canceled = 0;
  const stop = startPowerStatusRefresh(owner, (run) => { queued.push(run); return queued.length; }, () => { canceled++; });
  queued.shift()();
  await Promise.resolve();
  assert.equal(reads, 1);
  assert.equal(queued.length, 0, "a slow read cannot overlap another read");
  // A tile change does not own or stop this host-level loop.
  slow.resolve();
  await Promise.resolve(); await Promise.resolve();
  assert.equal(queued.length, 1);
  queued.shift()();
  await Promise.resolve(); await Promise.resolve();
  assert.equal(reads, 2);
  assert.equal(queued.length, 1, "the same owner continues correlated recovery");
  stop();
  assert.equal(canceled, 1);
});
