import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

// The probe is the one thing that can read where a Safe Disconnect stopped,
// and it runs against a live handheld. These pins keep it a read: a probe that
// consumed a record or dispatched an operation while "just looking" would be
// the worst kind of diagnostic.
const source = readFileSync(new URL("../scripts/probe_whole_dock_trial_status.mjs", import.meta.url), "utf8");

test("the probe calls only read-only backend methods", () => {
  const called = [...source.matchAll(/\["([a-z_]+)"(?:, "([a-z_]+)")?\]/g)].map((m) => m[1]);
  const inlineCalls = [...source.matchAll(/api\.call\("([a-z_]+)"/g)].map((m) => m[1]);
  const all = new Set([...called, ...inlineCalls]);
  assert.deepEqual([...all].sort(), ["get_egpu_disconnect_status", "get_sleep_readiness", "get_snapshot"]);
  // The consuming and mutating RPCs on the same plugin must never appear, not
  // even in a comment that a later edit could uncomment.
  for (const forbidden of [
    "execute_egpu_disconnect", "take_pending_sleep", "take_pending_relaunch",
    "remember_game_close_choice", "forget_game_close_choice", "execute_",
    "approve_", "acknowledge_", "setItem", "removeItem",
  ]) {
    assert.ok(!source.includes(forbidden), `probe must not reference ${forbidden}`);
  }
});

test("the probe reads only status views of the disconnect RPC", () => {
  const views = [...source.matchAll(/\["get_egpu_disconnect_status", "([a-z_]+)"\]/g)].map((m) => m[1]);
  assert.deepEqual(views.sort(), ["power_status", "whole_dock_record", "whole_dock_trial"]);
});

test("the probe targets SharedJSContext and uses its own tunnel port", () => {
  assert.match(source, /item\.title === "SharedJSContext"/);
  // 19223 is another agent's session; the default must not collide with it.
  assert.match(source, /"http:\/\/127\.0\.0\.1:19224"/);
  assert.doesNotMatch(source, /19223"/);
});

test("the probe reaches the backend through the loader's plugin api, not the legacy transport", () => {
  assert.match(source, /deckyLoaderAPIInit/);
  assert.match(source, /init\.connect\(2, "Re-Gear"\)/);
  assert.doesNotMatch(source, /callServerMethod|DeckyBackend\./);
});
