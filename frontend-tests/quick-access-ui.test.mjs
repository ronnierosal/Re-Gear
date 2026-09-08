import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

import {
  atAGlanceRows,
  compactJourneyStatusRows,
  compactStatusPanels,
  quickAccessSectionVisibility,
  revealJourneyDetails,
  journeyStatusRows,
  restoreQuickAccessFocus,
} from "../src/quick-access-ui.ts";

test("backend-retired display success releases stale acknowledgement UI", () => {
  const source = readFileSync(new URL("../src/index.tsx", import.meta.url), "utf8");
  const refresh = source.slice(source.indexOf("const refreshTransitionJournal ="), source.indexOf("const refreshTransitionJournal =") + 800);
  assert.match(refresh, /if \(status.code === "journal.idle"\) \{[^}]*setTvSwitchAcknowledgementId\(""\)/);
});

test("upward navigation reaches the native status focus stop before leaving HDM", () => {
  const source = readFileSync(new URL("../src/index.tsx", import.meta.url), "utf8");
  const summary = source.slice(source.indexOf('<PanelSection title="At a glance">'), source.indexOf('<PanelSection title="Docking & actions">'));
  assert.match(summary, /<QuickAccessOverview[\s\S]*summaryRef=\{statusFocusAnchor\}/);
  assert.match(summary, /onSummaryFocus=\{[\s\S]*scrollToTopOfOwningPanel\(statusAnchor.current\)/);
  assert.doesNotMatch(summary, /onActivate|onCancel|onGamepadDirection/);
  assert.match(source, /statusFocusAnchor.current \?\? primaryControlAnchor.current/);
});

test("informational sections have separate native focus stops without activation handlers", () => {
  const read = name => readFileSync(new URL(`../src/${name}`, import.meta.url), "utf8");
  const focus = read("section-focus.tsx");
  const overview = read("quick-access-overview.tsx");
  const readiness = read("connection-quick-status.tsx");
  assert.match(focus, /<Field ref=\{ref\} focusable=\{true\} highlightOnFocus=\{false\}/);
  assert.match(focus, /padding="none" bottomSeparator="none" childrenLayout="below"/);
  assert.doesNotMatch(focus, /<Focusable/);
  assert.match(focus, /role="group"/);
  assert.match(focus, /scrollIntoView/);
  assert.doesNotMatch(focus, /onActivate|onClick|onCancel|<button/);
  assert.match(overview, /label="At a glance: current state"/);
  assert.match(overview, /label="Your setup"/);
  assert.ok(readiness.indexOf('</SectionFocus>') < readiness.indexOf('<DialogButton'));
  assert.match(readiness, /label="eGPU readiness"/);
  assert.match(read("index.tsx"), /PanelSection title="eGPU readiness"/);
  assert.match(read("regear-theme.ts"), /rg-section-focus.gpfocus/);
  assert.doesNotMatch(overview, /StatusPill|fontSize: 26/);
});

test("neutral informational focus does not suppress action focus cues", () => {
  const css = readFileSync(new URL("../src/regear-theme.ts", import.meta.url), "utf8");
  const section = css.slice(css.indexOf('.rg-section-focus,'), css.indexOf('.rg-dashboard-action:focus-visible'));
  assert.match(section, /background: transparent !important/);
  assert.match(section, /outline: none !important/);
  assert.doesNotMatch(section.slice(0, section.indexOf('{')), /button|input|rg-dashboard-action|\*/);
  const actions = css.slice(css.indexOf('.rg-dashboard-action:focus-visible'));
  assert.match(actions, /outline: 2px solid #66d9f7 !important/);
});

test("secondary sections stay hidden until the player opens Troubleshoot", () => {
  assert.deepEqual(quickAccessSectionVisibility(false), {
    journey: false,
    sleepProtection: false,
    disconnectReadiness: false,
    support: false,
    diagnostics: false,
    navigation: false,
  });
  assert.deepEqual(quickAccessSectionVisibility(true), {
    journey: true,
    sleepProtection: true,
    disconnectReadiness: true,
    support: true,
    diagnostics: true,
    navigation: true,
  });
});

test("dashboard uses native preference controls without bypassing confirmation", () => {
  const source = readFileSync(new URL("../src/index.tsx", import.meta.url), "utf8");
  assert.match(source, /<QuickAccessOverview/);
  assert.match(source, /<DashboardSurface primary>/);
  assert.match(source, /<ToggleField[\s\S]*?checked=\{automaticDockStatus\?\.enabled === true\}/);
  assert.match(source, /disabled=\{automaticDockBusy \|\| !automaticDockStatus\}/);
  assert.match(source, /onChange=\{toggleAutomaticDock\}/);
  assert.match(source, /automaticDockModal.current = showAutomaticDockConfirmation\(/);
  assert.match(source, /<DashboardAction\s+title="Troubleshoot"[\s\S]*?expanded=\{showDiagnostics\}/);
});

test("at-a-glance UI remains compact and preserves progressive state labels", () => {
  assert.deepEqual(
    atAGlanceRows({
      mode: "Portable",
      health: "Ready",
      connection: "Ready to dock",
      game: "No game running",
    }),
    [
      ["Mode", "Portable"],
      ["Health", "Ready"],
      ["Connection", "Ready to dock"],
      ["Game", "No game running"],
    ],
  );
});

test("journey status is glanceable, fail-closed, and keeps detail on demand", () => {
  const rows = journeyStatusRows({
    deferred_dock: { state: "deferred", code: "private.code" },
    prepared_docked_idle: { state: "prepared", code: "private.code" },
    safe_undock: { state: "ready_for_revalidation", code: "private.code" },
    unexpected_removal_recovery: { state: "recovery_incomplete", code: "private.code" },
    link_instability: {
      schema_version: 1,
      status: "instability_observed",
      code: "private.code",
      current_state: "down",
    },
    offline_readiness: {
      schema_version: 1,
      status: "ready_to_try_offline",
      reason_codes: ["local_readiness_confirmed"],
    },
  });
  assert.deepEqual(rows.map(({ name, value }) => [name, value]), [
    ["Dock request", "Waiting for game to close"],
    ["Prepared state", "Prepared evidence"],
    ["Safe Undock evidence", "Needs revalidation"],
    ["Recovery", "Recovery incomplete"],
    ["Link evidence", "State change observed"],
    ["Offline readiness", "Ready to try offline"],
  ]);
  assert.doesNotMatch(JSON.stringify(rows), /private\.code/);
  assert.match(rows[2].detail, /not a physical-unplug approval/i);
  assert.match(rows[4].detail, /does not diagnose cable quality/i);
  assert.match(rows[5].detail, /not guaranteed/i);
});

test("unwired or unknown journey states never resemble a hardware result", () => {
  const rows = journeyStatusRows({ safe_undock: { state: "future_state", code: "x" } });
  assert.equal(rows[0].value, "Not connected");
  assert.equal(rows[2].value, "Not connected");
  assert.match(rows[2].detail, /not yet wired/i);
});

test("journey summary stays compact while details retain unwired sources", () => {
  assert.deepEqual(compactJourneyStatusRows(undefined), [{
    name: "Status",
    value: "Not connected",
    detail: "No read-only journey status is connected yet. Open details to review each future status source.",
  }]);
  const summary = compactJourneyStatusRows({
    deferred_dock: { state: "deferred", code: "private.code" },
  });
  assert.deepEqual(summary.map(({ name, value }) => [name, value]), [
    ["Dock request", "Waiting for game to close"],
  ]);
  assert.equal(journeyStatusRows({ deferred_dock: { state: "deferred", code: "private.code" } }).length, 6);
  assert.doesNotMatch(JSON.stringify(summary), /private\.code/);
});

test("returning to status focuses an in-panel native control, never QAM Back", () => {
  assert.deepEqual(compactStatusPanels(), {
    showDiagnostics: false,
    showJourneyDetails: false,
  });
  const calls = [];
  const control = { focus: (options) => calls.push(options) };
  assert.equal(restoreQuickAccessFocus(() => control), true);
  assert.deepEqual(calls, [{ preventScroll: true }]);
  assert.equal(restoreQuickAccessFocus(() => null), false);
});

test("opening journey details reveals the new section without changing focus", () => {
  const calls = [];
  const anchor = { scrollIntoView: (options) => calls.push(options) };
  assert.equal(revealJourneyDetails(anchor), true);
  assert.deepEqual(calls, [{ block: "nearest", behavior: "smooth" }]);
  assert.equal(revealJourneyDetails(null), false);
});
