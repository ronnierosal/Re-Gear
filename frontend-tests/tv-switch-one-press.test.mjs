import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/index.tsx", import.meta.url), "utf8");

test("TV switching has one visible activation control", () => {
  assert.match(source, /else if \(primaryDisplayAction.target === "tv"\) void executeTvSwitch\(\);/);
  assert.doesNotMatch(source, /showSupervisedTvSwitchConfirmation/);
  assert.doesNotMatch(source, /previewSupervisedTvSwitch/);
});

test("display action names its target and keeps the shortcut separate from shutdown", () => {
  const card = source.slice(source.indexOf('<DashboardSurface primary>'), source.indexOf('{tvSwitchMessage &&'));
  assert.match(card, /title=\{primaryDisplayAction.title\}/);
  assert.match(card, /description=\{primaryDisplayAction.description\}/);
  assert.match(card, /if \(primaryDisplayAction.target === "ally"\) requestControllerDisplaySwitch\("ally"\)/);
  assert.match(card, /if \(primaryDisplayAction.disabled\) return/);
  assert.match(card, /disabled=\{primaryDisplayAction.disabled\}/);
  assert.match(source, /tvSwitchBusy \|\| safeDisconnectBusy, Boolean\(tvSwitchAcknowledgementId\)/);
  assert.doesNotMatch(card, /executeSafeDisconnect\(true\)/);
  const disconnect = source.slice(source.indexOf('icon="power"'), source.indexOf('{safeDisconnectMessage &&'));
  assert.doesNotMatch(disconnect, /Back\/View \+ Y/);
  assert.match(disconnect, /onClick=\{requestSafeDisconnect\}/);
  assert.match(disconnect, /Keep the eGPU connected until fully powered off/);
});
