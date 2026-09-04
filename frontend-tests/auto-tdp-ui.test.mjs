import assert from "node:assert/strict";
import test from "node:test";
import { autoTdpActivity, autoTdpMessage, AutoTdpRequestGate, sanitizeAutoTdpStatus, validAutoTdpRange } from "../src/auto-tdp-ui.ts";

const ready = { schema_version: 1, can_start: true, enabled: false, running: false, stopping: false, code: "auto_tdp.ready", activity_code: null, target_fps: null, minimum_watts: null, maximum_watts: null };
const running = { ...ready, can_start: false, enabled: true, running: true, target_fps: 60, minimum_watts: 7, maximum_watts: 30, activity_code: "auto_tdp.context_settling" };
const manual = { ready: true, recovery_required: false, minimum_watts: 7, maximum_watts: 30, current_watts: 15 };

test("strict Auto schema preserves stop/drain separately from enablement", () => {
  assert.notEqual(sanitizeAutoTdpStatus(ready), null);
  assert.notEqual(sanitizeAutoTdpStatus(running), null);
  assert.notEqual(sanitizeAutoTdpStatus({ ...running, enabled: false, stopping: true }), null);
  for (const change of [{ schema_version: 2 }, { can_start: 1 }, { enabled: true }, { running: true }, { stopping: true }, { activity_code: undefined }, { target_fps: 60 }, { code: "private.path" }]) {
    assert.equal(sanitizeAutoTdpStatus({ ...ready, ...change }), null);
  }
  assert.equal(sanitizeAutoTdpStatus({ ...running, stopping: true }), null);
  assert.equal(sanitizeAutoTdpStatus({ ...running, maximum_watts: Infinity }), null);
  assert.equal(sanitizeAutoTdpStatus({ ...running, target_fps: NaN }), null);
});

test("ranges require current readback, inclusive bounds, and manual readiness", () => {
  assert.equal(validAutoTdpRange(manual, 7, 30, 60), true);
  assert.equal(validAutoTdpRange(manual, 15, 15, 60), true);
  for (const [minimum, maximum, fps] of [[16, 30, 60], [7, 14, 60], [6, 30, 60], [7, 31, 60], [7, 30, NaN], [7, 30, true], [null, 30, 60]]) {
    assert.equal(validAutoTdpRange(manual, minimum, maximum, fps), false);
  }
  assert.equal(validAutoTdpRange({ ...manual, recovery_required: true }, 7, 30, 60), false);
  assert.equal(validAutoTdpRange({ ...manual, ready: false }, 7, 30, 60), false);
  assert.equal(validAutoTdpRange(null, 7, 30, 60), false);
});

test("availability explanations distinguish configuration, measurement and manual ownership", () => {
  const message = (code) => autoTdpMessage({ ...ready, can_start: false, code }, "Power control is off.");
  assert.match(message("auto_tdp.configuration_missing"), /device configuration/);
  assert.match(message("auto_tdp.configuration_context_changed"), /changed/);
  assert.match(message("telemetry.collection_cost_unbenchmarked"), /benchmark/);
  assert.match(message("telemetry.auto_tdp_cost_exceeds_budget"), /exceeds/);
  assert.equal(message("tdp.disabled"), "Power control is off.");
  assert.match(autoTdpMessage(null, ""), /Refresh or stop/);
  assert.match(autoTdpMessage({ ...running, stopping: true, enabled: false }, ""), /Stopping/);
});

test("unknown categorical codes are not displayed as raw backend text", () => {
  const status = sanitizeAutoTdpStatus({ ...ready, can_start: false, code: "auto_tdp.new_condition" });
  assert.notEqual(status, null);
  assert.doesNotMatch(autoTdpMessage(status, ""), /new_condition/);
  for (const code of ["__proto__", "auto_tdp./private/path", "tdp.secret\nvalue"]) {
    assert.equal(sanitizeAutoTdpStatus({ ...ready, can_start: false, code }), null);
  }
});

test("running activity is bounded and never claims live refresh", () => {
  assert.match(autoTdpActivity(running), /current power limit/);
  assert.equal(autoTdpActivity(ready), null);
  assert.match(autoTdpActivity({ ...running, activity_code: "auto_tdp.unknown" }), /refresh/);
  assert.match(autoTdpActivity({ ...running, running: false, enabled: false, activity_code: "auto_tdp.session_unavailable" }), /stopped/);
  assert.match(autoTdpMessage({ ...running, code: "auto_tdp.configuration_missing" }, ""), /still on/);
  assert.match(autoTdpMessage({ ...running, code: "auto_tdp.game_or_render_unverified" }, ""), /waiting/);
});

test("Stop supersedes pending read or start without accepting their late responses", () => {
  const gate = new AutoTdpRequestGate();
  const start = gate.begin();
  assert.equal(gate.busy, true);
  assert.equal(gate.begin(), null);
  const stop = gate.begin(true);
  assert.equal(gate.current(start), false);
  assert.equal(gate.current(stop), true);
  gate.finish(start);
  assert.equal(gate.begin(), null);
  gate.finish(stop);
  assert.equal(gate.busy, false);
  assert.notEqual(gate.begin(), null);
});

test("unmount invalidates pending UI updates", () => {
  const gate = new AutoTdpRequestGate();
  const old = gate.begin();
  gate.invalidate();
  const current = gate.begin();
  assert.equal(gate.current(old), false);
  assert.equal(gate.current(current), true);
});
