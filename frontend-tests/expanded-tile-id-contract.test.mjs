import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

/** Pin the tile id vocabulary shared by the mappers and the Unknown placeholders.
 *
 * The shell resolves its nested detail page by tile id. So if a placeholder uses
 * a different id than the mapped tile it stands in for, a player reading the
 * detail of a tile is dropped out of that view the moment the reading becomes
 * unknown -- which is exactly when they were looking. That failure is invisible
 * in a screenshot and only appears when live data changes under an open panel,
 * so it is pinned here rather than left to review.
 *
 * This caught a real mismatch: the placeholders were written with "connection"
 * and "external" while the mappers emit "egpu" and "controller".
 */

const load = (path) => {
  const src = readFileSync(new URL(`../src/${path}.ts`, import.meta.url), "utf8");
  return ts.transpileModule(src, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText;
};
const strip = (text) => text.replace(/^import[^;]*;$/gm, "");
const bundle = [
  "quick-access/performance-state",
  "quick-access/expanded-command-center/model",
  "quick-access/expanded-command-center/tiles",
  "quick-access/expanded-command-center/tile-source",
].map((path, index) => (index === 0 ? load(path) : strip(load(path)))).join("\n");
const { buildTiles } = await import(`data:text/javascript;base64,${Buffer.from(bundle).toString("base64")}`);

const evidence = (text) => ({ text, known: true, verified: true });
const live = () => ({
  fresh: true, manualWatts: 15,
  egpu: {
    connection: evidence("Link up"), renderGpu: evidence("External GPU"),
    displayConnected: evidence("Connected"), displayActive: evidence("Active"),
    session: evidence("Running"), game: evidence("No game running"),
    model: null, lifecycle: evidence("Ready"),
    disconnect: { text: "Not confirmed", safeClaim: false, reason: "r" },
    recovery: { reachable: true, note: null },
  },
  controller: {
    available: true, reason: null,
    builtin: { text: "Available", known: true },
    external: { text: "Connected", known: true },
    precision: "exact", precisionNote: null,
    shortcut: { text: "Available", known: true }, planned: [],
  },
  performance: {
    active: false, autoKnown: true, stopping: false, supported: true,
    configuredWatts: 15, configuredIsLimit: true, action: "open",
    reason: null, busy: false,
  },
});

const idsByTab = (view) => Object.fromEntries(
  Object.entries(view).map(([tab, tiles]) => [tab, tiles.map((tile) => tile.id).sort()]),
);

test("each tab offers the same tile ids whether readings are live or unknown", () => {
  const known = idsByTab(buildTiles(live()));
  const unknown = idsByTab(buildTiles({ fresh: false }));
  for (const tab of Object.keys(known)) {
    assert.deepEqual(unknown[tab], known[tab],
      `${tab} changes its tile ids between live and unknown`);
  }
});

test("a tile open in the detail view survives its reading going unknown", () => {
  // The shell keeps the id and re-resolves it. Every live id must therefore
  // still exist in the unknown view, or the detail page falls back to its
  // "no longer available" state while the tile is in fact still on the grid.
  const known = buildTiles(live());
  const unknown = buildTiles({ fresh: false });
  for (const [tab, tiles] of Object.entries(known)) {
    for (const tile of tiles) {
      assert.ok(unknown[tab].some((candidate) => candidate.id === tile.id),
        `${tab}/${tile.id} disappears when readings go unknown`);
    }
  }
});

test("tile ids are unique within every tab", () => {
  // The shell finds by id; a duplicate would make the detail page ambiguous.
  for (const view of [buildTiles(live()), buildTiles({ fresh: false })]) {
    for (const [tab, tiles] of Object.entries(view)) {
      const ids = tiles.map((tile) => tile.id);
      assert.equal(new Set(ids).size, ids.length, `${tab} has duplicate tile ids`);
    }
  }
});
