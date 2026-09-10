import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const load = (path) => {
  const src = readFileSync(new URL(`../src/${path}.ts`, import.meta.url), "utf8");
  return ts.transpileModule(src, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText;
};
// Relative imports cannot resolve inside a data: URL, so the graph is
// concatenated and the import lines stripped.
const strip = (text) => text.replace(/^import[^;]*;$/gm, "");
// Only value modules are bundled. tiles.ts and tile-source.ts import the two
// presentation modules as types, which erase; including them would collide,
// because each declares its own top-level UNKNOWN.
const bundle = [
  "quick-access/performance-state",
  "quick-access/expanded-command-center/model",
  "quick-access/expanded-command-center/tiles",
  "quick-access/expanded-command-center/tile-source",
].map((path, index) => (index === 0 ? load(path) : strip(load(path)))).join("\n");
const m = await import(`data:text/javascript;base64,${Buffer.from(bundle).toString("base64")}`);
const { buildTiles, createTilePublisher, tabs } = m;

const evidence = (text, known = true, verified = true) => ({ text, known, verified });
const egpuPresentation = () => ({
  connection: evidence("Link up"), renderGpu: evidence("External GPU"),
  displayConnected: evidence("Connected"), displayActive: evidence("Active"),
  session: evidence("Running"), game: evidence("No game running"),
  model: "Vendor Model", lifecycle: evidence("Ready"),
  disconnect: { text: "Not confirmed", safeClaim: false, reason: "Re-Gear cannot confirm." },
  recovery: { reachable: true, note: null },
});
const controllerPresentation = () => ({
  available: true, reason: null,
  builtin: { text: "Available", known: true },
  external: { text: "Not connected", known: true },
  precision: "exact", precisionNote: null,
  shortcut: { text: "Available", known: true },
  planned: ["Player order"],
});
const performanceState = (over = {}) => ({
  active: false, autoKnown: true, stopping: false, supported: true,
  configuredWatts: 15, configuredIsLimit: true, action: "open",
  reason: null, busy: false, ...over,
});
const full = () => ({
  egpu: egpuPresentation(), controller: controllerPresentation(),
  performance: performanceState(), manualWatts: 15, fresh: true,
});

// ----------------------------------------------------------- every tab supplied

test("every tab is supplied, so the shell can never fall back to sample data", () => {
  // An absent tab is exactly what makes the shell render confident samples.
  for (const readings of [full(), { fresh: false }, {}]) {
    const view = buildTiles(readings);
    for (const tab of tabs) {
      assert.ok(Array.isArray(view[tab]), `${tab} missing for ${JSON.stringify(Object.keys(readings))}`);
      assert.ok(view[tab].length > 0, `${tab} empty`);
    }
  }
});

test("no supplied tile ever carries a confident sample string", () => {
  // These are the fabrications the prototype shipped; none may reappear.
  for (const readings of [full(), { fresh: false }]) {
    const rendered = JSON.stringify(buildTiles(readings));
    assert.doesNotMatch(rendered, /RX 7600M XT/i, "invented GPU model");
    assert.doesNotMatch(rendered, /\bP1\b|Player 1/i, "invented player order");
    assert.doesNotMatch(rendered, /1080p|\d+\s*Hz/i, "invented resolution or refresh rate");
    assert.doesNotMatch(rendered, /sample/i, "sample wording");
  }
});

// --------------------------------------------------------------- unknown states

test("no readings yet renders explicit Unknown, not a plausible default", () => {
  const view = buildTiles({ fresh: false });
  for (const tab of ["quick", "performance", "egpu", "controllers"]) {
    for (const tile of view[tab]) {
      assert.equal(tile.value, "Unknown", `${tab}/${tile.id}`);
      assert.equal(tile.tone, "unavailable", `${tab}/${tile.id}`);
    }
  }
});

test("a stale or failed read is Unknown even though the payload survives", () => {
  // index.tsx keeps the previous payload when a refresh throws, so freshness is
  // passed in rather than inferred from the payload being non-null.
  const stale = buildTiles({ ...full(), fresh: false });
  assert.equal(stale.egpu.every((tile) => tile.value === "Unknown"), true);
  const live = buildTiles(full());
  assert.notEqual(live.egpu[0].value, "Unknown");
});

test("watts are the configured limit and unknown watts never become a number", () => {
  const known = buildTiles(full()).performance.find((tile) => tile.id === "manual");
  assert.match(known.value, /15\s*W/);
  const unknown = buildTiles({ ...full(), manualWatts: null }).performance
    .find((tile) => tile.id === "manual");
  assert.doesNotMatch(unknown.value, /^\d/, "no fabricated wattage");
});

// ------------------------------------------------------------------ consistency

test("the quick tab reuses mapped tiles rather than deriving a second opinion", () => {
  const view = buildTiles(full());
  const quickAuto = view.quick.find((tile) => tile.id === "auto");
  const perfAuto = view.performance.find((tile) => tile.id === "auto");
  assert.equal(quickAuto.value, perfAuto.value);
  const quickConnection = view.quick.find((tile) => tile.id === "egpu");
  const egpuConnection = view.egpu.find((tile) => tile.id === "egpu");
  assert.equal(quickConnection.value, egpuConnection.value);
});

test("settings states unsupported entries as unavailable rather than dropping them", () => {
  const settings = buildTiles(full()).settings;
  assert.ok(settings.length > 0);
  for (const tile of settings) assert.equal(tile.tone, "unavailable");
  // The real shortcut control is supplied natively, not as a tile.
  assert.equal(settings.some((tile) => /shortcut/i.test(tile.title)), false);
});

// ------------------------------------------------- publisher and stable identity

test("read is stable by reference between publishes", () => {
  // useSyncExternalStore compares by reference; a fresh object per call would
  // re-render without end. This is correctness, not an optimisation.
  const { source } = createTilePublisher();
  assert.equal(source.read(), source.read());
  assert.equal(source.read(), source.read());
});

test("publish replaces the view and notifies every subscriber once", () => {
  const { source, publish } = createTilePublisher();
  const before = source.read();
  let a = 0, b = 0;
  source.subscribe(() => { a += 1; });
  source.subscribe(() => { b += 1; });
  publish(full());
  assert.equal(a, 1);
  assert.equal(b, 1);
  assert.notEqual(source.read(), before, "a publish must produce a new view");
  assert.equal(source.read(), source.read(), "and be stable again afterwards");
});

test("an unsubscribed listener stops being called", () => {
  const { source, publish } = createTilePublisher();
  let calls = 0;
  const stop = source.subscribe(() => { calls += 1; });
  publish(full());
  stop();
  publish(full());
  assert.equal(calls, 1);
});

test("one throwing listener does not stop the others being told", () => {
  const { source, publish } = createTilePublisher();
  let reached = false;
  source.subscribe(() => { throw new Error("consumer failure"); });
  source.subscribe(() => { reached = true; });
  publish(full());
  assert.equal(reached, true);
});

test("the publisher starts Unknown rather than empty", () => {
  // An empty initial view would let the shell show samples before first read.
  const { source } = createTilePublisher();
  const view = source.read();
  for (const tab of tabs) assert.ok(view[tab].length > 0, tab);
  assert.equal(view.egpu.every((tile) => tile.value === "Unknown"), true);
});

test("the source holds no timer and fetches nothing", () => {
  // The panel owns polling; a second source of truth is the failure mode here.
  const text = readFileSync(new URL("../src/quick-access/expanded-command-center/tile-source.ts", import.meta.url), "utf8");
  assert.doesNotMatch(text, /setInterval|setTimeout|requestAnimationFrame/);
  assert.doesNotMatch(text, /from "\.\.\/\.\.\/backend"|@decky\/api/);
});
