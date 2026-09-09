import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const load = (name) => {
  const source = readFileSync(new URL(`../src/${name}.ts`, import.meta.url), "utf8");
  return ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText;
};
// health-presentation imports health-ui by relative path, which cannot resolve
// in a data: URL, so the two are concatenated with the import line removed.
const bundle = load("health-ui") + load("quick-access/health-presentation").replace(/^import[^;]*;$/gm, "");
const { healthPresentation, healthNeedsSurface } =
  await import(`data:text/javascript;base64,${Buffer.from(bundle).toString("base64")}`);

const health = (state, blockers = []) => ({ state, blockers });

test("a healthy system is quiet: label only, nothing to surface", () => {
  const p = healthPresentation(health("ready"));
  assert.equal(p.label, "Ready");
  assert.equal(p.tone, "quiet");
  assert.equal(p.quiet, true);
  assert.deepEqual(p.reasons, []);
  assert.equal(healthNeedsSurface(p), false);
});

test("a healthy payload carrying blockers still lists nothing", () => {
  // healthAttentionMessages already refuses to explain a ready system; the
  // presentation must not reintroduce the noise.
  const p = healthPresentation(health("ready", ["health.display_degraded"]));
  assert.deepEqual(p.reasons, []);
  assert.equal(p.quiet, true);
});

test("unknown is its own state and is never healthy", () => {
  for (const value of [undefined, health(undefined), health("something_new_from_a_later_build")]) {
    const p = healthPresentation(value);
    assert.equal(p.tone, "unknown", String(value && value.state));
    assert.equal(p.quiet, false, "absent evidence is worth saying");
    assert.equal(p.label, "Unavailable");
  }
});

test("the four known states stay distinct from each other", () => {
  const tones = ["ready", "recovering", "degraded", "attention_required"]
    .map((state) => healthPresentation(health(state)).tone);
  assert.deepEqual(tones, ["quiet", "progress", "attention", "attention"]);
  const labels = ["ready", "recovering", "degraded", "attention_required"]
    .map((state) => healthPresentation(health(state)).label);
  assert.equal(new Set(labels).size, 4, "each state reads differently");
});

test("placement and workflow reasons are separated from health reasons", () => {
  // Presenting a docking question next to a hardware fault makes the first look
  // like the second.
  const p = healthPresentation(health("degraded", [
    "health.placement_degraded", "health.workflow_unknown", "health.display_degraded",
  ]));
  assert.equal(p.placementReasons.length, 1);
  assert.match(p.placementReasons[0], /mode needs attention/i);
  assert.equal(p.workflowReasons.length, 1);
  assert.match(p.workflowReasons[0], /recovery status/i);
  assert.equal(p.reasons.length, 1);
  assert.match(p.reasons[0], /display is not usable/i);
});

test("reasons are the sanitized mapping, never a raw backend code", () => {
  const p = healthPresentation(health("degraded", ["health.some_unmapped_future_code"]));
  for (const reason of p.reasons) {
    assert.doesNotMatch(reason, /health\./, "no raw code reaches a player");
  }
  assert.equal(p.reasons.length, 1);
});

test("loading says so and asserts nothing about health", () => {
  const p = healthPresentation(health("degraded", ["health.display_degraded"]), true);
  assert.equal(p.label, "Checking…");
  assert.equal(p.tone, "unknown");
  assert.deepEqual(p.reasons, [], "a reason shown while loading is evidence we do not have");
  assert.deepEqual(p.placementReasons, []);
});

test("the text equivalent needs no colour to be understood", () => {
  for (const state of ["ready", "recovering", "degraded", "attention_required", undefined]) {
    const p = healthPresentation(health(state));
    assert.equal(p.textEquivalent, p.label);
    assert.ok(p.textEquivalent.length > 0);
  }
});

test("the model names no colours, so it can be re-themed", () => {
  const p = healthPresentation(health("degraded", ["health.display_degraded"]));
  assert.doesNotMatch(JSON.stringify(p), /#[0-9a-f]{3,6}|amber|red|green/i);
});
