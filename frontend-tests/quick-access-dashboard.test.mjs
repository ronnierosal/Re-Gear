import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { placementCards, hardwareDetailRows } from "../src/quick-access-dashboard.ts";

test("mode cards select only known observed placement, never connection readiness", () => {
  for (const mode of ["unknown", "degraded", "boosted_handheld", "future_mode"]) {
    assert.ok(placementCards(mode).every((card) => !card.active));
  }
  assert.deepEqual(placementCards("portable").map((card) => card.active), [true, false]);
  assert.deepEqual(placementCards("tv_docked").map((card) => card.active), [false, true]);
  assert.deepEqual(placementCards("docked_egpu").map((card) => card.active), [false, true]);
  assert.ok(placementCards("portable", true).every((card) => !card.active));
});

test("connection without active output or selected GPU stays unknown", () => {
  assert.ok(hardwareDetailRows(null).every(([, value]) => value === "Unknown"));
  const payload = { snapshot: {
    displays: [{ kind: "external", connected: true, active: false, confidence: "verified" }],
    gpus: [{ role: "external", present: true, selected_for_render: false, confidence: "verified" }],
    egpu_link: { applicable: true, state: "up", confidence: "unknown" },
  } };
  assert.ok(hardwareDetailRows(payload).every(([, value]) => value === "Unknown"));
});

test("hardware disclosure separates observed display, render GPU and link", () => {
  const payload = { snapshot: {
    displays: [{ kind: "external", active: true, confidence: "verified" }],
    gpus: [{ role: "internal", present: true, selected_for_render: true, confidence: "verified" }],
    egpu_link: { applicable: true, state: "down", confidence: "observed" },
  } };
  assert.deepEqual(hardwareDetailRows(payload), [
    ["Active display", "External"], ["Render GPU", "Internal GPU"], ["eGPU link", "Observed down"],
  ]);
  payload.snapshot.gpus.push({ role: "external", present: true, selected_for_render: true, confidence: "verified" });
  assert.equal(hardwareDetailRows(payload)[1][1], "Unknown");
  payload.snapshot.displays[0].confidence = "unknown";
  assert.equal(hardwareDetailRows(payload)[0][1], "Unknown");
});

test("compact dashboard keeps native controls, single guarded action and local disclosure", () => {
  const source = readFileSync(new URL("../src/index.tsx", import.meta.url), "utf8");
  const overview = readFileSync(new URL("../src/quick-access-overview.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(overview, /onClick|onActivate|<button|setInterval|fetch\(/);
  assert.equal((source.match(/else if \(payload\?\.inference.mode === "portable"\) void executeTvSwitch\(\);/g) ?? []).length, 1);
  assert.match(source, /<ToggleField\s+label="Automatic TV docking"\s+layout="inline"/);
  assert.match(source, /onClick=\{\(\) => setShowHardwareDetails\(\(visible\) => !visible\)\}/);
  assert.match(source, /showHardwareDetails &&[\s\S]*hardwareDetailRows\(payload\)/);
  assert.ok(source.indexOf("<DashboardSurface primary>") > source.indexOf('<ToggleField\n'));
  assert.match(source, /Keep the eGPU connected until fully powered off/);
  assert.match(overview, /import handheldModeIcon from "\.\/assets\/mode-handheld\.svg"/);
  assert.match(overview, /import tvModeIcon from "\.\/assets\/mode-tv\.svg"/);
  assert.match(overview, /isPortable \? handheldModeIcon : tvModeIcon/);
});

test("dashboard actions keep icons and text inside one native button, not Item columns", () => {
  const action = readFileSync(new URL("../src/dashboard-action.tsx", import.meta.url), "utf8");
  const source = readFileSync(new URL("../src/index.tsx", import.meta.url), "utf8");
  assert.match(action, /<DialogButton onClick=\{onClick\} disabled=\{disabled\}/);
  assert.match(action, /gridTemplateColumns: "38px minmax\(0,1fr\) 18px"/);
  assert.match(action, /wordBreak: "normal",\s+overflowWrap: "normal"/);
  assert.doesNotMatch(action, /ButtonItem|noFocusRing=|outline:|overflow: "hidden"/);
  assert.equal((source.match(/<DashboardAction\s/g) ?? []).length, 5);
  assert.match(source, /title="Dock \/ eGPU"[\s\S]*expanded=\{showHardwareDetails\}/);
  assert.match(source, /title="Troubleshoot"[\s\S]*expanded=\{showDiagnostics\}/);
});
