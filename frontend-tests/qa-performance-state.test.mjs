import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/quick-access/performance-state.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } });
const { performanceState, acceptResponse, wattsValue, fpsTile } =
  await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

const status = (over = {}) => ({
  schema_version: 1, enabled: false, can_enable: true, ready: true, code: "tdp.ready",
  current_watts: 15, minimum_watts: 5, maximum_watts: 30, restore_available: false,
  recovery_required: false, auto_tdp_available: true, last_result: null, ...over,
});

test("no status yet reads as not observed, not as unsupported", () => {
  const s = performanceState({ status: null });
  assert.equal(s.action, "none");
  assert.equal(s.supported, false);
  assert.match(s.reason, /not yet observed/i);
});

test("an unsupported device says so and offers nothing", () => {
  const s = performanceState({ status: status({ auto_tdp_available: false }) });
  assert.equal(s.action, "none");
  assert.match(s.reason, /no verified TDP control/i);
});

test("Stop is offered while running", () => {
  const s = performanceState({ status: status({ enabled: true }) });
  assert.equal(s.active, true);
  assert.equal(s.action, "stop");
  assert.equal(s.reason, null);
});

test("Stop stays reachable even when starting is no longer permitted", () => {
  // A player must always be able to stop something changing their device.
  const s = performanceState({ status: status({ enabled: true, can_enable: false }) });
  assert.equal(s.action, "stop");
});

test("Start needs both permission and an explicitly configured range", () => {
  assert.equal(performanceState({ status: status(), configured: true }).action, "start");
  // Permission without configuration must not start from guessed defaults.
  const unconfigured = performanceState({ status: status(), configured: false });
  assert.equal(unconfigured.action, "open");
  assert.match(unconfigured.reason, /Set a power range/i);
  // Configuration without permission is still not startable.
  const unpermitted = performanceState({ status: status({ can_enable: false }), configured: true });
  assert.equal(unpermitted.action, "open");
  assert.match(unpermitted.reason, /not available/i);
});

test("recovery outranks starting", () => {
  // Starting over an unrestored limit leaves whatever the interrupted session left.
  const s = performanceState({ status: status({ recovery_required: true }), configured: true });
  assert.equal(s.action, "open");
  assert.match(s.reason, /recovery/i);
});

test("a busy tile issues nothing further, running or not", () => {
  for (const enabled of [true, false]) {
    const s = performanceState({ status: status({ enabled }), configured: true, busy: true });
    assert.equal(s.action, "none", `enabled=${enabled}`);
    assert.equal(s.busy, true);
  }
});

test("enablement and loop start are never one toggle", () => {
  // can_enable is a capability; enabled is a running loop. No input produces a
  // single boolean action conflating them.
  const actions = new Set();
  for (const enabled of [true, false]) {
    for (const can_enable of [true, false]) {
      for (const configured of [true, false]) {
        actions.add(performanceState({ status: status({ enabled, can_enable }), configured }).action);
      }
    }
  }
  assert.ok(actions.has("stop") && actions.has("start") && actions.has("open"));
  assert.equal(actions.has("toggle"), false);
});

test("unknown watts stay unknown rather than becoming zero", () => {
  assert.deepEqual(wattsValue(null), { text: "Unknown", known: false });
  assert.deepEqual(wattsValue(Number.NaN), { text: "Unknown", known: false });
  assert.deepEqual(wattsValue(14.6), { text: "15 W", known: true });
});

test("a late response never overwrites a newer read", () => {
  assert.equal(acceptResponse(4, 4), true);
  assert.equal(acceptResponse(3, 4), false, "a slow reply must not land on fresh state");
});

test("the FPS tile keeps its position, states why, and invents no number", () => {
  const tile = fpsTile();
  assert.equal(tile.available, false);
  assert.equal(tile.value.known, false);
  assert.match(tile.reason, /no verified frame-rate provider/i);
  assert.doesNotMatch(tile.value.text, /\d/, "no fabricated frame rate");
});
