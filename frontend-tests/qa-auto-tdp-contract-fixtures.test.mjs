/**
 * Reusable Auto TDP status fixtures and contract assertions for the future
 * Auto TDP page (task qa-auto-tdp-page, still blocked on qa-module-foundation).
 *
 * This slice deliberately tests the EXISTING adapters in src/auto-tdp-ui.ts. It
 * adds no renderer, no shell wiring and no src change, so it cannot collide with
 * the foundation or page owner. Assertions that genuinely need the page are
 * listed in UNCOVERED_BY_THIS_SLICE rather than faked with skipped tests.
 *
 * Design source: codex/qa-design-review at
 * 7cbf19ec17743b3a70c611960c1e5a469ffc6063 (LAYOUT_APPROVAL, REVISION_02).
 * Per REVISION_02 the Auto TDP tile offers Stop while running, Configure
 * otherwise, so anything that hides Stop from a running session is a defect.
 *
 * Backend note: auto_tdp_status() reports the readiness code as `code` and the
 * session's last tick result as `activity_code`. The codes added or broadened by
 * PR 132 (auto_tdp.readback_invalid, auto_tdp.clock_invalid) therefore arrive as
 * activity codes, and neither adapter maps them. That is intended for now: they
 * must land on the existing neutral fallbacks rather than invent player wording.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { autoTdpActivity, autoTdpMessage, AutoTdpRequestGate, sanitizeAutoTdpStatus, validAutoTdpRange } from "../src/auto-tdp-ui.ts";

export const READY = Object.freeze({
  schema_version: 1, can_start: true, enabled: false, running: false, stopping: false,
  code: "auto_tdp.ready", activity_code: null,
  target_fps: null, minimum_watts: null, maximum_watts: null,
});

export const RUNNING = Object.freeze({
  ...READY, can_start: false, enabled: true, running: true,
  target_fps: 60, minimum_watts: 7, maximum_watts: 30,
  activity_code: "auto_tdp.context_settling",
});

export const STOPPING = Object.freeze({ ...RUNNING, enabled: false, stopping: true });

/** PR 132: recoverable refusal. The session stays enabled; Stop must remain reachable. */
export const RUNNING_READBACK_INVALID = Object.freeze({ ...RUNNING, activity_code: "auto_tdp.readback_invalid" });

/** PR 132: terminal in the backend, so the worker has ended and nothing is running. */
export const CLOCK_INVALID_TERMINAL = Object.freeze({
  ...RUNNING, enabled: false, running: false, stopping: false,
  activity_code: "auto_tdp.clock_invalid",
});

export const MANUAL = Object.freeze({ ready: true, recovery_required: false, minimum_watts: 7, maximum_watts: 30, current_watts: 15 });

/** Assertions that require the page/adapter implementation, recorded for its owner. */
export const UNCOVERED_BY_THIS_SLICE = Object.freeze([
  "A terminal auto_tdp.clock_invalid produces no activity text at all, because autoTdpActivity returns null once enabled is false and only worker_unavailable/session_unavailable bypass that. The page decides whether a terminal clock fault deserves player wording; the backend treats it as fail-closed shutdown.",
  "auto_tdp.readback_invalid has no dedicated wording. It can mean a provider bounds mismatch, including a policy whose maximum exceeds a boost ceiling. Any player-facing phrasing needs backend semantic review before it is written.",
  "Stop versus Restore is only asserted here through autoTdpMessage's stopped wording. The page owns the actual control affordances and their focus order.",
  "Tile-level Stop/Configure behaviour from REVISION_02 needs the module shell and is not representable against these adapters.",
]);

test("fixtures are accepted by the strict sanitizer", () => {
  for (const fixture of [READY, RUNNING, STOPPING, RUNNING_READBACK_INVALID, CLOCK_INVALID_TERMINAL]) {
    assert.notEqual(sanitizeAutoTdpStatus({ ...fixture }), null);
  }
});

test("unmapped backend codes reach the neutral fallbacks without inventing a state", () => {
  // Running session, unmapped activity: neutral, and never an invented pause.
  const activity = autoTdpActivity({ ...RUNNING_READBACK_INVALID });
  assert.equal(activity, "Status updates when you refresh.");
  assert.doesNotMatch(activity, /Paused|Holding power|stopped|unavailable/i);

  // The readiness message must not turn a running session off or unavailable.
  const message = autoTdpMessage({ ...RUNNING_READBACK_INVALID }, "manual");
  assert.equal(message, "Auto TDP is running.");
  assert.doesNotMatch(message, /unavailable|stopped|off\b/i);

  // Defensive: an unmapped code arriving in the readiness slot stays neutral.
  const unmapped = autoTdpMessage({ ...RUNNING, code: "auto_tdp.readback_invalid" }, "manual");
  assert.equal(unmapped, "Auto TDP needs a fresh readiness check.");
  assert.doesNotMatch(unmapped, /unavailable|stopped/i);
});

test("authoritative flags survive an unmapped code, so Stop stays reachable", () => {
  const status = sanitizeAutoTdpStatus({ ...RUNNING_READBACK_INVALID });
  assert.notEqual(status, null);
  // REVISION_02: the tile offers Stop while running.
  assert.equal(status.enabled, true);
  assert.equal(status.running, true);
  assert.equal(status.stopping, false);
  assert.equal(status.can_start, false);
});

test("a terminal clock fault reports no activity text, and is recorded as uncovered", () => {
  // Documents current behaviour rather than asserting a wording that does not exist.
  assert.equal(autoTdpActivity({ ...CLOCK_INVALID_TERMINAL }), null);
  assert.equal(sanitizeAutoTdpStatus({ ...CLOCK_INVALID_TERMINAL }).enabled, false);
  assert.ok(UNCOVERED_BY_THIS_SLICE.some((item) => item.includes("clock_invalid")));
});

test("Stop retains the current limit and never claims a restore", () => {
  const stopped = autoTdpMessage({ ...READY, can_start: false, code: "auto_tdp.stopped" }, "manual");
  assert.match(stopped, /current power limit is retained/i);
  assert.doesNotMatch(stopped, /restor/i);
});

test("a valid range is validation only and never activates a session", () => {
  assert.equal(validAutoTdpRange(MANUAL, 7, 30, 60), true);
  // Saving a valid range must not imply the session may start or is running.
  const saved = sanitizeAutoTdpStatus({ ...READY, can_start: false, code: "auto_tdp.configuration_missing" });
  assert.equal(saved.can_start, false);
  assert.equal(saved.enabled, false);
  assert.equal(validAutoTdpRange({ ...MANUAL, recovery_required: true }, 7, 30, 60), false);
});

test("configured watts are integers, so measured telemetry cannot pose as a limit", () => {
  for (const change of [{ maximum_watts: 30.5 }, { minimum_watts: 7.2 }, { maximum_watts: 0 }]) {
    assert.equal(sanitizeAutoTdpStatus({ ...RUNNING, ...change }), null);
  }
  assert.equal(sanitizeAutoTdpStatus({ ...RUNNING, target_fps: 59.94 }).target_fps, 59.94);
});

test("malformed or missing payload stays unavailable", () => {
  for (const value of [null, undefined, {}, { ...RUNNING, schema_version: 2 }, { ...RUNNING, activity_code: "private.path" }]) {
    assert.equal(sanitizeAutoTdpStatus(value), null);
  }
  assert.match(autoTdpMessage(null, "manual"), /unavailable/i);
});

test("one in-flight Stop is not displaced by a concurrent refresh", () => {
  const gate = new AutoTdpRequestGate();
  const stop = gate.begin(true);
  assert.equal(gate.begin(), null);
  assert.equal(gate.current(stop), true);
  gate.finish(stop);
  assert.equal(gate.busy, false);
});
