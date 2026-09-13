import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/quick-access/expanded-command-center/model.ts", import.meta.url), "utf8");
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
