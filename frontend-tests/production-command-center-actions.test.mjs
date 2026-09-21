import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const index = readFileSync(new URL("../src/index.tsx", import.meta.url), "utf8");
const native = readFileSync(new URL("../src/quick-access/expanded-command-center/native.tsx", import.meta.url), "utf8");
const runtimeDetails = readFileSync(new URL("../src/quick-access/expanded-command-center/runtime-detail-source.ts", import.meta.url), "utf8");
const host = readFileSync(new URL("../src/quick-access/production-egpu-actions.tsx", import.meta.url), "utf8");
const model = readFileSync(new URL("../src/quick-access/command-center.ts", import.meta.url), "utf8");
const port = readFileSync(new URL("../src/power-request-port.ts", import.meta.url), "utf8");
const coordinator = readFileSync(new URL("../src/power-request-coordinator.ts", import.meta.url), "utf8");
const grid = readFileSync(new URL("../src/quick-access/command-center-grid.tsx", import.meta.url), "utf8");
const shortcutSettings = readFileSync(new URL("../src/quick-access/expanded-command-center/shortcut-settings.tsx", import.meta.url), "utf8");
const visualFixture = readFileSync(new URL("./qa-render-preview.tsx", import.meta.url), "utf8");

test("the focused Command Center no longer exposes demo wording", () => {
  assert.doesNotMatch(index, /Open expanded demo/);
  assert.doesNotMatch(shortcutSettings, /Open expanded demo/);
  assert.match(shortcutSettings, /Open Re-Gear from Steam's Quick Access menu/);
  assert.match(index, /<ProductionEgpuActionHost/);
  assert.match(native, /strTitle: "Re-Gear Command Center"/);
});

test("display activation calls the existing guarded display owner", () => {
  assert.match(native, /tile\.id==="switch-handheld"[\s\S]*runtimeDetails\?\.requestHandheld\(\)/);
  assert.match(runtimeDetails, /requestHandheld\(\)[\s\S]*state\.handheld\.request\(\)/);
  assert.match(index, /primaryDisplayAction\.target === "ally"[\s\S]*requestControllerDisplaySwitch\("ally"\)/);
  assert.match(index, /primaryDisplayAction\.target === "tv"[\s\S]*executeTvSwitch\(\)/);
});

test("production eGPU actions are exact and software reconnect is absent", () => {
  assert.match(host, /intent=\{request\.action === "shutdown" \? "shutdown" : "disconnect_only"\}/);
  assert.match(host, /startRequest/);
  assert.doesNotMatch(host, /whole_dock_reconnect|intent="disconnect"/);
  assert.match(coordinator, /"whole_dock_sleep_connected"/);
  assert.match(coordinator, /"whole_dock_shutdown"/);
  assert.doesNotMatch(coordinator, /"whole_dock_sleep"(?!_connected)/);
  assert.match(port, /execute\(true, "", "disconnect", action, true, attachment, requestId\)/);
});

test("resolution is visible but cannot dispatch", () => {
  assert.match(model, /id: "resolution"[\s\S]*available: false[\s\S]*activation: "notice"/);
  assert.doesNotMatch(index, /id === "resolution"[\s\S]*execute/);
});

test("eGPU status opens the existing read-only status route", () => {
  assert.match(index, /views:\{egpu:wrapDetail/);
  assert.match(native, /renderDetail/);
  assert.doesNotMatch(native, /tile\.id==="status"[\s\S]*execute/);
});

test("production tiles use exact artwork roles without duplicate legacy icons", () => {
  assert.match(grid, /"safe-disconnect": "disconnect"/);
  assert.match(grid, /"sleep-connected": "sleep-connected"/);
  assert.match(grid, /shutdown: "shutdown"/);
  assert.match(grid, /resolution: "resolution"/);
  assert.match(grid, /const hasRichArtwork = Boolean\(richTileArtworkId\(artworkId\)\)/);
  assert.match(grid, /\{!hasRichArtwork && <span[\s\S]*<ApprovedIcon/);
  for (const id of ["safe-disconnect", "sleep-connected", "shutdown", "resolution", "egpu-status"])
    assert.match(visualFixture, new RegExp(`\\['${id}'`));
});
