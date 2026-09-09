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
  for (const pair of [[8, 9], [35, 36], [30, 31], [35, 3], [8, 3], [9, 2]]) {
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

test("missing lifecycle provider or failed registration is unavailable and cleans up", () => {
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
