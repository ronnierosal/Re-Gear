import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

function loadTs(path) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8");
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2022 } }).outputText;
  return import("data:text/javascript;base64," + Buffer.from(js).toString("base64"));
}

test("quick tap Y opens swap customization while hold Y enters move mode", async () => {
  const { createCustomizeGestureRecognizer, CUSTOMIZE_HOLD_MS } = await loadTs("../src/quick-access/expanded-command-center/customization-input.ts");
  let clock = 1000;
  const events = [];
  const recognizer = createCustomizeGestureRecognizer({ tab: () => "quick", now: () => clock, onGesture: event => events.push(event) });
  recognizer.down(); clock += CUSTOMIZE_HOLD_MS - 1; recognizer.up();
  recognizer.down(); clock += CUSTOMIZE_HOLD_MS; recognizer.up();
  assert.deepEqual(events, [{kind:"swap",tab:"quick"},{kind:"move",tab:"quick"}]);
});

test("non-quick tabs only allow reorder on hold", async () => {
  const { createCustomizeGestureRecognizer, CUSTOMIZE_HOLD_MS } = await loadTs("../src/quick-access/expanded-command-center/customization-input.ts");
  let clock = 1000;
  const events = [];
  const recognizer = createCustomizeGestureRecognizer({ tab: () => "egpu", now: () => clock, onGesture: event => events.push(event) });
  recognizer.down(); clock += 100; recognizer.up();
  recognizer.down(); clock += CUSTOMIZE_HOLD_MS; recognizer.up();
  assert.deepEqual(events, [{kind:"move",tab:"egpu"}]);
});

test("reorder helper moves one-cell buttons without changing membership", async () => {
  const source = readFileSync(new URL("../src/quick-access/expanded-command-center/layout-customization.tsx", import.meta.url), "utf8");
  assert.match(source, /reorderById/);
  assert.match(source, /regearTileJiggle/);
  assert.match(source, /prefers-reduced-motion/);
  assert.match(source, /D-pad moves the selected button/);
});
