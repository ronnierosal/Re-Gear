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
test("responsive grid prefers four columns with three before narrow fallback", () => {
  assert.deepEqual([600, 599, 420, 419, 280, 279].map(m.columnsForWidth), [4, 3, 3, 2, 2, 1]);
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
  assert.equal(cells.at(-1).span, 3);
});
test("every tile is reachable by arrows in every responsive grid", () => {
  for (const tiles of Object.values(m.sampleTiles)) for (const columns of [1, 2, 3, 4]) {
    const cells = m.gridCells(tiles, columns), visited = new Set([tiles[0].id]);
    for (const id of visited) for (const direction of ["left", "right", "up", "down"]) visited.add(m.moveInGrid(cells, id, direction));
    assert.equal(visited.size, tiles.length);
  }
});
test("demo rendering import graph cannot reach backend or native runtime", () => {
  const visited = new Set();
  function visit(file) {
    if (visited.has(file)) return;
    visited.add(file);
    assert.ok(!file.endsWith("backend.ts") && !file.endsWith("native.tsx"), `Demo rendering imports action runtime: ${file}`);
    const body = readFileSync(file, "utf8");
    assert.ok(!body.includes('from "@decky/api"'), "Demo renderer must not import RPCs");
    for (const match of body.matchAll(/(?:from\s*|import\s*\(\s*|import\s*)["'](\.[^"']+)["']/g)) {
      const base = resolve(dirname(file), match[1]);
      const next = [base, `${base}.ts`, `${base}.tsx`, resolve(base, "index.ts"), resolve(base, "index.tsx")].find(path => /\.tsx?$/.test(path) && existsSync(path));
      if (next) visit(next);
    }
  }
  visit(new URL("../src/quick-access/expanded-command-center/shell.tsx", import.meta.url).pathname.replace(/^\/(\w:)/, "$1"));
});

test("native modal uses Decky controls without a second raw navigation listener", async () => {
  const nativeSource = readFileSync(new URL("../src/quick-access/expanded-command-center/native.tsx", import.meta.url), "utf8");
  const nativeJs = ts.transpileModule(nativeSource, { compilerOptions: { module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.React } }).outputText.replace(/^import .*;$/gm, "");
  const fixtures = `
    export const views=[], effects=[], listeners=[];
    export let opens=0, clicks=0;
    const React={createElement:(type,props,...children)=>({type,props:{...props,children}})};
    const ModalRoot='modal', ExpandedCommandCenter='shell',Button='native-button',Focusable='native-focus';
    const useEffect=fn=>effects.push(fn()), useState=v=>[v,()=>{}];
    const loadMenuBinding=()=> 'start-select',saveMenuBinding=()=>true,menuBindingOptions=[];
    const startMenuShortcut=()=>({available:true,reset(){},stop(){}});
    const showModal=view=>{opens++;views.push(view);return {Close(){}}};
    export const input={RegisterForControllerInputMessages(fn){listeners.push(fn);return {unregister(){throw Error('late provider')}}}};
    export const host={localStorage:{},document:{querySelector(){return {contains(){return true}}},activeElement:{tagName:'BUTTON',click(){clicks++}}}};
  `;
  const native = await import(`data:text/javascript;base64,${Buffer.from(fixtures + nativeJs).toString("base64")}`);
  const runtime = native.createExpandedMenu(native.input, native.host);
  runtime.open(); runtime.open(); assert.equal(native.opens, 1);
  const view = native.views[0].props.children[1];
  const shell = view.type(view.props); // Mount its cleanup and obtain close callback.
  assert.equal(shell.props.primitives.Button, 'native-button');
  assert.equal(shell.props.primitives.Focusable, 'native-focus');
  assert.equal(native.listeners.length, 0, 'Only the launcher may subscribe to raw input');
  shell.props.onClose(); runtime.open(); assert.equal(native.opens, 2);
  native.effects[0](); // Old animated unmount arrives after reopening.
  runtime.open(); assert.equal(native.opens, 2, "old unmount must not clear new modal");
  runtime.stop(); runtime.open(); assert.equal(native.opens, 2, "unload must prevent opening");
});
