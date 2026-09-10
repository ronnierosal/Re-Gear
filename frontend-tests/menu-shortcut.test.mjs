import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const js = ts.transpileModule(readFileSync(new URL("../src/menu-shortcut.ts", import.meta.url), "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { startMenuShortcut, loadMenuBinding, saveMenuBinding } = await import(
  "data:text/javascript;base64," + Buffer.from(js).toString("base64"));

function setup(t) {
  let event, list, current, binding = "view-y", opens = 0, removed = 0;
  const sub = () => ({ unregister() { removed++; } });
  const handle = startMenuShortcut({ input: {
    RegisterForControllerInputMessages(cb) { event = cb; return sub(); },
    RegisterForControllerListChanges(cb) { list = cb; return sub(); },
    RegisterForActiveControllerChanges(cb) { current = cb; return sub(); },
  }, readBinding: () => binding, open: () => opens++ });
  t.after(handle.stop);
  return { handle, send: (...args) => event(...args), list: () => list(), current: () => current(),
    binding(value) { binding = value; handle.reset(); }, opens: () => opens, removed: () => removed,
    chord(a = 9, b = 3, id = 0) { event(id, a, true); event(id, b, true); },
    release(a = 9, b = 3, id = 0) { event(id, a, false); event(id, b, false); } };
}

test("default View/Back + Y chord opens immediately in either press order", t => {
  const s = setup(t); assert.equal(s.handle.available, true);
  s.chord(); assert.equal(s.opens(), 1); s.release();
  s.chord(3, 9); assert.equal(s.opens(), 2);
});

test("different controllers, old shortcuts and alias substitutions never open", t => {
  const s = setup(t); s.send(0, 9, true); s.send(1, 3, true);
  assert.equal(s.opens(), 0);
  for (const pair of [[8, 9], [35, 36], [30, 31], [8, 3], [9, 2]]) {
    s.handle.reset(); s.chord(...pair); assert.equal(s.opens(), 0);
  }
});

test("repeated downs and partial releases cannot reopen before full release", t => {
  const s = setup(t); s.chord(); s.chord();
  s.send(0, 9, false); s.send(0, 9, true); assert.equal(s.opens(), 1);
  s.send(0, 2, true); s.release(); s.chord(); assert.equal(s.opens(), 1);
  s.release(); s.send(0, 2, false); s.chord(); assert.equal(s.opens(), 2);
});

test("extra held buttons block activation including release into an exact chord", t => {
  const s = setup(t); s.send(0, 2, true); s.chord(); s.send(0, 2, false);
  assert.equal(s.opens(), 0); s.release(); s.chord(); assert.equal(s.opens(), 1);
});

test("both controller notifications cancel partially accumulated input", t => {
  const s = setup(t);
  for (const change of [s.list, s.current, s.handle.reset]) {
    s.handle.reset(); s.send(0, 9, true); change(); s.send(0, 3, true);
    assert.equal(s.opens(), 0);
  }
});

test("settings reset, disabled mode and stick-click alternative", t => {
  const s = setup(t); s.send(0, 25, true); s.binding("sticks"); s.send(0, 41, true);
  assert.equal(s.opens(), 0); s.handle.reset(); s.chord(25, 41); assert.equal(s.opens(), 1);
  s.chord(25, 41); s.send(0, 25, false); s.send(0, 25, true); assert.equal(s.opens(), 1);
  s.release(25, 41); s.chord(41, 25); assert.equal(s.opens(), 2);
  s.handle.reset(); s.send(0, 25, true); s.send(1, 41, true); assert.equal(s.opens(), 2);
  s.handle.reset(); s.chord(); assert.equal(s.opens(), 2);
  s.binding("disabled"); s.chord(); s.handle.reset(); s.chord(25, 41); assert.equal(s.opens(), 2);
});

test("malformed input and controller capacity reset bounded accumulated state", t => {
  const s = setup(t);
  for (const args of [[-1, 8, true], [0, 256, true], [0, 9, 1], [NaN, 8, true]]) {
    s.handle.reset(); s.send(0, 9, true); s.send(...args); s.send(0, 3, true);
    assert.equal(s.opens(), 0);
  }
  s.handle.reset(); for (let id = 0; id < 9; id++) s.send(id, 9, true);
  s.send(0, 3, true); assert.equal(s.opens(), 0);
});

test("stop unregisters every subscription once and leaves delivered callbacks inert", t => {
  const s = setup(t); s.handle.stop(); s.handle.stop(); s.chord();
  assert.equal(s.opens(), 0); assert.equal(s.removed(), 3);
});

test("missing input provider or failed registration is unavailable and cleans up", () => {
  assert.equal(startMenuShortcut({ readBinding: () => "view-y", open() {} }).available, false);
  let removed = 0;
  const handle = startMenuShortcut({ input: {
    RegisterForControllerListChanges() { return { unregister() { removed++; } }; },
    RegisterForControllerInputMessages() { throw Error("unavailable"); },
  }, readBinding: () => "view-y", open() {} });
  assert.equal(handle.available, false); assert.equal(removed, 1);
});

test("persistence is namespaced and invalid or inaccessible storage uses default", () => {
  let value;
  const storage = { getItem(key) { assert.equal(key, "regear.menu-shortcut.v1"); return value; },
    setItem(key, next) { assert.equal(key, "regear.menu-shortcut.v1"); value = next; } };
  assert.equal(loadMenuBinding(storage), "view-y");
  assert.equal(saveMenuBinding("sticks", storage), true); assert.equal(loadMenuBinding(storage), "sticks");
  for (const legacy of ["start-select", "bumpers", "invalid"]) {
    value = legacy; assert.equal(loadMenuBinding(storage), "view-y");
  }
  value = "disabled"; assert.equal(loadMenuBinding(storage), "disabled");
  assert.equal(loadMenuBinding({ getItem() { throw Error("denied"); } }), "view-y");
  assert.equal(saveMenuBinding("disabled", { setItem() { throw Error("denied"); } }), false);
  assert.equal(saveMenuBinding("invalid", storage), false);
});

test("Steam batch messages open once and rearm only on full release", t => {
  const s = setup(t);
  const press = [{ nC: 0, nA: 9, bS: true }, { nC: 0, nA: 3, bS: true }];
  s.send(press); s.send(press); assert.equal(s.opens(), 1);
  s.send([{ nC: 0, nA: 9, bS: false }]); s.send(press); assert.equal(s.opens(), 1);
  s.send(press.map(row => ({ ...row, bS: false })));
  s.send(press); assert.equal(s.opens(), 2);
});

test("whole malformed batch is rejected before a valid prefix can open", t => {
  const s = setup(t);
  for (const bad of [null, {}, { nC: 0, nA: 3, bS: 1 }, { nC: -1, nA: 3, bS: true }]) {
    s.handle.reset();
    s.send([{ nC: 0, nA: 9, bS: true }, { nC: 0, nA: 3, bS: true }, bad]);
    assert.equal(s.opens(), 0);
    s.send([{ nC: 0, nA: 3, bS: true }]); assert.equal(s.opens(), 0);
  }
  s.handle.reset();
  s.send(Array.from({ length: 129 }, (_, i) => ({ nC: 0, nA: i % 2 ? 3 : 9, bS: true })));
  assert.equal(s.opens(), 0);
});

test("Steam batch chords do not aggregate different controllers", t => {
  const s = setup(t);
  s.send([{ nC: 0, nA: 9, bS: true }, { nC: 1, nA: 3, bS: true }]);
  assert.equal(s.opens(), 0);
  s.send([{ nC: 0, nA: 3, bS: true }]); assert.equal(s.opens(), 1);
  s.handle.stop();
  s.send([{ nC: 1, nA: 9, bS: true }]); assert.equal(s.opens(), 1);
});


test("captured Ally Select+Y sequence and optional analog arguments open", t => {
  const s=setup(t);
  for(const row of [[0,35,true],[0,3,true],[0,3,false],[0,35,false]]) s.send(...row);
  assert.equal(s.opens(),1);
  for(const row of [[0,35,true,0,0],[0,3,true,0,0],[0,35,false,0,0],[0,3,false,0,0]]) s.send(...row);
  assert.equal(s.opens(),2);
});


test("Ally input-only provider works and expires incomplete chords", t => {
  let send, time=0, opens=0;
  const handle=startMenuShortcut({input:{RegisterForControllerInputMessages(cb){send=cb;return {unregister(){}};}},readBinding:()=>"view-y",open:()=>opens++,now:()=>time});
  t.after(handle.stop);assert.equal(handle.available,true);
  send(0,35,true);time=2000;send(0,3,true);assert.equal(opens,0);
  send(0,35,false);send(0,3,false);send(0,35,true);send(0,3,true);assert.equal(opens,1);
  time=5000;send(0,35,true);send(0,3,true);assert.equal(opens,1,"timeout must not release a matched latch");
});
