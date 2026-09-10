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
  assert.deepEqual([640, 639, 430, 429, 280, 279].map(m.columnsForWidth), [4, 3, 3, 2, 2, 1]);
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
    const useSyncExternalStore=(_subscribe,read)=>read();
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

test("native shortcut dropdown preserves selection and active chord when saving fails", async () => {
  const nativeSource = readFileSync(new URL("../src/quick-access/expanded-command-center/native.tsx", import.meta.url), "utf8");
  const nativeJs = ts.transpileModule(nativeSource, { compilerOptions: { module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.React } }).outputText.replace(/^import .*;$/gm, "");
  const fixture = `
    export const views=[], saved=[];
    export let resets=0, stops=0;
    const componentStates=new WeakMap();
    let states=[],cursor=0, fail=false, deps;
    const React={createElement:(type,props,...children)=>({type,props:{...props,children}})};
    const ModalRoot='modal',ExpandedCommandCenter='shell',Button='button',Focusable='focus',Dropdown='native-dropdown',ShortcutSettings='settings';
    const useEffect=()=>{},useState=v=>{const ownStates=states,i=cursor++;if(!(i in ownStates))ownStates[i]=v;return [ownStates[i],n=>ownStates[i]=n]};
    // Snapshot-only stub for this preference test. Subscription/liveness is
    // exercised by the producer/consumer tests, not by sharing hook arrays.
    const useSyncExternalStore=(_subscribe,read)=>read();
    const loadMenuBinding=()=> 'view-y',saveMenuBinding=value=>{saved.push(value);return !fail};
    const menuBindingOptions=[{label:'View / Back + Y',data:'view-y'},{label:'L3 + R3',data:'sticks'},{label:'Disabled',data:'disabled'}];
    const startMenuShortcut=d=>{deps=d;return {available:true,reset(){resets++},stop(){stops++}}};
    const showModal=view=>{views.push(view);return {Close(){}}};
    export const currentBinding=()=>deps.readBinding(),failSave=value=>{fail=value},render=component=>{
      cursor=0;states=componentStates.get(component)??[];
      componentStates.set(component,states);return component();
    };
  `;
  const native = await import(`data:text/javascript;base64,${Buffer.from(fixture + nativeJs).toString("base64")}`);
  const runtime = native.createExpandedMenu(undefined, {localStorage:{}});
  runtime.open();
  const view = native.views[0].props.children[1];
  const settings = native.render(() => view.type(view.props)).props.settings.type;
  let rendered = native.render(settings);
  assert.equal(rendered.props.control.type, "native-dropdown");
  assert.equal(rendered.props.control.props.selectedOption, "view-y");
  rendered.props.control.props.onChange({data:"unrecognized"});
  assert.equal(native.saved.length, 0);
  native.failSave(true);
  rendered.props.control.props.onChange({data:"sticks"});
  rendered = native.render(settings);
  assert.equal(rendered.props.control.props.selectedOption, "view-y");
  assert.equal(native.currentBinding(), "view-y");
  assert.match(rendered.props.error, /previous choice remains active/);
  assert.equal(native.resets, 0);
  native.failSave(false);
  rendered.props.control.props.onChange({data:"disabled"});
  rendered = native.render(settings);
  assert.equal(rendered.props.control.props.selectedOption, "disabled");
  assert.equal(native.currentBinding(), "disabled");
  assert.equal(rendered.props.error, "");
  assert.equal(native.resets, 1);
  runtime.stop();
  assert.equal(native.stops, 1);
});

test("native live source publishes into an open menu and unsubscribes on close", {
  // The UI branch can land independently; once the bridge module is present,
  // its consumer must satisfy this contract in the combined CI tree.
  skip: !existsSync(new URL("../src/quick-access/expanded-command-center/tile-source.ts", import.meta.url)),
}, async () => {
  const body=readFileSync(new URL("../src/quick-access/expanded-command-center/native.tsx", import.meta.url),"utf8");
  const compiled=ts.transpileModule(body,{compilerOptions:{module:ts.ModuleKind.ESNext,jsx:ts.JsxEmit.React}}).outputText.replace(/^import .*;$/gm, "");
  const fixture=`
    export const views=[],listeners=new Set();
    export let current;
    let unsubscribe,renderView;
    let snapshot={quick:[{id:'auto',title:'Auto TDP',value:'Running',detail:'Fixture'}],performance:[],egpu:[],controllers:[],settings:[]};
    const React={createElement:(type,props,...children)=>({type,props:{...props,children}})};
    const ModalRoot='modal',ExpandedCommandCenter='shell',Button='button',Focusable='focus',Dropdown='dropdown',ShortcutSettings='settings';
    const useState=v=>[v,()=>{}],useEffect=()=>{};
    const useSyncExternalStore=(subscribe,read)=>{
      if(!unsubscribe)unsubscribe=subscribe(()=>{current=renderView();});
      return read();
    };
    const loadMenuBinding=()=> 'view-y',saveMenuBinding=()=>true,menuBindingOptions=[];
    const startMenuShortcut=()=>({available:true,reset(){},stop(){}});
    const showModal=view=>{views.push(view);return {Close(){unsubscribe?.();unsubscribe=undefined;}}};
    export const source={read:()=>snapshot,subscribe(fn){listeners.add(fn);return()=>listeners.delete(fn);}};
    export function mount(){const view=views.at(-1).props.children[1];renderView=()=>view.type(view.props);current=renderView();}
    export function publish(){snapshot={...snapshot,quick:[{id:'auto',title:'Auto TDP',value:'Unknown',detail:'Expired'}]};for(const listener of listeners)listener();}
  `;
  const native=await import(`data:text/javascript;base64,${Buffer.from(fixture+compiled).toString("base64")}`);
  const menu=native.createExpandedMenu(undefined,{localStorage:{}},()=>true,native.source);
  menu.open();native.mount();
  assert.equal(native.current.props.tiles.quick[0].value,"Running");
  assert.equal(native.listeners.size,1,"opening must subscribe to the existing publisher");
  native.publish();
  assert.equal(native.current.props.tiles.quick[0].value,"Unknown","an open menu must update without reopening");
  native.current.props.onClose();
  assert.equal(native.listeners.size,0);
  menu.open();native.mount();
  assert.equal(native.listeners.size,1,"reopen installs one fresh subscription");
  menu.stop();
  assert.equal(native.listeners.size,0);
});
