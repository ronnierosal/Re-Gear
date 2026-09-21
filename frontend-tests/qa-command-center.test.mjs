import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const load = (name) => {
  const source = readFileSync(new URL(`../src/${name}.ts`, import.meta.url), "utf8");
  return ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText;
};
const bundle = load("quick-access/performance-state")
  + load("egpu-disconnect-tile").replace(/^import[^;]*;$/gm, "")
  + load("quick-access/command-center").replace(/^import[^;]*;$/gm, "")
  + load("quick-access/module-registry").replace(/^import[^;]*;$/gm, "");
const m = await import(`data:text/javascript;base64,${Buffer.from(bundle).toString("base64")}`);
const { commandCenterTiles, performanceState, TILE_ORDER, TILE_COLUMNS, tileIndex, stepGrid } = m;

const status = (over = {}) => ({
  schema_version: 1, enabled: false, can_enable: true, ready: true, code: "tdp.ready",
  current_watts: 15, minimum_watts: 5, maximum_watts: 30, restore_available: false,
  recovery_required: false, auto_tdp_available: true, last_result: null, ...over,
});
const tilesFor = (perfInput, rest = {}) =>
  commandCenterTiles({ performance: performanceState(perfInput), ...rest });
const by = (tiles) => Object.fromEntries(tiles.map((t) => [t.id, t]));

const disconnect = (over = {}) => ({
  schema_version: 1, availability: "ready", code: "removal_safety.clear", ready: true,
  attemptable: true, busy: false, holders: [], scan_complete: true,
  external_display_committed: false, display_release_required: false, last: null, ...over,
});

test("the production controls appear in a stable order", () => {
  assert.deepEqual(tilesFor({ status: status() }).map((t) => t.id), TILE_ORDER);
  assert.deepEqual(TILE_ORDER,
    ["fps", "tdp", "auto-tdp", "display", "safe-disconnect", "sleep-connected",
      "shutdown", "resolution", "egpu-status"]);
});

test("the grid shape never depends on live evidence", () => {
  // A tile that disappears moves every tile after it under the player's thumb.
  const cases = [
    { status: null },
    { status: status({ auto_tdp_available: false }) },
    { status: status({ enabled: true }) },
    { status: status({ recovery_required: true }), configured: true },
  ];
  for (const input of cases) {
    assert.deepEqual(tilesFor(input).map((t) => t.id), TILE_ORDER, JSON.stringify(input));
  }
  // Including every disconnect state: the grid must not reshape as the eGPU
  // status changes underneath a player's thumb.
  for (const d of [null, disconnect(), disconnect({ availability: "busy", attemptable: false }),
    disconnect({ availability: "recovery_required", attemptable: false })]) {
    assert.deepEqual(tilesFor({ status: status() }, { disconnectStatus: d }).map((t) => t.id), TILE_ORDER);
  }
});

test("no tile fabricates a value", () => {
  const tiles = tilesFor({ status: status({ auto_tdp_available: false, current_watts: null }) });
  for (const tile of tiles) {
    if (!tile.value.known) {
      assert.doesNotMatch(tile.value.text, /^\d/, `${tile.id} invented a number`);
    }
  }
  const unknownWatts = by(tilesFor({ status: status({ current_watts: null }) })).tdp;
  assert.equal(unknownWatts.value.known, false);
  assert.equal(unknownWatts.value.text, "Unknown", "never 0 W");
});

test("Safe Disconnect delegates admission to the guarded whole-dock owner", () => {
  const tile = by(tilesFor({ status: status() }))["safe-disconnect"];
  assert.equal(tile.available, true);
  assert.equal(tile.activation, "act");
  assert.equal(tile.value.text, "Guarded");
  assert.equal(tile.confirmation, undefined, "the model does not recreate lifecycle confirmation");
});

test("power actions stay distinct and disconnect-before-sleep is absent", () => {
  const tiles = by(tilesFor({ status: status() }));
  assert.equal(tiles["sleep-connected"].activation, "act");
  assert.equal(tiles["shutdown"].activation, "act");
  assert.doesNotMatch(JSON.stringify(tiles), /Safe Disconnect \+ Sleep|whole_dock_sleep/i);
});

test("Resolution stays visible and honestly unavailable", () => {
  const tile = by(tilesFor({ status: status() })).resolution;
  assert.equal(tile.available, false);
  assert.equal(tile.activation, "notice");
  assert.match(tile.reason, /No verified resolution provider/);
});

test("eGPU Status is a read-only navigation target", () => {
  const tile = by(tilesFor({ status: status() }))["egpu-status"];
  assert.equal(tile.available, true);
  assert.equal(tile.activation, "open");
});

test("no disconnect state ever presents unplugging as safe", () => {
  // Software removal is not unplug clearance, whatever the readings say.
  const states = [
    null, disconnect(), disconnect({ display_release_required: true }),
    disconnect({ availability: "busy", busy: true, attemptable: false, ready: false }),
    disconnect({ availability: "recovery_required", attemptable: false, ready: false }),
    disconnect({ availability: "unavailable", attemptable: false, ready: false }),
  ];
  for (const disconnectStatus of states) {
    const tiles = tilesFor({ status: status() }, { disconnectStatus });
    const rendered = JSON.stringify(tiles);
    assert.doesNotMatch(rendered, /safe to (unplug|disconnect|remove)/i);
    assert.doesNotMatch(rendered, /you (can|may) (now )?(unplug|remove)/i);
  }
});

test("Auto TDP offers one context action, never a toggle", () => {
  assert.equal(by(tilesFor({ status: status({ enabled: true }), autoStatus: { running: true } }))["auto-tdp"].actionLabel, "Stop");
  assert.equal(by(tilesFor({ status: status(), configured: true }))["auto-tdp"].actionLabel, "Configure");
  assert.equal(by(tilesFor({ status: status(), configured: false }))["auto-tdp"].actionLabel, "Configure");
});

test("Stop remains offered when starting is no longer permitted", () => {
  const tile = by(tilesFor({ status: status({ enabled: true, can_enable: false }), autoStatus: { running: true } }))["auto-tdp"];
  assert.equal(tile.actionLabel, "Stop");
  assert.equal(tile.activation, "act");
});

test("FPS keeps its slot, explains itself and shows no number", () => {
  const tile = by(tilesFor({ status: status() })).fps;
  assert.equal(tile.available, false);
  assert.equal(tile.activation, "none");
  assert.doesNotMatch(tile.value.text, /\d/);
  assert.match(tile.reason, /frame-rate provider/i);
});

test("Display target reads unknown rather than guessing", () => {
  assert.equal(by(tilesFor({ status: status() })).display.value.text, "Unknown");
  assert.equal(by(tilesFor({ status: status() }, { displayTarget: "TV" })).display.value.text, "TV");
});

test("the display tile mirrors the guarded dynamic action", () => {
  const tv = by(tilesFor({ status: status() }, { displayTarget: "Handheld",
    displayAction: { target: "tv", title: "Switch to TV", disabled: false, description: "Ready" } })).display;
  assert.equal(tv.title, "Switch to TV");
  assert.equal(tv.activation, "act");
  const handheld = by(tilesFor({ status: status() }, { displayTarget: "External",
    displayAction: { target: "ally", title: "Switch to handheld", disabled: false, description: "Ready" } })).display;
  assert.equal(handheld.title, "Switch to handheld");
  assert.equal(handheld.activation, "act");
  const blocked = by(tilesFor({ status: status() }, { displayAction: {
    target: null, title: "Display switch unavailable", disabled: true, description: "State unknown" } })).display;
  assert.equal(blocked.activation, "notice");
  assert.equal(blocked.reason, "State unknown");
});

test("every unavailable tile gives a reason", () => {
  for (const tile of tilesFor({ status: null })) {
    if (!tile.available) assert.ok(tile.reason, `${tile.id} declined without saying why`);
  }
});

test("two-dimensional traversal reaches all production controls", () => {
  const count = TILE_ORDER.length;
  assert.equal(stepGrid(tileIndex("fps"), count, TILE_COLUMNS, "right"), tileIndex("tdp"));
  assert.equal(stepGrid(tileIndex("fps"), count, TILE_COLUMNS, "down"), tileIndex("auto-tdp"));
  assert.equal(stepGrid(tileIndex("auto-tdp"), count, TILE_COLUMNS, "down"), tileIndex("safe-disconnect"));
  assert.equal(stepGrid(tileIndex("display"), count, TILE_COLUMNS, "down"), tileIndex("sleep-connected"));
  assert.equal(stepGrid(tileIndex("shutdown"), count, TILE_COLUMNS, "down"), tileIndex("egpu-status"));
  assert.equal(stepGrid(tileIndex("resolution"), count, TILE_COLUMNS, "down"), tileIndex("egpu-status"));
});

 test("manual power enablement never claims a running Auto TDP loop", () => {
   const tile = by(tilesFor({ status: status({ enabled: true }), autoStatus: { running: false } }))["auto-tdp"];
   assert.equal(tile.value.text, "Off");
   assert.equal(tile.actionLabel, "Configure");
   assert.equal(by(tilesFor({ status: status({ enabled: true }) }))["auto-tdp"].value.text, "Unknown");
 });

test("stopping loop is named explicitly without a duplicate Stop", () => {
  const tile = by(tilesFor({ status: status(), autoStatus: {running:true, stopping:true} }))["auto-tdp"];
  assert.equal(tile.value.text, "Stopping…");
  assert.equal(tile.activation, "none");
});
