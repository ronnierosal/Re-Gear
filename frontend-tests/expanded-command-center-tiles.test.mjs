import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(
  new URL("../src/quick-access/expanded-command-center/tiles.ts", import.meta.url),
  "utf8",
);
const js = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext },
}).outputText;
const m = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);

const unknown = { text: "Unknown", known: false, verified: false };
const observed = (text) => ({ text, known: true, verified: false });
const verified = (text) => ({ text, known: true, verified: true });

/** Everything absent: the shape a snapshot takes before anything is observed. */
const blank = {
  connection: unknown,
  renderGpu: unknown,
  displayConnected: unknown,
  displayActive: unknown,
  session: unknown,
  game: unknown,
  model: null,
  lifecycle: unknown,
  disconnect: {
    text: "Readiness check required",
    safeClaim: false,
    reason: "Re-Gear cannot confirm live removal.",
  },
  recovery: { reachable: true, note: null },
};

const byId = (tiles) => Object.fromEntries(tiles.map((tile) => [tile.id, tile]));

test("an absent reading is unavailable and says Unknown, never blank", () => {
  const tiles = byId(m.egpuTiles(blank));

  for (const id of ["link", "render", "display"]) {
    assert.equal(tiles[id].tone, "unavailable", id);
    assert.equal(tiles[id].value, "Unknown", id);
    assert.match(tiles[id].detail, /no observation available/, id);
    // A tile that renders nothing looks like one that is still loading.
    assert.notEqual(tiles[id].value, "");
  }
  // The approved composition also carries two cards with no provider at all.
  // They are stated, not omitted, and never blank.
  for (const id of ["device", "dock"]) {
    assert.equal(tiles[id].tone, "unavailable", id);
    assert.match(tiles[id].value, /unknown|not available/i, id);
    assert.notEqual(tiles[id].detail, "", id);
  }
});

test("observed is not verified: an ungraded reading is never the active tone", () => {
  const tiles = byId(
    m.egpuTiles({ ...blank, connection: observed("Link up"), renderGpu: verified("External GPU") }),
  );

  assert.equal(tiles.link.tone, "quiet");
  assert.match(tiles.link.detail, /observed, not verified/);
  assert.equal(tiles.render.tone, "active");
  assert.doesNotMatch(tiles.render.detail, /not verified/);
});

test("evidenceTone maps the three grades and nothing else", () => {
  assert.equal(m.evidenceTone(unknown), "unavailable");
  assert.equal(m.evidenceTone(observed("x")), "quiet");
  assert.equal(m.evidenceTone(verified("x")), "active");
});

test("attachment and output stay separate facts on the display tile", () => {
  // A connected display is not a display that is driving anything.
  const tiles = byId(
    m.egpuTiles({
      ...blank,
      displayConnected: verified("Connected"),
      displayActive: verified("Not active"),
    }),
  );

  assert.equal(tiles.display.value, "Connected");
  assert.match(tiles.display.detail, /Output: Not active/);
});

test("the model name is detail only and never becomes the reading", () => {
  const tiles = byId(
    m.egpuTiles({ ...blank, connection: verified("Link up"), model: "RX 7600M XT" }),
  );

  assert.equal(tiles.link.value, "Link up");
  // The approved composition adds a "Detected device" card, which is exactly
  // the place a model name would get promoted into an identity. The payload
  // documents it as presentation only, so it stays in the detail there too and
  // the reading itself remains Unknown.
  assert.match(tiles.device.detail, /RX 7600M XT/);
  assert.notEqual(tiles.device.value, "RX 7600M XT");
  assert.equal(tiles.device.tone, "unavailable");
});

test("the disconnect detail keeps each carried reading's own grade", () => {
  // The approved eGPU composition has no game or session card, so both are
  // carried in the Safe Disconnect detail. Carrying the raw text instead of the
  // graded line makes an unverified observation read as a confirmed one -- on
  // the single card a player consults before touching hardware.
  const graded = (game, session) => byId(m.egpuTiles({ ...blank, game, session })).disconnect.detail;

  const sameText = "No game running";
  assert.notEqual(
    graded(verified(sameText), verified("Running")),
    graded(observed(sameText), verified("Running")),
    "identical text with different verification must not render identically",
  );
  assert.match(graded(observed(sameText), verified("Running")), /observed, not verified/);
  assert.doesNotMatch(graded(verified(sameText), verified("Running")), /observed, not verified/);

  // The session reading is graded independently of the game reading.
  assert.match(graded(verified(sameText), observed("Running")), /observed, not verified/);
  assert.match(graded(unknown, verified("Running")), /no observation available/);

  // And the refusal itself is still there, ahead of both.
  assert.match(graded(verified(sameText), verified("Running")), /cannot confirm live removal/i);
});

test("Safe Disconnect is always warning and never claims a cable may be pulled", () => {
  const readings = [
    blank,
    { ...blank, connection: verified("Link down"), renderGpu: verified("Internal GPU") },
    {
      ...blank,
      connection: verified("Link up"),
      renderGpu: verified("External GPU"),
      displayConnected: verified("Connected"),
      displayActive: verified("Active"),
      game: verified("Idle"),
    },
  ];

  for (const presentation of readings) {
    const tile = byId(m.egpuTiles(presentation)).disconnect;

    assert.equal(tile.tone, "warning");
    assert.equal(tile.wide, true);
    // Text comes from the presentation's own refusal, which types safeClaim as
    // the literal false. No combination of readings can talk it into a claim.
    assert.equal(tile.value, presentation.disconnect.text);
    for (const wording of [/safe to (unplug|remove|disconnect)/i, /you can now/i, /cable is safe/i]) {
      assert.doesNotMatch(`${tile.value} ${tile.detail}`, wording);
    }
  }
});

test("every tile carries an id the shell already knows how to focus", () => {
  // The shell maps ids to icons and remembers focus by id; an unknown id
  // silently loses both.
  const ids = m.egpuTiles(blank).map((tile) => tile.id);

  // Approved identity, docs/design/command-center-runtime-handoff.md.
  assert.deepEqual(ids, ["device", "dock", "display", "render", "link", "disconnect"]);
});

const perfState = (over = {}) => ({
  active: false, autoKnown: true, stopping: false, supported: true,
  configuredWatts: 18, configuredIsLimit: true, action: "open", reason: null,
  busy: false, ...over,
});
const fps = { available: false, value: { text: "Unavailable", known: false },
  reason: "No verified frame-rate provider on this device." };
const perf = (over = {}, manual = { text: "18 W", known: true }) =>
  byId(m.performanceTiles({ state: perfState(over), manualWatts: manual, fps }));

test("the FPS tile is always present and always unavailable", () => {
  // fpsTile's own reason: a grid whose shape depends on live evidence moves a
  // target under a player's thumb.
  for (const over of [{}, { active: true }, { autoKnown: false }, { supported: false }]) {
    const tiles = perf(over);
    assert.equal(tiles.fps.tone, "unavailable");
    assert.equal(tiles.fps.value, "Unavailable");
    assert.match(tiles.fps.detail, /No verified frame-rate provider/);
  }
});

test("an unreadable TDP limit stays unknown and never becomes a number", () => {
  const tiles = perf({}, { text: "Unknown", known: false });

  assert.equal(tiles.manual.value, "Unknown");
  assert.equal(tiles.manual.tone, "unavailable");
  assert.doesNotMatch(tiles.manual.value, /\d/);
});

test("Auto TDP distinguishes unknown from off, running and stopping", () => {
  assert.equal(perf({ autoKnown: false }).auto.value, "Unknown");
  assert.equal(perf({ autoKnown: false }).auto.tone, "unavailable");
  assert.equal(perf().auto.value, "Off");
  assert.equal(perf({ active: true }).auto.value, "Running");
  assert.equal(perf({ active: true, stopping: true }).auto.value, "Stopping…");
  // Stopping is in flight, not a working state.
  assert.notEqual(perf({ active: true, stopping: true }).auto.tone, "active");
});

test("Auto TDP shows the reason the state machine already produced", () => {
  const tiles = perf({ supported: false, reason: "This device has no verified TDP control." });

  assert.match(tiles.auto.detail, /no verified TDP control/);
});

const controller = (over = {}) => ({
  available: true, reason: null,
  builtin: { text: "Off", known: true },
  external: { text: "Player 1", known: true },
  precision: "exact", precisionNote: null,
  shortcut: { text: "Available", known: true },
  planned: ["Player order", "Shortcut customization", "Priority handoff"],
  ...over,
});

test("controller tone follows the payload's precision, not just presence", () => {
  const exact = byId(m.controllerTiles(controller()));
  assert.equal(exact.builtin.tone, "active");
  // Player 1 never takes a tone from controller presence, at any precision:
  // presence is not player order, and player order has no provider.
  assert.equal(exact.controller.tone, "unavailable");

  // A partial reading is known but not exact; it must not use the tone a
  // player reads as "this is true right now".
  const partial = byId(m.controllerTiles(controller({
    precision: "partial", precisionNote: "Only one source reported",
  })));
  // The approved "controller" card is Player 1, which has no provider, so the
  // precision-driven tone now belongs to the built-in reading. The precision
  // note still reaches the Player 1 card's detail.
  assert.equal(partial.builtin.tone, "quiet");
  assert.match(partial.controller.detail, /Only one source reported/);

  const none = byId(m.controllerTiles(controller({ precision: "unknown" })));
  assert.equal(none.builtin.tone, "unavailable");
});

test("no controller reading shows the reason rather than a blank tile", () => {
  const tiles = byId(m.controllerTiles(controller({
    available: false, reason: "Peripheral status unavailable.",
    builtin: { text: "Unknown", known: false },
    external: { text: "Unknown", known: false },
    precision: "unknown",
  })));

  assert.match(tiles.controller.value, /unknown|not available/i);
  assert.match(tiles.controller.detail, /Peripheral status unavailable/);
  assert.equal(tiles.builtin.tone, "unavailable");
});

test("controller priority is never rendered as a working control", () => {
  for (const precision of ["exact", "partial", "unknown"]) {
    const tiles = byId(m.controllerTiles(controller({ precision })));

    assert.equal(tiles.priority.tone, "unavailable");
    assert.equal(tiles.priority.value, "Not available");
    assert.match(tiles.priority.detail, /Planned, not implemented/);
  }
});

test("the new tabs use ids the shell already knows how to focus", () => {
  // Approved identity, docs/design/command-center-runtime-handoff.md.
  assert.deepEqual(m.performanceTiles({
    state: perfState(), manualWatts: { text: "18 W", known: true }, fps,
  }).map(t => t.id), ["profile", "fps", "manual", "auto", "display", "refresh"]);
  assert.deepEqual(m.controllerTiles(controller()).map(t => t.id),
    ["controller", "battery", "builtin", "priority", "tv-controller", "controller-settings"]);
});
