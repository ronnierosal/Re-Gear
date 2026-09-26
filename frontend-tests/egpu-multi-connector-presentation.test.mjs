import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/quick-access/modules/egpu-presentation.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
});
const { egpuPresentation } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
);

const display = (over = {}) => ({
  kind: "external", connected: false, active: false, edid_ready: false,
  confidence: "verified", ...over,
});
const presentation = (displays) => egpuPresentation({ snapshot: { displays, gpus: [] } });

test("a later connected and active TV wins over earlier disconnected connectors", () => {
  const result = presentation([
    display(),
    display({ confidence: "observed" }),
    display({ connected: true, active: true, edid_ready: true }),
  ]);
  assert.deepEqual(result.displayConnected, { text: "Connected", known: true, verified: true });
  assert.deepEqual(result.displayActive, { text: "Active", known: true, verified: true });
});

test("connected and active aggregate independently", () => {
  const result = presentation([
    display({ connected: true, active: false }),
    display({ connected: false, active: true, confidence: "observed" }),
  ]);
  assert.deepEqual(result.displayConnected, { text: "Connected", known: true, verified: true });
  assert.deepEqual(result.displayActive, { text: "Active", known: true, verified: false });
});

test("incomplete evidence stays Unknown when no connector reports true", () => {
  const result = presentation([
    display(),
    display({ connected: null, active: undefined }),
  ]);
  assert.deepEqual(result.displayConnected, { text: "Unknown", known: false, verified: false });
  assert.deepEqual(result.displayActive, { text: "Unknown", known: false, verified: false });
});

test("all observed false yields false and carries the weakest confidence", () => {
  const observed = presentation([
    display(),
    display({ confidence: "observed" }),
  ]);
  assert.deepEqual(observed.displayConnected, { text: "Not connected", known: true, verified: false });
  assert.deepEqual(observed.displayActive, { text: "Not active", known: true, verified: false });

  const verified = presentation([display(), display()]);
  assert.deepEqual(verified.displayConnected, { text: "Not connected", known: true, verified: true });
  assert.deepEqual(verified.displayActive, { text: "Not active", known: true, verified: true });
});
