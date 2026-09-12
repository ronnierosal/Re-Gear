import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/quick-access/modules/egpu-presentation.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } });
const { displayTargetEvidence } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

const display = (over = {}) => ({
  kind: "external", connected: true, active: true, edid_ready: true, confidence: "verified", ...over,
});

test("a verified reading of a driven panel is the only one that reads as fact", () => {
  const graded = displayTargetEvidence([display()]);
  assert.equal(graded.text, "External");
  assert.equal(graded.known, true);
  assert.equal(graded.verified, true);
});

test("an observed reading is known but not verified, so it cannot render as active", () => {
  // The eGPU tab already says "observed, not verified" for this same field.
  // Publishing it ungraded is how one observation gets stated two ways.
  for (const confidence of ["observed", "unknown"]) {
    const graded = displayTargetEvidence([display({ confidence })]);
    assert.equal(graded.text, "External", `${confidence} still names the panel`);
    assert.equal(graded.known, true);
    assert.equal(graded.verified, false, `${confidence} must not claim verification`);
  }
});

test("attachment is not a target: connected but inactive is no observation at all", () => {
  const graded = displayTargetEvidence([display({ active: false }), display({ kind: "internal", active: false })]);
  assert.equal(graded.known, false);
  assert.equal(graded.text, "Unknown");
  assert.equal(graded.verified, false);
});

test("a null active reading is absence of evidence, never a negative reading", () => {
  const graded = displayTargetEvidence([display({ active: null })]);
  assert.equal(graded.known, false);
});

test("mirrored output names both panels rather than picking one", () => {
  // Reporting only "External" here hides the fact that the handheld is also
  // being driven, at the moment a player is deciding whether the TV is live.
  const graded = displayTargetEvidence([display(), display({ kind: "internal" })]);
  assert.equal(graded.text, "External + handheld");
  assert.equal(graded.known, true);
  assert.equal(graded.verified, true);
});

test("an answer is only as verified as its least verified input", () => {
  const graded = displayTargetEvidence([
    display({ confidence: "verified" }),
    display({ kind: "internal", confidence: "observed" }),
  ]);
  assert.equal(graded.text, "External + handheld");
  assert.equal(graded.verified, false);
});

test("the handheld alone is reported as the handheld, not as an absence", () => {
  const graded = displayTargetEvidence([display({ kind: "internal" }), display({ active: false })]);
  assert.equal(graded.text, "Handheld");
  assert.equal(graded.verified, true);
});

test("a panel of unknown kind cannot stand in for either answer", () => {
  const graded = displayTargetEvidence([display({ kind: "unknown" })]);
  assert.equal(graded.known, false, "an unidentified driven panel names neither target");
});

test("absent, empty and malformed input all fail closed", () => {
  for (const value of [undefined, null, []]) {
    const graded = displayTargetEvidence(value);
    assert.equal(graded.known, false);
    assert.equal(graded.text, "Unknown");
  }
});
