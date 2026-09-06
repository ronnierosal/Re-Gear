import assert from "node:assert/strict";
import test from "node:test";
import { sanitizeTdpStatus, tdpControls, tdpMessage, tdpResultMessage, TdpRequestGate } from "../src/tdp-ui.ts";

const ready = { schema_version: 1, enabled: true, can_enable: true, ready: true, code: "tdp.ready", current_watts: 17, minimum_watts: 7, maximum_watts: 30, restore_available: false, recovery_required: false, last_result: null, auto_tdp_available: false };

test("verified readiness controls apply; numbers alone never enable it", () => {
  assert.equal(tdpControls(sanitizeTdpStatus(ready)).canApply, true);
  assert.equal(tdpControls(sanitizeTdpStatus({ ...ready, ready: false })).canApply, false);
  assert.equal(sanitizeTdpStatus({ ...ready, code: "tdp.conflict" }), null);
  assert.equal(tdpControls(sanitizeTdpStatus({ ...ready, enabled: false, ready: false })).canToggle, true);
  assert.deepEqual(tdpControls(null), { canToggle: false, canApply: false, canRestore: false });
});

test("malformed schema, booleans, units and inconsistent bounds fail closed", () => {
  for (const change of [{ schema_version: 2 }, { enabled: 1 }, { ready: "true" }, { current_watts: NaN }, { maximum_watts: Infinity }, { minimum_watts: -1 }, { current_watts: 17.5 }, { current_watts: "17" }, { minimum_watts: 18 }, { maximum_watts: 16 }, { maximum_watts: 9999 }, { current_watts: null }, { last_result: undefined }, { auto_tdp_available: "true" }, { enabled: false }, { can_enable: false }]) {
    assert.equal(sanitizeTdpStatus({ ...ready, ...change }), null, JSON.stringify(change));
  }
  for (const value of [null, undefined, [], {}, true]) assert.equal(sanitizeTdpStatus(value), null);
});

test("Auto capability availability does not enable manual power control", () => {
  const status = sanitizeTdpStatus({ ...ready, auto_tdp_available: true, ready: false, enabled: false });
  assert.notEqual(status, null);
  assert.equal(tdpControls(status).canApply, false);
});

test("unknown codes are never displayed or trusted", () => {
  for (const code of ["private.error", "toString", "__proto__"]) {
    const status = sanitizeTdpStatus({ ...ready, code });
    assert.equal(status, null);
    assert.doesNotMatch(tdpMessage(status), /private|toString|__proto__/);
  }
});

test("missing numeric readings allow display but no enable or restore", () => {
  const value = { ...ready, enabled: false, can_enable: false, ready: false, code: "tdp.runtime_unavailable", current_watts: null, minimum_watts: null, maximum_watts: null };
  assert.notEqual(sanitizeTdpStatus(value), null);
  assert.equal(tdpControls(sanitizeTdpStatus({ ...value, enabled: true })).canToggle, true);
  assert.equal(sanitizeTdpStatus({ ...value, can_enable: true }), null);
  assert.equal(sanitizeTdpStatus({ ...value, restore_available: true }), null);
});

test("restore can be available while disabled; recovery overrides all actions", () => {
  const status = sanitizeTdpStatus({ ...ready, enabled: false, ready: false, restore_available: true });
  assert.equal(tdpControls(status).canRestore, true);
  assert.equal(tdpControls({ ...status, recovery_required: true }).canRestore, false);
  assert.equal(tdpControls({ ...ready, recovery_required: true }).canApply, false);
  assert.equal(tdpControls({ ...ready, recovery_required: true }).canToggle, true);
});

test("action results require known state and code with strict watts", () => {
  const last_result = { state: "applied", code: "tdp.readback_verified", requested_watts: 20, observed_watts: 20 };
  assert.match(tdpResultMessage(sanitizeTdpStatus({ ...ready, last_result })), /verified/);
  const recovered = sanitizeTdpStatus({ ...ready, last_result: { ...last_result, state: "blocked", code: "tdp.ownership_unverified" } });
  assert.match(tdpMessage(recovered), /Ready to adjust/);
  assert.match(tdpResultMessage(recovered), /ownership needs verification/);
  assert.equal(tdpControls(recovered).canApply, true);
  assert.match(tdpMessage(sanitizeTdpStatus({ ...ready, ready: false, code: "tdp.conflict", last_result })), /Another power controller/);
  for (const change of [{ state: "unknown" }, { code: "private.error" }, { requested_watts: true }, { observed_watts: Infinity }]) assert.equal(sanitizeTdpStatus({ ...ready, last_result: { ...last_result, ...change } }), null);
});

test("single inflight request suppresses duplicate writes and releases after failure", async () => {
  const gate = new TdpRequestGate();
  let release;
  let calls = 0;
  const first = gate.run(() => { calls++; return new Promise((resolve) => { release = resolve; }); });
  assert.equal(await gate.run(async () => { calls++; }), undefined);
  assert.equal(calls, 1);
  release("done");
  assert.equal(await first, "done");
  await assert.rejects(gate.run(async () => { throw new Error("failed"); }));
  assert.equal(await gate.run(async () => "next"), "next");
});

test("a rejected automatic dispatch cannot disable otherwise-ready manual controls", () => {
  const status = sanitizeTdpStatus({ ...ready, restore_available: true,
    last_result: { state: "blocked", code: "tdp.dispatch_rejected", requested_watts: 20, observed_watts: null } });
  assert.notEqual(status, null);
  assert.equal(tdpControls(status).canToggle, true);
  assert.equal(tdpControls(status).canApply, true);
  assert.equal(tdpControls(status).canRestore, true);
  assert.match(tdpResultMessage(status), /before changing power/);
});
