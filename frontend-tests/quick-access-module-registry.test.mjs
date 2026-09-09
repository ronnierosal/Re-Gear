import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const load = async (name) => {
  const source = readFileSync(new URL(`../src/${name}.ts`, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } });
  return outputText;
};
// Concatenated rather than imported: module-registry imports the taxonomy by
// relative path, which cannot resolve inside a data: URL. Exports are kept.
const bundle = (await load("quick-access-sections"))
  + (await load("quick-access/module-registry")).replace(/^import[^;]*;$/gm, "");
const m = await import(`data:text/javascript;base64,${Buffer.from(bundle).toString("base64")}`);
const { quickAccessSections, quickAccessModules, moduleEntry, routeKey, pushRoute, backRoute,
  currentRoute, focusKeyAfterBack, stepGrid, INITIAL_STACK, MODULE_ORDER } = m;

const ready = { fresh: true, mode: "portable", shortcutAvailable: true,
  autoTdpAvailable: true, tdpCanEnable: true, healthKnown: true };

// ---------------------------------------------------------------- registry

test("modules are the three planned destinations, in a stable order", () => {
  assert.deepEqual(quickAccessModules(quickAccessSections(ready)).map((e) => e.id), MODULE_ORDER);
});

test("availability comes from the taxonomy, never recomputed", () => {
  // A module and its section must not be able to disagree about a feature.
  const sections = quickAccessSections({ ...ready, autoTdpAvailable: false });
  const tdp = moduleEntry(quickAccessModules(sections), "auto-tdp");
  assert.equal(tdp.available, false);
  assert.equal(tdp.reason, sections.find((s) => s.id === "tdp").reason);
});

test("an unavailable module stays listed and explains itself", () => {
  const modules = quickAccessModules(quickAccessSections({ ...ready, shortcutAvailable: false }));
  const controller = moduleEntry(modules, "controller");
  assert.equal(modules.length, MODULE_ORDER.length, "never dropped from the list");
  assert.equal(controller.available, false);
  assert.match(controller.reason, /No verified controller input source/);
});

test("a missing section reads unavailable rather than dropping the module", () => {
  // Unknown state is not a capability claim.
  const modules = quickAccessModules([]);
  assert.equal(modules.length, MODULE_ORDER.length);
  for (const entry of modules) {
    assert.equal(entry.available, false, entry.id);
    assert.ok(entry.reason, entry.id);
  }
});

test("an available module carries no reason", () => {
  for (const entry of quickAccessModules(quickAccessSections(ready))) {
    if (entry.available) assert.equal(entry.reason, null, entry.id);
  }
});

// -------------------------------------------------------------- navigation

test("a fresh panel opens on Command Center", () => {
  assert.deepEqual(currentRoute(INITIAL_STACK), { kind: "command-center" });
});

test("status and module routes are distinct destinations", () => {
  // The approved design keeps "eGPU status" read-only and separate from the
  // eGPU module; one key for both would route a look into a set of controls.
  assert.notEqual(routeKey({ kind: "status", id: "egpu" }), routeKey({ kind: "module", id: "egpu" }));
});

test("Back returns one level and then delegates to Steam", () => {
  const modules = pushRoute(INITIAL_STACK, { kind: "modules" });
  const module = pushRoute(modules, { kind: "module", id: "egpu" });
  const first = backRoute(module);
  assert.equal(first.delegate, false);
  assert.deepEqual(currentRoute(first.stack), { kind: "modules" });
  const second = backRoute(first.stack);
  assert.equal(second.delegate, false);
  assert.deepEqual(currentRoute(second.stack), { kind: "command-center" });
  // Nothing internal left: swallowing this press would trap the player.
  assert.equal(backRoute(second.stack).delegate, true);
});

test("Command Center is never popped off the stack", () => {
  assert.deepEqual(backRoute(INITIAL_STACK).stack, INITIAL_STACK);
});

test("re-opening the current destination does not stack a duplicate", () => {
  // Otherwise a repeated press needs two Backs to leave one screen.
  const once = pushRoute(INITIAL_STACK, { kind: "modules" });
  assert.equal(pushRoute(once, { kind: "modules" }), once);
});

test("depth is capped at the approved two levels", () => {
  let stack = pushRoute(INITIAL_STACK, { kind: "modules" });
  stack = pushRoute(stack, { kind: "module", id: "egpu" });
  stack = pushRoute(stack, { kind: "module", id: "controller" });
  assert.equal(stack.length, 2);
  assert.deepEqual(currentRoute(stack), { kind: "module", id: "controller" });
  assert.equal(backRoute(stack).delegate, false, "still returns to Command Center, not out");
});

test("returning restores focus to the route being returned to", () => {
  const stack = pushRoute(pushRoute(INITIAL_STACK, { kind: "modules" }), { kind: "module", id: "egpu" });
  assert.equal(focusKeyAfterBack(backRoute(stack).stack), "modules");
});

test("an unavailable module is still a reachable destination", () => {
  // The defect this stack already shipped once: bouncing off an unavailable
  // target moves the player with no explanation.
  const stack = pushRoute(INITIAL_STACK, { kind: "module", id: "auto-tdp" });
  assert.deepEqual(currentRoute(stack), { kind: "module", id: "auto-tdp" });
});

// ----------------------------------------------------------------- 2D grid

test("left and right move within a row and clamp at its edges", () => {
  assert.equal(stepGrid(0, 5, 2, "right"), 1);
  assert.equal(stepGrid(1, 5, 2, "right"), 1, "clamped, not wrapped");
  assert.equal(stepGrid(1, 5, 2, "left"), 0);
  assert.equal(stepGrid(0, 5, 2, "left"), 0, "clamped, not wrapped");
});

test("up and down move a whole row and clamp at the grid edges", () => {
  assert.equal(stepGrid(0, 5, 2, "down"), 2);
  assert.equal(stepGrid(2, 5, 2, "up"), 0);
  assert.equal(stepGrid(0, 5, 2, "up"), 0);
});

test("down from a full row reaches the incomplete last row", () => {
  // Five tiles in two columns: the fifth must be reachable from either cell
  // above it, or Safe Disconnect becomes unfocusable from the right column.
  assert.equal(stepGrid(2, 5, 2, "down"), 4);
  assert.equal(stepGrid(3, 5, 2, "down"), 4);
  assert.equal(stepGrid(4, 5, 2, "down"), 4, "no empty cell below");
});

test("traversal never leaves the grid, from any cell in any direction", () => {
  for (let count = 1; count <= 8; count++) {
    for (let index = 0; index < count; index++) {
      for (const direction of ["up", "down", "left", "right"]) {
        const next = stepGrid(index, count, 2, direction);
        assert.ok(Number.isInteger(next) && next >= 0 && next < count,
          `count=${count} index=${index} ${direction} -> ${next}`);
      }
    }
  }
});

test("a degenerate grid cannot produce an invalid index", () => {
  assert.equal(stepGrid(3, 0, 2, "down"), 0);
  assert.equal(stepGrid(0, 5, 0, "right"), 0);
  assert.equal(stepGrid(-4, 5, 2, "up"), 0);
  assert.equal(stepGrid(99, 5, 2, "up"), 2, "clamps to the last tile, then moves a row");
});

// ------------------------------------------- wiring decisions the panel makes

test("Back has an internal level only once something is pushed", () => {
  assert.equal(m.hasInternalLevel(INITIAL_STACK), false, "at root Steam must get the press");
  assert.equal(m.hasInternalLevel(pushRoute(INITIAL_STACK, { kind: "modules" })), true);
});

test("the cancel decision does not depend on a state updater running", () => {
  // The defect this replaces: a handler that computed its answer inside a React
  // updater and returned it immediately, while the caller discarded it. This
  // form is a pure function of the stack the render already holds.
  const stack = pushRoute(INITIAL_STACK, { kind: "modules" });
  assert.equal(m.hasInternalLevel(stack), m.hasInternalLevel(stack));
  assert.equal(m.hasInternalLevel(backRoute(stack).stack), false);
});

test("diagnostics count as visible only on Command Center", () => {
  assert.equal(m.diagnosticsVisible(INITIAL_STACK, true), true);
  assert.equal(m.diagnosticsVisible(INITIAL_STACK, false), false);
});

test("navigating away stops diagnostics being treated as on screen", () => {
  // Otherwise collection continues for surfaces nobody can see.
  const pushed = pushRoute(INITIAL_STACK, { kind: "module", id: "egpu" });
  assert.equal(m.diagnosticsVisible(pushed, true), false);
  // Returning restores it without the player re-opening anything.
  assert.equal(m.diagnosticsVisible(backRoute(pushed).stack, true), true);
});

test("a fresh panel opening resets to Command Center", () => {
  // Steam may keep the plugin mounted, so the stack survives a close.
  assert.deepEqual(m.stackOnPanelOpen(), INITIAL_STACK);
  assert.deepEqual(currentRoute(m.stackOnPanelOpen()), { kind: "command-center" });
});

test("Troubleshooting refreshes on the closed to open edge only", () => {
  const opening = m.troubleshootingToggle(false);
  assert.equal(opening.next, true);
  assert.equal(opening.refresh, true);
  const closing = m.troubleshootingToggle(true);
  assert.equal(closing.next, false);
  assert.equal(closing.refresh, false, "closing must not request evidence");
});

test("re-opening an already open Troubleshooting does not request again", () => {
  // Toggling twice returns to closed, having requested exactly once.
  const first = m.troubleshootingToggle(false);
  const second = m.troubleshootingToggle(first.next);
  assert.equal(second.refresh, false);
  assert.equal(second.next, false);
});
