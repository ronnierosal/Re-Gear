import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/index.tsx", import.meta.url), "utf8");

test("TV switching has one visible activation control", () => {
  assert.match(source, /else if \(payload\?\.inference.mode === "portable"\) void executeTvSwitch\(\);/);
  assert.doesNotMatch(source, /showSupervisedTvSwitchConfirmation/);
  assert.doesNotMatch(source, /previewSupervisedTvSwitch/);
});

test("display action names its target and keeps the shortcut separate from shutdown", () => {
  const card = source.slice(source.indexOf('<DashboardSurface primary>'), source.indexOf('{tvSwitchMessage &&'));
  assert.match(card, /"Switch to handheld"/);
  assert.match(card, /"Switch to TV"/);
  assert.match(card, /Hold Back\/View \+ Y for 3 seconds to switch/);
  assert.match(card, /if \(payload\?\.inference.mode === "docked_egpu"\) requestControllerDisplaySwitch\("ally"\)/);
  assert.match(card, /payload\?\.inference.mode !== "portable" && payload\?\.inference.mode !== "docked_egpu"/);
  assert.match(card, /safeDisconnectBusy/);
  assert.doesNotMatch(card, /executeSafeDisconnect\(true\)/);
  const disconnect = source.slice(source.indexOf('icon="power"'), source.indexOf('{safeDisconnectMessage &&'));
  assert.doesNotMatch(disconnect, /Back\/View \+ Y/);
  assert.match(disconnect, /onClick=\{requestSafeDisconnect\}/);
  assert.match(disconnect, /Keep the eGPU connected until fully powered off/);
});
