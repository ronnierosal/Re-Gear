import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

// Exercise the production mapper, not sampleTiles or source-string assertions.
const modules = [
  "quick-access/performance-state",
  "quick-access/expanded-command-center/model",
  "quick-access/expanded-command-center/tiles",
  "quick-access/expanded-command-center/tile-source",
];
const bundle = modules.map((path) => ts.transpileModule(
  readFileSync(new URL(`../src/${path}.ts`, import.meta.url), "utf8"),
  { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } },
).outputText.replace(/^import[^;]*;$/gm, "")).join("\n");
const { buildTiles, createTilePublisher, restoreTarget } = await import(
  `data:text/javascript;base64,${Buffer.from(bundle).toString("base64")}`
);

// Approved runtime identities from PR306 a660ebd's runtime handoff. Keep this
// acceptance oracle independent of the mapper: deriving it from live output
// would allow deleting a card from both live and unknown paths to pass.
const approved = {
  quick: ["fps", "manual", "auto", "display", "egpu", "controller", "disconnect"],
  performance: ["profile", "fps", "manual", "auto", "display", "refresh"],
  egpu: ["device", "dock", "display", "render", "link", "disconnect"],
  controllers: ["controller", "battery", "builtin", "priority", "tv-controller", "controller-settings"],
  settings: ["quick-actions", "shortcut", "appearance", "updates", "diagnostics", "about"],
};
const evidence = (text) => ({ text, known: true, verified: true });
const live = () => ({
  fresh: true,
  performanceFresh: true,
  // Controller evidence is gated by its own source, so a live case has to
  // say so or these inputs never reach the mapper.
  controllerFresh: true,
  manualWatts: 15,
  // Active external output is not a resolution/refresh-rate observation.
  displayTarget: evidence("External"),
  egpu: {
    connection: evidence("Link up"), renderGpu: evidence("External GPU"),
    displayConnected: evidence("Connected"), displayActive: evidence("Active"),
    session: evidence("Running"), game: evidence("No game running"),
    model: "Observed GPU", lifecycle: evidence("Ready"),
    disconnect: { text: "Not confirmed", safeClaim: false, reason: "Readiness required" },
    recovery: { reachable: true, note: null },
  },
  controller: {
    available: true, reason: null,
    builtin: { text: "Available", known: true },
    // External presence does not establish Steam's Player 1 assignment.
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

for (const [tab, expected] of Object.entries(approved)) {
  test(`live ${tab} preserves approved cards and remembered target identities`, () => {
    const publisher = createTilePublisher();
    for (const readings of [
      {}, { fresh: true, performanceFresh: true }, live(),
      { ...live(), fresh: false, performanceFresh: false, controllerFresh: false }, live(),
    ]) {
      publisher.publish(readings);
      const tiles = publisher.source.read()[tab];
      assert.ok(Array.isArray(tiles), `${tab} must never fall back to samples`);
      const ids = tiles.map(({ id }) => id);
      assert.deepEqual(ids, expected, `${tab} changed the approved composition`);
      for (const focused of expected) {
        assert.equal(restoreTarget(ids, focused), focused,
          `${tab}/${focused} loses remembered focus when observation changes`);
      }
    }
  });
}

for (const [tab, ids] of [
  ["performance", ["profile", "fps", "display", "refresh"]],
  ["controllers", ["controller", "battery", "priority"]],
]) {
  for (const id of ids) {
    test(`live ${tab}/${id} retains its missing-provider card without invented readings`, () => {
      const view = buildTiles(live());
      const tile = view[tab].find((candidate) => candidate.id === id);
      assert.ok(tile, `${tab}/${id} must remain visible without a provider`);
      assert.match(tile.value, /unknown|unavailable|not available|not supported/i,
        `${tab}/${id} has no verified producer in these readings`);
      assert.equal(tile.tone, "unavailable", `${tab}/${id} must not imply verified support`);
    });
  }
}

test("both live and unknown views retain the wide guarded disconnect entry", () => {
  for (const readings of [live(), {}, { ...live(), fresh: false, controllerFresh: false }]) {
    const view = buildTiles(readings);
    for (const tab of ["quick", "egpu"]) {
      const tile = view[tab].find(({ id }) => id === "disconnect");
      assert.ok(tile, `${tab} must retain Safe Disconnect`);
      assert.equal(tile.wide, true);
      assert.equal(tile.tone, "warning");
      assert.doesNotMatch(tile.value, /safe to (?:unplug|disconnect)|ready to unplug/i);
    }
  }
});
