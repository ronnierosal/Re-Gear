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

  for (const id of ["egpu", "render", "display", "game"]) {
    assert.equal(tiles[id].tone, "unavailable", id);
    assert.equal(tiles[id].value, "Unknown", id);
    assert.match(tiles[id].detail, /no observation available/, id);
    // A tile that renders nothing looks like one that is still loading.
    assert.notEqual(tiles[id].value, "");
  }
});

test("observed is not verified: an ungraded reading is never the active tone", () => {
  const tiles = byId(
    m.egpuTiles({ ...blank, connection: observed("Link up"), game: verified("Idle") }),
  );

  assert.equal(tiles.egpu.tone, "quiet");
  assert.match(tiles.egpu.detail, /observed, not verified/);
  assert.equal(tiles.game.tone, "active");
  assert.doesNotMatch(tiles.game.detail, /not verified/);
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

  assert.equal(tiles.egpu.value, "Link up");
  assert.match(tiles.egpu.detail, /RX 7600M XT/);
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

  assert.deepEqual(ids, ["egpu", "render", "display", "game", "disconnect"]);
});
