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
  "quick-access/expanded-command-center/offline-tab",
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
  performance: performanceState(), manualWatts: 15, fresh: true, performanceFresh: true,
  controllerFresh: true,
});

// ------------------------------------------- freshness is per source, not shared

const perfTiles = (readings) => buildTiles(readings).performance;
const perfValues = (readings) => perfTiles(readings).map((tile) => tile.value);

test("Quick reports observed presence while Controllers keeps Player 1 unknown", () => {
  // Presence IS observed; player order is not. Quick's approved card is
  // Controller Status, so dropping a truthful presence reading because a
  // different question is unanswerable would be its own kind of dishonesty.
  const view = buildTiles(full());
  const quick = view.quick.find((tile) => tile.id === "controller");
  const assignment = view.controllers.find((tile) => tile.id === "controller");

  assert.equal(quick.title, "Controller Status");
  assert.notEqual(quick.value, "Unknown", "presence was observed and must be reported");
  assert.match(quick.detail, /player order not established/i,
    "the summary must not imply it answers the assignment question");

  assert.equal(assignment.title, "Player 1");
  assert.match(assignment.value, /unknown|not available/i);
  assert.equal(assignment.tone, "unavailable");
});

test("the Quick summary grades by precision, never by presence alone", () => {
  const withPrecision = (precision, precisionNote = null) => buildTiles({
    ...full(),
    controller: { ...full().controller, precision, precisionNote },
  }).quick.find((tile) => tile.id === "controller");

  assert.equal(withPrecision("exact").tone, "active");
  // Known, but not exact: it may not wear the tone a player reads as
  // "this is true right now".
  const partial = withPrecision("partial", "Only one source reported");
  assert.equal(partial.tone, "quiet");
  assert.match(partial.detail, /Only one source reported/);
  assert.equal(withPrecision("unknown").tone, "unavailable");
});

test("an unread controller source leaves Quick unknown rather than guessing", () => {
  const quick = buildTiles({ ...full(), controllerFresh: false })
    .quick.find((tile) => tile.id === "controller");
  assert.equal(quick.value, "Unknown");
  assert.equal(quick.tone, "unavailable");
});

test("controller evidence is gated by its own reading, not the snapshot", () => {
  // Peripheral status arrives over a different transport and carries no
  // observation timestamp at all, so the snapshot's age says nothing about it
  // in either direction.
  const noReading = { ...full(), controllerFresh: false };
  assert.equal(noReading.fresh, true, "the snapshot is still fresh in this case");
  for (const tile of buildTiles(noReading).controllers) assert.equal(tile.value, "Unknown");

  const staleSnapshot = { ...full(), fresh: false, controllerFresh: true };
  assert.ok(buildTiles(staleSnapshot).controllers.some((tile) => tile.value !== "Unknown"),
    "a controller reading must not be blanked by an unrelated stale observation");
});

test("absent controller freshness fails closed, like the other two flags", () => {
  const { controllerFresh, ...omitted } = full();
  assert.equal(controllerFresh, true);
  for (const tile of buildTiles(omitted).controllers) assert.equal(tile.value, "Unknown");
});

test("an expired performance reading is Unknown even while the snapshot is fresh", () => {
  // The defect this pins: performance arrives over a different transport with
  // no observation timestamp, so grading it by the snapshot's age lets a power
  // limit that expired minutes ago render as the current limit, vouched for by
  // an unrelated GPU sample that happened to be recent.
  const expired = { ...full(), performanceFresh: false };
  assert.equal(expired.fresh, true, "the snapshot is still fresh in this case");
  for (const value of perfValues(expired)) assert.equal(value, "Unknown");
  // And the quick tab reads from the same gate.
  const quick = buildTiles(expired).quick;
  for (const id of ["manual", "auto", "fps"]) {
    assert.equal(quick.find((tile) => tile.id === id).value, "Unknown", id);
  }
});

test("a live performance reading survives a stale snapshot", () => {
  // The same independence in the other direction: the snapshot going stale
  // says nothing about a reading the performance owner still considers live.
  const staleSnapshot = { ...full(), fresh: false, performanceFresh: true };
  assert.ok(perfValues(staleSnapshot).some((value) => value !== "Unknown"),
    "performance must not be blanked by an unrelated stale observation");
  // while everything derived from that snapshot is Unknown.
  const egpu = buildTiles(staleSnapshot).egpu;
  for (const tile of egpu) {
    if (tile.id !== "disconnect") assert.equal(tile.value, "Unknown", tile.id);
  }
});

test("absent performance freshness fails closed, like the snapshot flag", () => {
  const { performanceFresh, ...omitted } = full();
  assert.equal(performanceFresh, true);
  for (const value of perfValues(omitted)) assert.equal(value, "Unknown");
});

test("neither freshness flag can stand in for the other", () => {
  // Four combinations, and only the matching source unlocks each tab.
  const egpuKnown = (readings) => buildTiles(readings).egpu
    .some((tile) => tile.id !== "disconnect" && tile.value !== "Unknown");
  const perfKnown = (readings) => perfValues(readings).some((value) => value !== "Unknown");
  for (const [fresh, performanceFresh] of [[true, true], [true, false], [false, true], [false, false]]) {
    const readings = { ...full(), fresh, performanceFresh };
    assert.equal(egpuKnown(readings), fresh, `egpu follows fresh=${fresh}`);
    assert.equal(perfKnown(readings), performanceFresh,
      `performance follows performanceFresh=${performanceFresh}`);
  }
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
    const view = buildTiles(readings);
    // Check what the tiles REPORT, not what the approved composition calls
    // them. "Player 1" is an approved card title whose value is "Not
    // available"; naming an absent capability is the opposite of inventing a
    // reading for it. Matching on titles would force the mapper to rename an
    // approved card to pass, which is the tail wagging the dog.
    const reported = Object.values(view).flat()
      .map((tile) => `${tile.value} ${tile.detail}`).join(" | ");
    assert.doesNotMatch(reported, /\bP1\b/i, "invented player order");
    assert.doesNotMatch(reported, /1080p|\d+\s*Hz/i, "invented resolution or refresh rate");
    assert.doesNotMatch(reported, /sample/i, "sample wording");
    // A model name may appear as detail, but never as a reading.
    for (const tile of Object.values(view).flat()) {
      assert.doesNotMatch(tile.value, /RX 7600M XT/i, `${tile.id} reports a model name`);
    }
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
  // Index 0 is now "device", which has no provider and reads Unknown even
  // when live. Assert against the card that does carry a reading.
  const live = buildTiles(full());
  assert.notEqual(live.egpu.find((tile) => tile.id === "link").value, "Unknown");
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
  // Quick calls it "egpu" and the eGPU tab calls it "link" -- two approved
  // identities for one reading. The values must still agree, or two tabs
  // would report different things about the same observation.
  const quickConnection = view.quick.find((tile) => tile.id === "egpu");
  const egpuConnection = view.egpu.find((tile) => tile.id === "link");
  assert.equal(quickConnection.value, egpuConnection.value);
});

test("settings states unsupported entries as unavailable rather than dropping them", () => {
  const settings = buildTiles(full()).settings;
  assert.ok(settings.length > 0);
  for (const tile of settings) assert.equal(tile.tone, "unavailable");
  // The approved composition carries a shortcut card, but the real control
  // is still the native adapter row. The card must say where the control is
  // rather than look like a second, dead one.
  const shortcut = settings.find((tile) => tile.id === "shortcut");
  assert.ok(shortcut, "the approved shortcut card is present");
  assert.equal(shortcut.tone, "unavailable");
  assert.match(shortcut.detail, /below|not from this card/i);
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

test("Safe Disconnect keeps its one-cell card on Quick Access, readings or not", () => {
  // Dropping it when readings are missing removes the control a player reaches
  // for when something has gone wrong, at the moment it went wrong.
  for (const readings of [full(), { fresh: false }]) {
    const disconnect = buildTiles(readings).quick.find((tile) => tile.id === "disconnect");
    assert.ok(disconnect, "Quick Access lost its Safe Disconnect card");
    assert.equal(disconnect.wide, false, "the approved one-cell slot must survive");
  }
});

test("an unobserved Safe Disconnect keeps its warning tone and refuses clearance", () => {
  // Unknown readiness is a reason not to act, never an absence of the warning.
  for (const tab of ["quick", "egpu"]) {
    const tile = buildTiles({ fresh: false })[tab].find((item) => item.id === "disconnect");
    assert.equal(tile.tone, "warning", `${tab} lost the warning tone`);
    assert.equal(tile.wide, false, `${tab} lost the one-cell slot`);
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
  assert.notEqual(explicit.egpu.find((tile) => tile.id === "link").value, "Unknown");
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
