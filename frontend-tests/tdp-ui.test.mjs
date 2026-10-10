import assert from "node:assert/strict";
import test from "node:test";
import { sanitizeTdpStatus, tdpControls, tdpMessage, tdpResultMessage, TdpRequestGate, sanitizeManualPresets, manualPresetOptions, createCustomTdpDraft, validCustomTdpDraft, retireCustomTdpDraft } from "../src/tdp-ui.ts";

const ready = { schema_version: 1, enabled: true, can_enable: true, ready: true, code: "tdp.ready", current_watts: 17, minimum_watts: 7, maximum_watts: 30, restore_available: false, recovery_required: false, last_result: null, auto_tdp_available: false };

test("mode-specific power readiness remains visible without enabling writes", () => {
  for (const code of ["tdp.placement_unverified", "tdp.egpu_presence_unverified", "tdp.egpu_attached", "tdp.egpu_power_profile_unavailable", "tdp.docked_power_profile_unavailable"]) {
    const status = sanitizeTdpStatus({ ...ready, ready: false, can_enable: false, code });
    assert.notEqual(status, null);
    assert.equal(tdpControls(status).canApply, false);
    assert.doesNotMatch(tdpMessage(status), /tdp\./);
  }
});

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

const presets = () => [{ id: "low", watts: 10, admitted: true }, { id: "balanced", watts: 15, admitted: true }, { id: "high", watts: 25, admitted: true }];
test("fixed preset schema preserves intent IDs, values, labels and independent admission", () => {
  const value = presets(); value[1].admitted = false;
  const status = sanitizeTdpStatus({ ...ready, manual_presets: value });
  assert.deepEqual(manualPresetOptions(status).map(x => [x.id, x.watts, x.label, x.admitted]), [["low", 10, "Chill", true], ["balanced", 15, "Balanced", false], ["high", 25, "Performance", true]]);
});
test("malformed optional presets fail closed as a unit without breaking Manual", () => {
  const changes = [undefined, null, {}, [], presets().slice(1), [...presets(), presets()[0]], presets().reverse(), [presets()[0], presets()[0], presets()[2]],
    presets().map(x => ({ ...x, id: x.id === "low" ? "Chill" : x.id })), presets().map(x => ({ ...x, watts: x.watts === 10 ? 11 : x.watts })),
    presets().map(x => ({ ...x, admitted: "true" })), presets().map(x => ({ ...x, name: "private" })), presets().map(x => Object.create(x))];
  for (const manual_presets of changes) {
    assert.equal(sanitizeManualPresets(manual_presets), null);
    const status = sanitizeTdpStatus({ ...ready, manual_presets });
    assert.notEqual(status, null); assert.equal(tdpControls(status).canApply, true);
    assert.deepEqual(manualPresetOptions(status).map(x => x.admitted), [false, false, false]);
  }
});
test("preset property/index/entry accessors never execute or grant admission", () => {
  const value = { ...ready };
  Object.defineProperty(value, "manual_presets", { enumerable: true, get() { throw Error("private"); } });
  assert.equal(sanitizeTdpStatus(value).manual_presets, null);
  const indexed = presets(); Object.defineProperty(indexed, "0", { get() { throw Error("index"); } });
  assert.equal(sanitizeManualPresets(indexed), null);
  const entry = presets(); Object.defineProperty(entry[0], "admitted", { get() { throw Error("entry"); } });
  assert.equal(sanitizeManualPresets(entry), null);
});
test("current readiness, recovery and provider bounds override positive preset evidence", () => {
  for (const change of [{ enabled: false, ready: false }, { ready: false }, { recovery_required: true }]) {
    assert.deepEqual(manualPresetOptions(sanitizeTdpStatus({ ...ready, manual_presets: presets(), ...change })).map(x => x.admitted), [false, false, false]);
  }
  assert.deepEqual(manualPresetOptions(sanitizeTdpStatus({ ...ready, manual_presets: presets(), maximum_watts: 20 })).map(x => x.admitted), [true, true, false]);
});

test("Custom drafts use only current ready integer bounds and have revocable local lifetime", () => {
  for(const change of [{enabled:false,ready:false},{ready:false},{recovery_required:true},{can_enable:false},{code:"tdp.conflict"},{minimum_watts:NaN},{minimum_watts:"7"},{maximum_watts:Infinity},{minimum_watts:18},{maximum_watts:16},{maximum_watts:9999},{current_watts:17.5},{current_watts:null,minimum_watts:null,maximum_watts:null}])
    assert.equal(createCustomTdpDraft({...ready,...change}),null);
  for(const value of [NaN,Infinity,6,31,15.5,"15",null]) assert.equal(createCustomTdpDraft(ready,value),null);
  for(const value of [7,17,30]) {
    const draft=createCustomTdpDraft(ready,value); assert.ok(Object.isFrozen(draft));
    assert.equal(validCustomTdpDraft(draft,ready,value),true);
    assert.equal(validCustomTdpDraft(draft,{...ready},value),false);
    assert.equal(validCustomTdpDraft(draft,ready,value+1),false);
    retireCustomTdpDraft(draft); assert.equal(validCustomTdpDraft(draft,ready,value),false);
  }
  assert.equal(validCustomTdpDraft({kind:"custom",status:ready,watts:17},ready,17),false);
});
