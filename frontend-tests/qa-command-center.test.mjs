import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const load = (name) => {
  const source = readFileSync(new URL(`../src/${name}.ts`, import.meta.url), "utf8");
  return ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText;
};
const bundle = load("quick-access/performance-state")
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

test("the approved five tiles appear in the approved order", () => {
  assert.deepEqual(tilesFor({ status: status() }).map((t) => t.id), TILE_ORDER);
  assert.deepEqual(TILE_ORDER,
    ["fps", "tdp", "auto-tdp", "display", "safe-disconnect"]);
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
    const tiles = tilesFor(input);
    assert.deepEqual(tiles.map((t) => t.id), TILE_ORDER, JSON.stringify(input));
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

test("Safe Disconnect is present, prepared, and performs nothing", () => {
  const tile = by(tilesFor({ status: status() }))["safe-disconnect"];
  assert.equal(tile.developmental, true);
  assert.equal(tile.available, false);
  assert.equal(tile.activation, "notice", "opens information, never an operation");
  assert.equal(tile.actionLabel, null);
  assert.match(tile.reason, /cannot confirm a safe disconnect/i);
});

test("Safe Disconnect readiness is never inferred", () => {
  // Not from topology, not from connection state, not from two devices being on.
  for (const rest of [{}, { displayTarget: "TV" }, { safeDisconnectSupported: false }]) {
    const tile = by(tilesFor({ status: status({ enabled: true }) }, rest))["safe-disconnect"];
    assert.equal(tile.developmental, true, JSON.stringify(rest));
    assert.equal(tile.available, false);
  }
});

test("Auto TDP offers one context action, never a toggle", () => {
  assert.equal(by(tilesFor({ status: status({ enabled: true }) }))["auto-tdp"].actionLabel, "Stop");
  assert.equal(by(tilesFor({ status: status(), configured: true }))["auto-tdp"].actionLabel, "Start");
  assert.equal(by(tilesFor({ status: status(), configured: false }))["auto-tdp"].actionLabel, "Open Auto TDP");
});

test("Stop remains offered when starting is no longer permitted", () => {
  const tile = by(tilesFor({ status: status({ enabled: true, can_enable: false }) }))["auto-tdp"];
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

test("the display tile routes and never runs a transition itself", () => {
  const tile = by(tilesFor({ status: status() }, { displayTarget: "TV" })).display;
  assert.equal(tile.activation, "open", "guards stay with the surface that owns them");
});

test("every unavailable tile gives a reason", () => {
  for (const tile of tilesFor({ status: null })) {
    if (!tile.available) assert.ok(tile.reason, `${tile.id} declined without saying why`);
  }
});

test("two-dimensional traversal reaches all five tiles including the lone fifth", () => {
  const count = TILE_ORDER.length;
  assert.equal(stepGrid(tileIndex("fps"), count, TILE_COLUMNS, "right"), tileIndex("tdp"));
  assert.equal(stepGrid(tileIndex("fps"), count, TILE_COLUMNS, "down"), tileIndex("auto-tdp"));
  // Safe Disconnect sits alone on the last row; both cells above must reach it.
  assert.equal(stepGrid(tileIndex("auto-tdp"), count, TILE_COLUMNS, "down"), tileIndex("safe-disconnect"));
  assert.equal(stepGrid(tileIndex("display"), count, TILE_COLUMNS, "down"), tileIndex("safe-disconnect"));
});
