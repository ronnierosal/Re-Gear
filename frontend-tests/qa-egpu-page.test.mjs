import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/quick-access/modules/egpu-presentation.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } });
const { egpuPresentation } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

const gpu = (over = {}) => ({ role: "external", present: true, selected_for_render: true, confidence: "verified", ...over });
const display = (over = {}) => ({ kind: "external", connected: true, active: true, edid_ready: true, confidence: "verified", ...over });
const link = (over = {}) => ({ applicable: true, state: "up", confidence: "verified", reason: "", error: "", ...over });
const readiness = (stage) => ({ schema_version: 1, stage, code: "c", poll_after_ms: 0, window_age_ms: 0 });

const base = () => ({
  delivery_schema_version: 1,
  snapshot: {
    schema_version: 1, observed_at: "2026-09-09T00:00:00Z", host_profile: "p", support_tier: "t",
    game_state: "idle", gpus: [gpu()], displays: [display()],
    gamescope: { running: true, confidence: "verified" },
    disconnect_readiness: {}, sleep_guard: {}, egpu_link: link(), blockers: [],
  },
  inference: { mode: "docked_egpu", reasons: [] },
  connection_readiness: readiness("ready_idle"),
});
const withSnapshot = (over) => { const p = base(); p.snapshot = { ...p.snapshot, ...over }; return p; };
const INDEPENDENT = ["connection", "renderGpu", "displayConnected", "displayActive", "session", "game", "lifecycle"];

test("nothing is known when there is no payload at all", () => {
  const p = egpuPresentation(null);
  for (const key of INDEPENDENT) {
    assert.equal(p[key].known, false, key);
    assert.equal(p[key].text, "Unknown", key);
  }
  assert.equal(p.model, null);
});

test("the link says nothing about rendering, display, session or game", () => {
  // AGENTS.md: physical connection, render GPU, display target, Gamescope and
  // game state are independent. Changing only the link must move only the link.
  const up = egpuPresentation(base());
  const down = egpuPresentation(withSnapshot({ egpu_link: link({ state: "down" }) }));
  assert.notEqual(up.connection.text, down.connection.text, "the link itself must change");
  for (const key of ["renderGpu", "displayConnected", "displayActive", "session", "game"]) {
    assert.deepEqual(down[key], up[key], `${key} must not follow the link`);
  }
});

test("rendering says nothing about the link or the display", () => {
  const rendering = egpuPresentation(base());
  const not = egpuPresentation(withSnapshot({ gpus: [gpu({ selected_for_render: false })] }));
  assert.notEqual(rendering.renderGpu.text, not.renderGpu.text);
  for (const key of ["connection", "displayConnected", "displayActive", "session", "game"]) {
    assert.deepEqual(not[key], rendering[key], `${key} must not follow the render GPU`);
  }
});

test("a connected display is not an active one", () => {
  const p = egpuPresentation(withSnapshot({ displays: [display({ connected: true, active: false })] }));
  assert.equal(p.displayConnected.text, "Connected");
  assert.equal(p.displayActive.text, "Not active");
});

test("a running game does not change the hardware readings", () => {
  const idle = egpuPresentation(base());
  const running = egpuPresentation(withSnapshot({ game_state: "running" }));
  assert.notEqual(idle.game.text, running.game.text);
  for (const key of ["connection", "renderGpu", "displayConnected", "displayActive", "session"]) {
    assert.deepEqual(running[key], idle[key], `${key} must not follow game state`);
  }
});

test("unknown evidence fails closed rather than reading as working", () => {
  const p = egpuPresentation(withSnapshot({
    egpu_link: link({ state: "unknown", confidence: "unknown" }),
    gpus: [gpu({ selected_for_render: null })],
    displays: [display({ connected: null, active: null })],
    gamescope: { running: null, confidence: "unknown" },
  }));
  for (const key of ["connection", "renderGpu", "displayConnected", "displayActive", "session"]) {
    assert.equal(p[key].known, false, key);
    assert.equal(p[key].verified, false, key);
  }
});

test("an inapplicable link reads unknown rather than down", () => {
  const p = egpuPresentation(withSnapshot({ egpu_link: link({ applicable: false }) }));
  assert.equal(p.connection.known, false);
});

test("confidence is carried, so observed is not presented as verified", () => {
  const p = egpuPresentation(withSnapshot({ egpu_link: link({ confidence: "observed" }) }));
  assert.equal(p.connection.known, true);
  assert.equal(p.connection.verified, false);
});

test("no input ever produces a safe-disconnect claim", () => {
  // Re-Gear cannot confirm live removal is safe; the refusal is unconditional.
  const idleNoRender = withSnapshot({ game_state: "idle", gpus: [gpu({ selected_for_render: false })] });
  const disconnected = base(); disconnected.connection_readiness = readiness("disconnected");
  for (const input of [null, base(), idleNoRender, disconnected]) {
    const p = egpuPresentation(input);
    assert.equal(p.disconnect.safeClaim, false);
    const rendered = JSON.stringify(p);
    assert.doesNotMatch(rendered, /safe to (unplug|disconnect|remove)/i);
    assert.doesNotMatch(rendered, /you (can|may) (now )?(unplug|disconnect|remove)/i);
    assert.match(p.disconnect.reason, /cannot confirm/i);
  }
});

test("recovery stays reachable when readings are missing", () => {
  for (const input of [null, base()]) {
    assert.equal(egpuPresentation(input).recovery.reachable, true);
  }
  assert.match(egpuPresentation(null).recovery.note, /still available/i);
});

test("a model name is shown only when one external GPU is unambiguous", () => {
  const one = egpuPresentation(withSnapshot({ gpus: [gpu({ model_name: "Vendor Model" })] }));
  assert.equal(one.model, "Vendor Model");
  const two = egpuPresentation(withSnapshot({ gpus: [gpu({ model_name: "A" }), gpu({ model_name: "B" })] }));
  assert.equal(two.model, null, "ambiguous identity is not presented");
  const blank = egpuPresentation(withSnapshot({ gpus: [gpu({ model_name: "  " })] }));
  assert.equal(blank.model, null);
});

test("the model name never changes any reading", () => {
  // The payload documents it as presentation only, never a readiness input.
  const named = egpuPresentation(withSnapshot({ gpus: [gpu({ model_name: "Vendor Model" })] }));
  const plain = egpuPresentation(base());
  for (const key of INDEPENDENT) {
    assert.deepEqual(named[key], plain[key], `${key} must not depend on a name`);
  }
});

test("no unsupported display capability is presented", () => {
  const rendered = JSON.stringify(egpuPresentation(base()));
  assert.doesNotMatch(rendered, /\bHDR\b|\bVRR\b|refresh rate|\d+\s*Hz/i);
});

test("lifecycle stages read distinctly and an unknown stage is not invented", () => {
  const stages = ["disconnected", "waiting_for_link", "ready_idle", "link_training_failed", "timed_out"];
  const seen = stages.map((stage) => {
    const p = base(); p.connection_readiness = readiness(stage);
    return egpuPresentation(p).lifecycle.text;
  });
  assert.equal(new Set(seen).size, stages.length, "each stage reads distinctly");
  const later = base(); later.connection_readiness = readiness("a_stage_from_a_later_build");
  assert.equal(egpuPresentation(later).lifecycle.known, false);
});
