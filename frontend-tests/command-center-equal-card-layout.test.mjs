import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/quick-access/expanded-command-center/model.ts", import.meta.url), "utf8");
const actions = readFileSync(new URL("../src/quick-access/expanded-command-center/egpu-actions-ui.tsx", import.meta.url), "utf8");
const popup = readFileSync(new URL("../src/quick-access/expanded-command-center/popup-ui.tsx", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2022 } }).outputText;
const { sampleTiles, gridCells } = await import("data:text/javascript;base64," + Buffer.from(js).toString("base64"));

test("approved quick and eGPU cards never request a two-cell span", () => {
  for (const tab of ["quick", "egpu"]) {
    assert.ok(sampleTiles[tab].every(tile => tile.wide !== true));
    assert.ok(gridCells(sampleTiles[tab], 4).every(cell => cell.span === 1));
  }
});

test("four-column layout preserves one-card-per-cell rhythm", () => {
  const cells = gridCells(sampleTiles.quick.slice(0, 4), 4);
  assert.deepEqual(cells.map(({row,column,span}) => ({row,column,span})), [
    {row:0,column:0,span:1},
    {row:0,column:1,span:1},
    {row:0,column:2,span:1},
    {row:0,column:3,span:1},
  ]);
});

test("eGPU action cards stay equal-width and prefer four columns", () => {
  assert.match(actions, /grid-template-columns:repeat\(4,minmax\(0,1fr\)\)/);
  assert.match(actions, /data-egpu-action-card/);
  assert.doesNotMatch(actions, /gridColumn/);
  assert.doesNotMatch(actions, /span 2/);
});

test("eGPU action grid adapts instead of overflowing small screens", () => {
  assert.match(actions, /@container \(max-width:520px\)/);
  assert.match(actions, /repeat\(2,minmax\(0,1fr\)\)/);
  assert.match(actions, /@container \(max-width:300px\)/);
  assert.match(actions, /grid-template-columns:1fr/);
});

test("popups remain centered and footer actions wrap on compact screens", () => {
  assert.match(popup, /placeItems: "center"/);
  assert.match(popup, /data-regear-popup-footer/);
  assert.match(popup, /flex-wrap:wrap/);
  assert.match(popup, /@media\(max-width:430px\)/);
  assert.match(popup, /flex:1 1 100%/);
});
