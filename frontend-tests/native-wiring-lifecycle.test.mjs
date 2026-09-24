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
const actionExports={}; new Function("exports",compile(read("test-build-actions.ts")))(actionExports);

test('native Safe Disconnect activation opens one centered progress surface with a consumable start',()=>{
  const h=harness();h.menu.open();const view=h.mount();
  view.props.onDisconnect();view.props.onDisconnect();
  assert.equal(h.modals.length,2);
  const operation=h.modals[1].node??h.modals[1].view??h.modals[1];
  const tree=operation.props?operation:h.modals[1].tree;
  assert.equal(tree.props.strTitle,'Safe Disconnect');
  const control=tree.props.children.find(child=>child?.type==='dock');
  assert.equal(control.props.intent,'disconnect_only');
  assert.equal(control.props.startRequest(),true);assert.equal(control.props.startRequest(),false);
  h.menu.stop();
});
test('delayed close callback from an old operation cannot close the replacement',()=>{
  const h=harness();h.menu.open();const view=h.mount();
  view.props.onDisconnect();const old=h.modals[1];old.node.props.onOK();
  view.props.onDisconnect();const current=h.modals[2];old.options.fnOnClose();
  assert.equal(current.closed,false);
  view.props.onDisconnect();assert.equal(h.modals.length,3);
  h.menu.stop();assert.equal(current.closed,true);
});

function harness(pendingRecord = null) {
  const h = { modals: [], cleanup: [], timers: new Map(), nextTimer: 1, throwOpen: false, stopped: false, allowed: true };
  const values = new Map(pendingRecord ? [["regear.whole-dock.pending-request", pendingRecord]] : []);
  h.storage = { getItem:key=>values.get(key)??null, setItem:(key,value)=>values.set(key,value), removeItem:key=>values.delete(key) };
  const runtime = {
    createMenuVisibility, ...actionExports, GamepadButton:{DIR_UP:9,DIR_DOWN:10,DIR_LEFT:11,DIR_RIGHT:12}, EgpuConfirmModal:"confirm",
    parsePendingRecord: raw => {
      const match = /^v2:(disconnect|disconnect_only|sleep|shutdown):([^:]+):([^:]+)$/.exec(raw ?? "");
      return match ? { intent: match[1], panel: match[2], request: match[3] } : null;
    },
    jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }),
    useEffect: callback => h.cleanup.push(callback()), useState: value => [value, () => {}],
    useSyncExternalStore: (_subscribe, read) => read(),
    Button: "button", Focusable: "focusable", ModalRoot: "modal", Dropdown: "dropdown",
    ExpandedCommandCenter: "expanded", WholeDockControl: "dock", ShortcutSettings: "settings",
    loadMenuBinding: () => "view-y", saveMenuBinding: () => true, menuBindingOptions: [],
    startMenuShortcut: options => { h.shortcutOpen = options.open; return { available: true, reset() {}, stop() { h.stopped = true; } }; },
    showModal: (node,parent,options) => {
      if (h.throwOpen) throw Error("host unavailable");
      h.onHostOpen?.();
      const modal = { node, parent, options, closed: false, Close() { this.closed = true; } };
      h.modals.push(modal); return modal;
    },
  };
  const exports = {};
  new Function("require", "exports", compile(read("native.tsx")))(() => runtime, exports);
  h.tiles = { quick: [] };
  h.source = { read: () => h.tiles, subscribe: () => () => {} };
  h.snapshot = () => ({ schema_version: 3 });
  h.detail = () => "existing-detail";
  h.host = {localStorage:h.storage,
    setTimeout(callback) { const id=h.nextTimer++;h.timers.set(id,callback);return id; },
    clearTimeout(id) { h.timers.delete(id); }};
  h.runLatestTimer = () => { const entry=[...h.timers.entries()].at(-1);if(!entry)return;h.timers.delete(entry[0]);entry[1](); };
  h.menu = exports.createExpandedMenu(undefined, h.host, () => h.allowed, h.source, h.snapshot, h.detail);
  h.mount = () => {
    const child = h.modals.at(-1).node.props.children.find(child => typeof child?.type === "function");
    return child.type(child.props);
  };
  return h;
}

test('plugin remount restores pending sleep as status-only and never replays it',()=>{
  const h=harness('v2:sleep:retired-panel:request-1');
  assert.equal(h.modals.length,1);
  const tree=h.modals[0].node;
  assert.equal(tree.props.strTitle,'Disconnect + Sleep status');
  const control=tree.props.children.find(child=>child?.type==='dock');
  assert.equal(control.props.intent,'sleep');
  assert.equal(control.props.statusOnly,true);
  assert.equal(control.props.startRequest,undefined);
  h.menu.stop();assert.equal(h.modals[0].closed,true);
});

test('terminal Safe Disconnect correlation is cleared only by dismissing its restored popup',()=>{
  const pending='v2:disconnect_only:retired-panel:request-1';
  const h=harness(pending);
  assert.equal(h.storage.getItem('regear.whole-dock.pending-request'),pending);
  const tree=h.modals[0].node;
  const control=tree.props.children.find(child=>child?.type==='dock');
  assert.equal(control.props.statusOnly,true);
  assert.equal(control.props.startRequest,undefined);
  control.props.onSettled({intent:'disconnect_only',request:'request-1'});
  assert.equal(h.storage.getItem('regear.whole-dock.pending-request'),pending,
    'presenting terminal status keeps the remount receipt');
  tree.props.onOK();
  assert.equal(h.storage.getItem('regear.whole-dock.pending-request'),null,
    'explicit popup dismissal acknowledges the terminal result');
  assert.equal(h.modals[0].closed,true);
  h.menu.stop();
});

test('explicit Safe Disconnect replaces a stale handoff modal with status-only presentation once',()=>{
  const h=harness();h.menu.open();const view=h.mount();
  view.props.onDisconnect();
  const operation=h.modals[1].node;
  const control=operation.props.children.find(child=>child?.type==='dock');
  const request='request-after-handoff';
  h.storage.setItem('regear.whole-dock.pending-request',`v2:disconnect_only:panel:${request}`);
  h.runLatestTimer();
  assert.equal(h.modals[1].closed,true);
  assert.equal(h.modals.length,3);
  const restored=h.modals[2].node;
  assert.equal(restored.props.strTitle,'Safe Disconnect status');
  const status=restored.props.children.find(child=>child?.type==='dock');
  assert.equal(status.props.statusOnly,true);
  assert.equal(status.props.startRequest,undefined);
  assert.equal(control.props.startRequest(),true,
    'the stale visual replacement never consumes or replays the original request');
  h.menu.stop();
});

test('Gamescope teardown cannot acknowledge an active result before its replacement popup',()=>{
  const h=harness();h.menu.open();const view=h.mount();
  view.props.onDisconnect();
  const active=h.modals[1];
  const control=active.node.props.children.find(child=>child?.type==='dock');
  const request='request-terminal-after-handoff';
  const pending=`v2:disconnect_only:panel:${request}`;
  h.storage.setItem('regear.whole-dock.pending-request',pending);

  control.props.onSettled({intent:'disconnect_only',request});
  // A Gamescope/modal teardown may surface through any of these callbacks.
  // None belongs to the player-facing terminal status popup.
  active.node.props.onCancel();
  assert.equal(h.storage.getItem('regear.whole-dock.pending-request'),pending);
  assert.equal(active.closed,true);

  h.runLatestTimer();
  assert.equal(h.modals.length,3);
  const restored=h.modals[2].node;
  assert.equal(restored.props.strTitle,'Safe Disconnect status');
  const status=restored.props.children.find(child=>child?.type==='dock');
  assert.equal(status.props.statusOnly,true);
  status.props.onSettled({intent:'disconnect_only',request});
  assert.equal(h.storage.getItem('regear.whole-dock.pending-request'),pending);
  restored.props.onOK();
  assert.equal(h.storage.getItem('regear.whole-dock.pending-request'),null);
  h.menu.stop();
});

test('fresh Safe Disconnect acknowledges an exact settled stale operation and dispatches once',()=>{
  const h=harness();h.menu.open();const view=h.mount();
  view.props.onDisconnect();
  const stale=h.modals[1];
  const staleControl=stale.node.props.children.find(child=>child?.type==='dock');
  h.storage.setItem('regear.whole-dock.pending-request','v2:disconnect_only:panel:request-old');
  staleControl.props.onSettled({intent:'disconnect_only',request:'request-old'});
  h.runLatestTimer();
  view.props.onDisconnect();
  assert.equal(stale.closed,true);
  assert.equal(h.storage.getItem('regear.whole-dock.pending-request'),null);
  assert.equal(h.modals.length,4);
  const fresh=h.modals[3].node.props.children.find(child=>child?.type==='dock');
  assert.equal(fresh.props.statusOnly,undefined);
  assert.equal(fresh.props.startRequest(),true);
  assert.equal(fresh.props.startRequest(),false);
  h.menu.stop();
});

test('fresh Safe Disconnect reopens unresolved stale status without dispatching',()=>{
  const h=harness();h.menu.open();const view=h.mount();
  view.props.onDisconnect();
  const stale=h.modals[1];
  h.storage.setItem('regear.whole-dock.pending-request','v2:disconnect_only:panel:request-unresolved');
  h.runLatestTimer();
  view.props.onDisconnect();
  assert.equal(stale.closed,true);
  assert.equal(h.modals.length,4);
  const status=h.modals[3].node.props.children.find(child=>child?.type==='dock');
  assert.equal(status.props.statusOnly,true);
  assert.equal(status.props.startRequest,undefined);
  assert.equal(h.storage.getItem('regear.whole-dock.pending-request'),'v2:disconnect_only:panel:request-unresolved');
  h.menu.stop();
});

test('unconfirmed Safe Disconnect receipt clears only when its restored popup is dismissed',()=>{
  const pending='v2:disconnect_only:retired-panel:request-unconfirmed';
  const h=harness(pending);
  const tree=h.modals[0].node;
  const control=tree.props.children.find(child=>child?.type==='dock');
  assert.equal(control.props.statusOnly,true);
  assert.equal(control.props.startRequest,undefined);
  control.props.onSettled({intent:'disconnect_only',request:'request-unconfirmed'});
  assert.equal(h.storage.getItem('regear.whole-dock.pending-request'),pending,
    'presenting unconfirmed status keeps the remount receipt');
  tree.props.onOK();
  assert.equal(h.storage.getItem('regear.whole-dock.pending-request'),null,
    'explicit dismissal acknowledges this exact unconfirmed result');
  assert.equal(h.modals[0].closed,true);
  h.menu.stop();
});

test('dismissing a terminal popup cannot clear a newer receipt',()=>{
  const pending='v2:disconnect_only:retired-panel:request-old';
  const newer='v2:disconnect_only:new-panel:request-new';
  const h=harness(pending);
  const tree=h.modals[0].node;
  const control=tree.props.children.find(child=>child?.type==='dock');
  control.props.onSettled({intent:'disconnect_only',request:'request-old'});
  h.storage.setItem('regear.whole-dock.pending-request',newer);
  tree.props.onOK();
  assert.equal(h.storage.getItem('regear.whole-dock.pending-request'),newer);
  h.menu.stop();
});

test('hiding before terminal status keeps the receipt and restores status on the next explicit open',()=>{
  const pending='v2:disconnect_only:retired-panel:request-2';
  const h=harness(pending);
  assert.equal(h.modals.length,1);
  h.modals[0].node.props.onOK();
  assert.equal(h.storage.getItem('regear.whole-dock.pending-request'),pending);
  h.menu.open();
  assert.equal(h.modals.length,2);
  assert.equal(h.modals[1].node.props.strTitle,'Safe Disconnect status');
  const control=h.modals[1].node.props.children.find(child=>child?.type==='dock');
  assert.equal(control.props.statusOnly,true);
  assert.equal(control.props.startRequest,undefined);
  h.menu.stop();
});

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
  assert.deepEqual(view.props.tiles, actionExports.testBuildTiles(h.tiles));
  assert.deepEqual(view.props.tiles.egpu.map(tile=>tile.id), ["switch-handheld","disconnect","resolution","egpu","disconnect-sleep","disconnect-shutdown"]);
  assert.equal(view.props.tiles.egpu.find(tile=>tile.id==="disconnect-sleep").title,
    "Disconnect + Sleep");
  assert.ok(!("disconnect-sleep" in view.props.unavailableActions) && !("disconnect-shutdown" in view.props.unavailableActions));
  assert.equal(view.props.renderDetail, h.detail);
  // Every destructive route stays behind the same guarded WholeDockControl.
  const [dockSelector, dockControl] = view.props.disconnectControl.props.children;
  assert.equal(dockSelector.type, "dropdown");
  assert.deepEqual(dockSelector.props.rgOptions.map(option => option.data),
    ["disconnect_only", "sleep", "shutdown"]);
  assert.equal(dockControl.props.intent, "disconnect_only");
  assert.equal(dockControl.props.readCurrentSnapshot, h.snapshot);
  assert.equal(typeof dockControl.props.onSettled,'function');
  const retained='v2:disconnect_only:panel:request-from-operation';
  h.storage.setItem('regear.whole-dock.pending-request',retained);
  dockControl.props.onSettled({intent:'disconnect_only',request:'request-from-operation'});
  assert.equal(h.storage.getItem('regear.whole-dock.pending-request'),retained,
    'the embedded status reader cannot retire the operation popup receipt');
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
test("shortcut and nested operations let Decky select the focused game overlay window", () => {
  const h = harness(); h.menu.open(); const view = h.mount();
  assert.equal(h.modals[0].parent, undefined,
    "the plugin SharedJS window must not hide the menu behind a running game");
  view.props.onDisconnect();
  assert.equal(h.modals[1].parent, undefined,
    "nested operation surfaces must stay on Decky's focused modal window");
  h.menu.stop();
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
