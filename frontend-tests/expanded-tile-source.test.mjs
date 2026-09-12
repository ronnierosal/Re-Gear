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
      // Safe Disconnect is the deliberate exception: it keeps its warning tone
      // when unobserved, because unknown readiness is a reason not to act
      // rather than an absence of the warning. Covered in its own test below.
      assert.equal(tile.tone, tile.id === "disconnect" ? "warning" : "unavailable",
        `${tab}/${tile.id}`);
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

// -------------------------------------- findings raised in reciprocal review

test("Safe Disconnect keeps its wide card on Quick Access, readings or not", () => {
  // Dropping it when readings are missing removes the control a player reaches
  // for when something has gone wrong, at the moment it went wrong.
  for (const readings of [full(), { fresh: false }]) {
    const disconnect = buildTiles(readings).quick.find((tile) => tile.id === "disconnect");
    assert.ok(disconnect, "Quick Access lost its Safe Disconnect card");
    assert.equal(disconnect.wide, true, "the approved wide slot must survive");
  }
});

test("an unobserved Safe Disconnect keeps its warning tone and refuses clearance", () => {
  // Unknown readiness is a reason not to act, never an absence of the warning.
  for (const tab of ["quick", "egpu"]) {
    const tile = buildTiles({ fresh: false })[tab].find((item) => item.id === "disconnect");
    assert.equal(tile.tone, "warning", `${tab} lost the warning tone`);
    assert.equal(tile.wide, true, `${tab} lost the wide slot`);
    assert.match(tile.detail, /cannot confirm a safe disconnect/i);
    assert.match(tile.detail, /never makes unplugging safe/i);
  }
});

test("display target is an observation of output, not of attachment", () => {
  // A connected but inactive television must not read as the current target.
  const attachedNotDriven = buildTiles({
    ...full(), displayTarget: { text: "Handheld", known: true, verified: true },
  }).quick.find((tile) => tile.id === "display");
  assert.equal(attachedNotDriven.value, "Handheld");
  const external = buildTiles({
    ...full(), displayTarget: { text: "External", known: true, verified: true },
  }).quick.find((tile) => tile.id === "display");
  assert.equal(external.value, "External");
  // And it is not the eGPU tab's attachment card wearing a different title.
  const attachment = buildTiles(full()).egpu.find((tile) => tile.id === "display");
  assert.equal(attachment.value, "Connected", "the eGPU card still reports attachment");
});

test("a verified display target reads as fact; an observed one says it is not", () => {
  // Same reading, two grades. "active" is the tone a player reads as "this is
  // true right now", and only a verified observation has earned it -- the eGPU
  // tab already says "observed, not verified" for this same field.
  const verified = buildTiles({
    ...full(), displayTarget: { text: "External", known: true, verified: true },
  }).quick.find((tile) => tile.id === "display");
  assert.equal(verified.tone, "active");
  assert.equal(verified.detail, "The panel currently being driven.");

  const observed = buildTiles({
    ...full(), displayTarget: { text: "External", known: true, verified: false },
  }).quick.find((tile) => tile.id === "display");
  assert.equal(observed.value, "External", "the panel is still named");
  assert.equal(observed.tone, "quiet", "an ungraded reading must not render as active");
  assert.match(observed.detail, /observed, not verified/);
});

test("mirrored output survives into the tile rather than being reduced to one panel", () => {
  const tile = buildTiles({
    ...full(), displayTarget: { text: "External + handheld", known: true, verified: true },
  }).quick.find((item) => item.id === "display");
  assert.equal(tile.value, "External + handheld");
  assert.equal(tile.tone, "active");
});

test("an unobserved display target is Unknown, never inferred from attachment", () => {
  const tile = buildTiles({ ...full(), displayTarget: undefined })
    .quick.find((item) => item.id === "display");
  assert.equal(tile.value, "Unknown");
  assert.equal(tile.tone, "unavailable");
});

test("omitted freshness fails closed rather than accepting the payload", () => {
  // Absent is not a yes. The owner performs the age check; anything short of an
  // explicit true has to read as unobserved here.
  const omitted = buildTiles({ egpu: full().egpu, controller: full().controller,
    performance: full().performance, manualWatts: 15 });
  assert.equal(omitted.egpu.every((tile) => tile.value === "Unknown" || tile.id === "disconnect"), true);
  const explicit = buildTiles(full());
  assert.notEqual(explicit.egpu[0].value, "Unknown");
});

// ------------------------------------------------------------ observation age

test("a recently received but long-observed reading is not fresh", () => {
  // The reproduction from reciprocal review: response receipt is not freshness.
  // A reply can arrive instantly carrying a reading taken minutes ago.
  const now = Date.UTC(2026, 8, 10, 12, 0, 0);
  const fiveMinutesOld = new Date(now - 300_000).toISOString();
  assert.equal(m.observationAge(fiveMinutesOld, now, 10_000).fresh, false);
});

test("an observation inside its lifetime is fresh and reports what is left", () => {
  const now = Date.UTC(2026, 8, 10, 12, 0, 0);
  const threeSecondsOld = new Date(now - 3_000).toISOString();
  const age = m.observationAge(threeSecondsOld, now, 10_000);
  assert.equal(age.fresh, true);
  assert.equal(age.remainingMs, 7_000, "the re-check must be the remaining lifetime");
});

test("the boundary is exclusive, so an expired observation is never fresh", () => {
  const now = Date.UTC(2026, 8, 10, 12, 0, 0);
  const exactlyExpired = new Date(now - 10_000).toISOString();
  assert.equal(m.observationAge(exactlyExpired, now, 10_000).fresh, false);
});

test("a future observation is refused rather than trusted", () => {
  // Disagreeing clocks are not a reason to trust a reading more than a stale one.
  const now = Date.UTC(2026, 8, 10, 12, 0, 0);
  const future = new Date(now + 60_000).toISOString();
  assert.equal(m.observationAge(future, now, 10_000).fresh, false);
});

test("an unparseable, empty or missing timestamp is not evidence of recency", () => {
  const now = Date.UTC(2026, 8, 10, 12, 0, 0);
  for (const value of ["not-a-date", "", undefined, null]) {
    const age = m.observationAge(value, now, 10_000);
    assert.equal(age.fresh, false, String(value));
    assert.equal(age.remainingMs, 0, String(value));
  }
});

test("a stale observation reports no remaining lifetime to schedule against", () => {
  const now = Date.UTC(2026, 8, 10, 12, 0, 0);
  assert.equal(m.observationAge(new Date(now - 60_000).toISOString(), now, 10_000).remainingMs, 0);
});
