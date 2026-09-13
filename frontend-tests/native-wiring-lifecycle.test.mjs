import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const read = path => readFileSync(new URL(`../src/quick-access/expanded-command-center/${path}`, import.meta.url), "utf8");
const compile = source => ts.transpileModule(source, { compilerOptions: {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
} }).outputText;
const visibilityExports = {};
new Function("exports", compile(read("menu-visibility.ts")))(visibilityExports);
const { createMenuVisibility } = visibilityExports;

function harness() {
  const h = { modals: [], cleanup: [], throwOpen: false, stopped: false, allowed: true };
  const runtime = {
    createMenuVisibility,
    jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }),
    useEffect: callback => h.cleanup.push(callback()), useState: value => [value, () => {}],
    useSyncExternalStore: (_subscribe, read) => read(),
    Button: "button", Focusable: "focusable", ModalRoot: "modal", Dropdown: "dropdown",
    ExpandedCommandCenter: "expanded", WholeDockControl: "dock", ShortcutSettings: "settings",
    loadMenuBinding: () => "view-y", saveMenuBinding: () => true, menuBindingOptions: [],
    startMenuShortcut: options => { h.shortcutOpen = options.open; return { available: true, reset() {}, stop() { h.stopped = true; } }; },
    showModal: node => {
      if (h.throwOpen) throw Error("host unavailable");
      h.onHostOpen?.();
      const modal = { node, closed: false, Close() { this.closed = true; } };
      h.modals.push(modal); return modal;
    },
  };
  const exports = {};
  new Function("require", "exports", compile(read("native.tsx")))(() => runtime, exports);
  h.tiles = { quick: [] };
  h.source = { read: () => h.tiles, subscribe: () => () => {} };
  h.snapshot = () => ({ schema_version: 3 });
  h.detail = () => "existing-detail";
  h.menu = exports.createExpandedMenu(undefined, {}, () => h.allowed, h.source, h.snapshot, h.detail);
  h.mount = () => {
    const child = h.modals.at(-1).node.props.children.find(child => typeof child?.type === "function");
    return child.type(child.props);
  };
  return h;
}

test("visibility publishes stable changes with unsubscribe", () => {
  const store = createMenuVisibility(); let count = 0;
  const off = store.source.subscribe(() => count++);
  assert.equal(store.source.read(), false);
  store.set(true); store.set(true); assert.equal(count, 1);
  off(); store.set(false); assert.equal(count, 1);
});
test("actual native adapter mounts live tiles, details and golden disconnect together", () => {
  const h = harness(); h.menu.open(); const view = h.mount();
  assert.equal(h.menu.visibility.read(), true);
  assert.equal(view.props.tiles, h.tiles);
  assert.equal(view.props.renderDetail, h.detail);
  assert.equal(view.props.disconnectControl.props.intent, "disconnect_only");
  assert.equal(view.props.disconnectControl.props.readCurrentSnapshot, h.snapshot);
  assert.ok(view.props.settings);
  h.menu.stop(); assert.equal(h.menu.visibility.read(), false);
});
test("close, shortcut reopen, stale unmount and stop preserve exact menu lifetime", () => {
  const h = harness(); h.menu.open(); const first = h.mount(); const oldCleanup = h.cleanup.at(-1);
  h.menu.open(); assert.equal(h.modals.length, 1);
  first.props.onClose(); assert.equal(h.menu.visibility.read(), false);
  h.shortcutOpen(); h.mount(); assert.equal(h.modals.length, 2);
  oldCleanup(); assert.equal(h.menu.visibility.read(), true);
  h.cleanup.at(-1)(); assert.equal(h.menu.visibility.read(), false);
  h.menu.open(); h.mount(); h.menu.stop(); assert.equal(h.stopped, true);
  assert.equal(h.menu.visibility.read(), false); h.menu.open(); assert.equal(h.modals.length, 3);
});
test("refused or throwing host open never leaves visibility active", () => {
  const h = harness(); h.allowed = false; h.menu.open(); assert.equal(h.modals.length, 0);
  h.allowed = true; h.throwOpen = true; h.menu.open(); assert.equal(h.menu.visibility.read(), false);
  h.throwOpen = false; h.menu.open(); assert.equal(h.menu.visibility.read(), true);
  h.modals.at(-1).node.props.closeModal(); assert.equal(h.menu.visibility.read(), false);
});

test("reentrant host open and stop cannot leak a second modal or active visibility", () => {
  const h=harness(); h.onHostOpen=()=>h.menu.open(); h.menu.open();
  assert.equal(h.modals.length,1); h.menu.stop(); assert.equal(h.menu.visibility.read(),false);
  const stopped=harness(); stopped.onHostOpen=()=>stopped.menu.stop(); stopped.menu.open();
  assert.equal(stopped.modals.length,1); assert.equal(stopped.modals[0].closed,true);
  assert.equal(stopped.menu.visibility.read(),false);
});
