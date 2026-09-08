import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/quick-access-sections.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } });
const { quickAccessSections, defaultSectionId, resolveSectionId } =
  await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

const ready = {
  fresh: true, mode: "portable", shortcutAvailable: true,
  autoTdpAvailable: true, tdpCanEnable: true, healthKnown: true,
};
const by = (sections) => Object.fromEntries(sections.map((section) => [section.id, section]));

test("the taxonomy is the five named sections, in panel order", () => {
  assert.deepEqual(quickAccessSections(ready).map((section) => section.id),
    ["egpu", "controller", "tdp", "display", "system"]);
});

test("every section is present when its feature is ready", () => {
  for (const section of quickAccessSections(ready)) {
    assert.equal(section.available, true, section.id);
    assert.equal(section.reason, null, section.id);
  }
});

test("an unavailable section stays listed and explains itself", () => {
  // A control that disappears reads as a bug; the reason is the whole point.
  const sections = quickAccessSections({ ...ready, shortcutAvailable: false });
  assert.equal(sections.length, 5);
  assert.equal(by(sections).controller.available, false);
  assert.match(by(sections).controller.reason, /No verified controller input source/);
});

test("unknown evidence fails closed rather than claiming a capability", () => {
  // Absent fields mean unknown, never "supported".
  const sections = by(quickAccessSections({}));
  assert.equal(sections.controller.available, false);
  assert.equal(sections.tdp.available, false);
  assert.equal(sections.display.available, false);
  for (const id of ["controller", "tdp", "display"]) {
    assert.ok(sections[id].reason, `${id} must say why`);
  }
});

test("Auto TDP needs a proven writer and current permission, not either alone", () => {
  const noWriter = by(quickAccessSections({ ...ready, autoTdpAvailable: false }));
  assert.equal(noWriter.tdp.available, false);
  assert.match(noWriter.tdp.reason, /no verified TDP control/);

  const notPermitted = by(quickAccessSections({ ...ready, tdpCanEnable: false }));
  assert.equal(notPermitted.tdp.available, false);
  assert.match(notPermitted.tdp.reason, /not available in the current state/);

  const unobserved = by(quickAccessSections({ ...ready, tdpCanEnable: undefined }));
  assert.equal(unobserved.tdp.available, false);
});

test("eGPU and System stay reachable on stale evidence", () => {
  // These own recovery, troubleshooting and support export — reachable exactly
  // when readings are stale is the point.
  const stale = by(quickAccessSections({ fresh: false }));
  assert.equal(stale.egpu.available, true);
  assert.equal(stale.system.available, true);
  assert.equal(stale.display.available, false);
  assert.match(stale.display.reason, /Waiting for a fresh status update/);
});

test("the panel opens on the first usable section", () => {
  assert.equal(defaultSectionId(quickAccessSections(ready)), "egpu");
  assert.equal(defaultSectionId([]), "egpu");
});

test("the default never names a section the caller was not given", () => {
  // A nav row must be able to resolve its selection to a target it draws.
  const none = [{ id: "tdp", title: "Auto TDP", summary: "s", available: false, reason: "r" }];
  assert.equal(defaultSectionId(none), "tdp");
  assert.equal(resolveSectionId(none, "tdp"), "tdp");
});

test("a selection survives, and falls back only when the section is gone", () => {
  const sections = quickAccessSections(ready);
  assert.equal(resolveSectionId(sections, "tdp"), "tdp");
  assert.equal(resolveSectionId(sections, "nonsense"), "egpu");
  assert.equal(resolveSectionId(sections, undefined), "egpu");
});

test("an unavailable section is still resolved, so it can explain itself", () => {
  // Bouncing off it silently moved the player with no reason given, and made
  // the blocked/reason path unreachable from any real taxonomy.
  const blocked = quickAccessSections({ ...ready, tdpCanEnable: false });
  assert.equal(blocked.find((section) => section.id === "tdp").available, false);
  assert.equal(resolveSectionId(blocked, "tdp"), "tdp");
});

test("a fresh panel still opens on an available section, never a blocked one", () => {
  // Nobody lands on a blocked pane without having chosen it.
  const sections = quickAccessSections({ healthKnown: true });
  const opened = sections.find((section) => section.id === resolveSectionId(sections, undefined));
  assert.equal(opened.available, true);
});

test("titles stay short enough for the ~310px Decky panel", () => {
  for (const section of quickAccessSections(ready)) {
    assert.ok(section.title.length <= 16, `${section.id} title too long: ${section.title}`);
    assert.ok(section.summary.length <= 48, `${section.id} summary too long`);
  }
});
