import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const load = async (name) => {
  const source = readFileSync(new URL(`../src/${name}.ts`, import.meta.url), "utf8")
    .replace(/^import .*;\r?\n/gm, "");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
  });
  return outputText;
};

// The nav module imports the taxonomy; concatenate both so the pair runs offline.
const bundle = (await load("quick-access-sections")) + (await load("quick-access-nav"));
const { quickAccessSections, quickAccessNavView, stepSection } =
  await import(`data:text/javascript;base64,${Buffer.from(bundle).toString("base64")}`);

const ready = {
  fresh: true, mode: "portable", shortcutAvailable: true,
  autoTdpAvailable: true, tdpCanEnable: true, healthKnown: true,
};

test("the row carries one target per section, in panel order", () => {
  const view = quickAccessNavView(quickAccessSections(ready));
  assert.deepEqual(view.items.map((item) => item.id),
    ["egpu", "controller", "tdp", "display", "system"]);
  assert.deepEqual(view.items.map((item) => item.icon),
    ["connection", "controller", "gauge", "monitor", "tools"]);
});

test("every target has an accessible name, since the row is icon-only", () => {
  for (const item of quickAccessNavView(quickAccessSections(ready)).items) {
    assert.ok(item.label && item.label.length > 0, item.id);
  }
});

test("the row keeps its shape when evidence is missing", () => {
  // Targets must not move under a player's thumb as a snapshot arrives.
  const full = quickAccessNavView(quickAccessSections(ready)).items.map((item) => item.id);
  const empty = quickAccessNavView(quickAccessSections({})).items.map((item) => item.id);
  assert.deepEqual(empty, full);
});

test("an unavailable section is dimmed but still reachable", () => {
  // Being drawn in the row was never the question. This asserted only presence,
  // so it passed for the whole period when selecting the target was impossible:
  // the resolver bounced off it. Reachability means landing on it.
  const sections = quickAccessSections({ ...ready, shortcutAvailable: false });
  const view = quickAccessNavView(sections);
  const controller = view.items.find((item) => item.id === "controller");
  assert.equal(controller.available, false);
  assert.equal(controller.active, false, "not active until chosen");

  const chosen = quickAccessNavView(sections, "controller");
  assert.equal(chosen.activeId, "controller", "selecting it must land on it");
  assert.equal(chosen.blocked, true);
  assert.equal(chosen.items.find((item) => item.id === "controller").active, true);

  // Stepping must reach it too, or traversal order would depend on evidence.
  const fromEgpu = quickAccessNavView(sections, "egpu");
  assert.equal(stepSection(fromEgpu, 1), "controller");
});

test("selecting a blocked section shows the reason, not the summary", () => {
  // This is reachable from the real taxonomy, not only from a synthetic list:
  // the test previously asserted the opposite of its own name because the
  // resolver bounced off the selection before the row could explain it.
  const sections = quickAccessSections({ ...ready, autoTdpAvailable: false });
  const view = quickAccessNavView(sections, "tdp");
  assert.equal(view.activeId, "tdp");
  assert.equal(view.blocked, true);
  assert.equal(view.detail, "This device has no verified TDP control.");
  assert.equal(view.items.find((item) => item.id === "tdp").active, true);
});

test("a blocked active section reports blocked and explains itself", () => {
  const blocked = [{ id: "tdp", title: "Auto TDP", summary: "s", available: false, reason: "No verified TDP control." }];
  const view = quickAccessNavView(blocked, "tdp");
  assert.equal(view.blocked, true);
  assert.equal(view.detail, "No verified TDP control.");
  assert.equal(view.heading, "Auto TDP");
});

test("an available section shows its summary and is not blocked", () => {
  const view = quickAccessNavView(quickAccessSections(ready), "tdp");
  assert.equal(view.activeId, "tdp");
  assert.equal(view.blocked, false);
  assert.match(view.detail, /Power limit/);
});

test("exactly one target is active", () => {
  const view = quickAccessNavView(quickAccessSections(ready), "display");
  assert.equal(view.items.filter((item) => item.active).length, 1);
  assert.equal(view.items.find((item) => item.active).id, "display");
});

test("stepping wraps, so the row has no dead ends", () => {
  const view = quickAccessNavView(quickAccessSections(ready), "egpu");
  assert.equal(stepSection(view, -1), "system");
  assert.equal(stepSection(view, 1), "controller");
  const last = quickAccessNavView(quickAccessSections(ready), "system");
  assert.equal(stepSection(last, 1), "egpu");
});

test("stepping reaches unavailable sections rather than skipping them", () => {
  // Skipping would make traversal order depend on live evidence.
  const view = quickAccessNavView(quickAccessSections({ ...ready, shortcutAvailable: false }), "egpu");
  assert.equal(stepSection(view, 1), "controller");
});

test("an empty section list does not crash the row", () => {
  const view = quickAccessNavView([], undefined);
  assert.deepEqual(view.items, []);
  assert.equal(view.blocked, true);
  assert.equal(stepSection(view, 1), view.activeId);
});
