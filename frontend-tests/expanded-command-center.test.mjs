import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import ts from "typescript";

const source = readFileSync(new URL("../src/quick-access/expanded-command-center/model.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const m = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);

test("bumper tab cycle wraps in both directions", () => {
  assert.equal(m.nextTab("quick", -1), "settings");
  assert.equal(m.nextTab("settings", 1), "quick");
  let tab = "quick";
  for (let i = 0; i < 5; i++) tab = m.nextTab(tab, 1);
  assert.equal(tab, "quick");
});
test("focus restoration retains unavailable FPS and falls back after removal", () => {
  const ids = m.sampleTiles.quick.map(tile => tile.id);
  assert.equal(m.restoreTarget(ids, "fps"), "fps");
  assert.equal(m.restoreTarget(ids, "removed"), "fps");
  assert.equal(m.restoreTarget([], "fps"), undefined);
});
test("responsive grid preserves readable fallback and four-to-three boundary", () => {
  assert.deepEqual([700, 620, 619, 430, 429, 249].map(m.columnsForWidth), [4, 4, 3, 3, 2, 1]);
});
test("four-column navigation respects the spanning disconnect tile", () => {
  const cells = m.gridCells(m.sampleTiles.quick, 4);
  assert.equal(m.moveInGrid(cells, "display", "down"), "disconnect");
  assert.equal(m.moveInGrid(cells, "auto", "down"), "disconnect");
  assert.equal(m.moveInGrid(cells, "disconnect", "left"), "controller");
  assert.equal(m.moveInGrid(cells, "disconnect", "right"), "disconnect");
});
test("three-column packing does not navigate through an empty grid cell", () => {
  const cells = m.gridCells(m.sampleTiles.quick, 3);
  assert.equal(cells.at(-1).row, 2);
  assert.equal(m.moveInGrid(cells, "controller", "down"), "disconnect");
  assert.equal(m.moveInGrid(cells, "disconnect", "up"), "display");
});
test("every tile is reachable by arrows in every responsive grid", () => {
  for (const tiles of Object.values(m.sampleTiles)) for (const columns of [1, 2, 3, 4]) {
    const cells = m.gridCells(tiles, columns), visited = new Set([tiles[0].id]);
    for (const id of visited) for (const direction of ["left", "right", "up", "down"]) visited.add(m.moveInGrid(cells, id, direction));
    assert.equal(visited.size, tiles.length);
  }
});
test("production import graph cannot reach synthetic prototype", () => {
  const visited = new Set();
  function visit(file) {
    if (visited.has(file)) return;
    visited.add(file);
    assert.ok(!file.includes("expanded-command-center"), `Production imports sample prototype: ${file}`);
    const body = readFileSync(file, "utf8");
    for (const match of body.matchAll(/(?:from\s*|import\s*\(\s*|import\s*)["'](\.[^"']+)["']/g)) {
      const base = resolve(dirname(file), match[1]);
      const next = [base, `${base}.ts`, `${base}.tsx`, resolve(base, "index.ts"), resolve(base, "index.tsx")].find(path => /\.tsx?$/.test(path) && existsSync(path));
      if (next) visit(next);
    }
  }
  visit(new URL("../src/index.tsx", import.meta.url).pathname.replace(/^\/(\w:)/, "$1"));
});
