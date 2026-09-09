import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/quick-access/modules/controller-presentation.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } });
const { controllerPresentation, PLANNED_CONTROLLER_FEATURES } =
  await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

const peripheral = (controller) => ({
  schema_version: 1,
  controller: { complete: true, exact: true, builtin_available: true, external_connected: false, code: "peripheral.ok", ...controller },
  audio: { complete: true, exact: true, external_available: null, portable_available: null, code: "peripheral.ok" },
});

test("no peripheral reading says status unavailable", () => {
  const p = controllerPresentation({ peripheral: null });
  assert.equal(p.available, false);
  assert.match(p.reason, /unavailable/i);
  assert.equal(p.builtin.known, false);
  assert.equal(p.external.known, false);
});

test("exact and complete facts are reported as facts", () => {
  const p = controllerPresentation({ peripheral: peripheral({}) });
  assert.equal(p.available, true);
  assert.equal(p.precision, "exact");
  assert.equal(p.precisionNote, null);
  assert.deepEqual(p.builtin, { text: "Available", known: true });
  assert.deepEqual(p.external, { text: "Not connected", known: true });
});

test("null fields stay Unknown and are never inferred from the other", () => {
  // An attached external pad says nothing about whether the built-in one works.
  const p = controllerPresentation({ peripheral: peripheral({ builtin_available: null, external_connected: true }) });
  assert.equal(p.builtin.known, false);
  assert.equal(p.builtin.text, "Unknown");
  assert.equal(p.external.text, "Connected");
});

test("an incomplete reading shows what it knows and flags the caveat", () => {
  // Incomplete is not absent: collapsing it to "no controller" loses evidence.
  const p = controllerPresentation({ peripheral: peripheral({ complete: false }) });
  assert.equal(p.precision, "partial");
  assert.match(p.precisionNote, /incomplete/i);
  assert.equal(p.available, true, "partial evidence is still evidence");
  assert.equal(p.builtin.text, "Available");
});

test("a reading with no usable facts is unavailable, not silently empty", () => {
  const p = controllerPresentation({ peripheral: peripheral({ builtin_available: null, external_connected: null }) });
  assert.equal(p.available, false);
  assert.match(p.reason, /no usable facts/i);
});

test("shortcut input is reported separately and is not controller presence", () => {
  // A usable input source does not mean a controller is attached.
  const p = controllerPresentation({ peripheral: null, shortcutAvailable: true });
  assert.deepEqual(p.shortcut, { text: "Available", known: true });
  assert.equal(p.builtin.known, false, "shortcut availability must not imply presence");
  assert.equal(p.available, false);
});

test("shortcut availability is unknown when not observed", () => {
  const p = controllerPresentation({ peripheral: peripheral({}) });
  assert.equal(p.shortcut.known, false);
  assert.equal(p.shortcut.text, "Unknown");
});

test("no device name, Player 1, or handoff state is ever produced", () => {
  const inputs = [
    { peripheral: null },
    { peripheral: peripheral({}), shortcutAvailable: true },
    { peripheral: peripheral({ complete: false, exact: false }) },
  ];
  for (const input of inputs) {
    const rendered = JSON.stringify(controllerPresentation(input));
    assert.doesNotMatch(rendered, /player\s*[12]/i, "no player assignment");
    assert.doesNotMatch(rendered, /xbox|dualsense|raikiri|steam deck|ally/i, "no invented identity");
  }
});

test("planned features are listed as planned, not as working controls", () => {
  const p = controllerPresentation({ peripheral: peripheral({}) });
  assert.deepEqual(p.planned, PLANNED_CONTROLLER_FEATURES);
  assert.ok(p.planned.includes("Player order"));
  // The model exposes no callable action anywhere: a page cannot accidentally
  // render a planned capability as a live toggle.
  for (const value of Object.values(p)) {
    assert.notEqual(typeof value, "function");
  }
});

test("planned features are reported the same whatever the evidence says", () => {
  // Their absence is a fact about the build, not about this device.
  const a = controllerPresentation({ peripheral: null });
  const b = controllerPresentation({ peripheral: peripheral({}), shortcutAvailable: true });
  assert.deepEqual(a.planned, b.planned);
});
