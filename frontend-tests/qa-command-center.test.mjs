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

test("Safe Disconnect is unavailable until the backend has been read", () => {
  // Absent status means not yet read, which is not the same as "no".
  const tile = by(tilesFor({ status: status() }))["safe-disconnect"];
  assert.equal(tile.available, false);
  assert.equal(tile.value.text, "Unknown");
  assert.equal(tile.activation, "notice", "opens information, never an operation");
  assert.equal(tile.actionLabel, null);
});

test("Safe Disconnect availability is never inferred from anything else", () => {
  // Not from topology, not from Auto TDP, not from a display target, not from
  // two devices being online. Only the backend's own status decides.
  for (const rest of [{}, { displayTarget: "TV" }]) {
    const tile = by(tilesFor({ status: status({ enabled: true }) }, rest))["safe-disconnect"];
    assert.equal(tile.available, false, JSON.stringify(rest));
  }
  const offered = by(tilesFor({ status: status() }, { disconnectStatus: disconnect() }))["safe-disconnect"];
  assert.equal(offered.available, true, "and only the backend can turn it on");
});

test("a standing external display asks for approval rather than reading blocked", () => {
  // Telling a player nothing can be done, when all that is missing is their
  // approval to turn the TV off, is the wrong answer.
  const tile = by(tilesFor({ status: status() },
    { disconnectStatus: disconnect({ display_release_required: true }) }))["safe-disconnect"];
  assert.equal(tile.available, true);
  assert.equal(tile.displayApprovalRequired, true);
  assert.equal(tile.reason, null);
});

test("a half-detached eGPU is attention, not a failed button press", () => {
  const tile = by(tilesFor({ status: status() }, {
    disconnectStatus: disconnect({
      availability: "recovery_required", ready: false, attemptable: false,
      code: "removal_transaction.partially_detached",
    }),
  }))["safe-disconnect"];
  assert.equal(tile.attention, true);
  assert.equal(tile.available, false);
  assert.equal(tile.actionLabel, null, "no disconnect is offered over a half-detached device");
});

test("an unfinished scan is not a clear device", () => {
  // holders and scan_complete travel separately; an empty list from a scan
  // that could not finish is not evidence that nothing is using the eGPU.
  const tile = by(tilesFor({ status: status() }, {
    disconnectStatus: disconnect({
      availability: "unavailable", ready: false, attemptable: false,
      holders: [], scan_complete: false, code: "removal_safety.client_scan_incomplete",
    }),
  }))["safe-disconnect"];
  assert.equal(tile.available, false);
  assert.match(tile.reason, /could not check every process/i);
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

test("the confirmation is passed through untouched, not restated here", () => {
  const tile = by(tilesFor({ status: status() }, { disconnectStatus: disconnect() }))["safe-disconnect"];
  assert.ok(tile.confirmation, "an offered disconnect must carry its confirmation");
  assert.match(tile.confirmation, /session will restart/i);
  assert.match(tile.confirmation, /keep the cable connected/i);
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
