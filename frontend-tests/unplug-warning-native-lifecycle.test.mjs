import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const read = path => readFileSync(
  new URL(`../src/quick-access/expanded-command-center/${path}`, import.meta.url),
  "utf8",
);
const compile = source => ts.transpileModule(source, { compilerOptions: {
  target: ts.ScriptTarget.ES2022,
  module: ts.ModuleKind.CommonJS,
  jsx: ts.JsxEmit.ReactJSX,
} }).outputText;
const visibilityExports = {};
new Function("exports", compile(read("menu-visibility.ts")))(visibilityExports);
const actionExports = {};
new Function("exports", compile(read("test-build-actions.ts")))(actionExports);

const REQUEST = "a".repeat(32);

function harness(pending = null) {
  const h = {
    cleanup: [], modals: [], sounds: [], timers: new Map(), intervals: new Map(),
    nextTimer: 1, warningStopped: false, reads: 0,
    status: { schema_version: 1, code: "dock_teardown.no_trial" },
  };
  const values = new Map(pending ? [["regear.whole-dock.pending-request", pending]] : []);
  h.storage = {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  };
  const warningListeners = new Set();
  let warningState = { phase: "idle", requestId: null };
  const runtime = {
    ...visibilityExports,
    ...actionExports,
    createUnplugWarningCoordinator: ports => {
      h.warningPorts = ports;
      h.warning = {
        read: () => warningState,
        observe(observation) {
          if (observation.physicalAbsenceVerified === true) {
            h.emitWarning({ phase: "cleared", requestId: observation.requestId });
          } else if (observation.deauthorized === true
              && !(warningState.requestId === observation.requestId
                && (warningState.phase === "prompt" || warningState.phase === "alarm"))) {
            h.emitWarning({ phase: "prompt", requestId: observation.requestId });
          }
        },
        subscribe(listener) { warningListeners.add(listener); return () => warningListeners.delete(listener); },
        stop() { h.warningStopped = true; warningState = { phase: "idle", requestId: null }; },
      };
      h.emitWarning = next => {
        warningState = next;
        for (const listener of [...warningListeners]) listener(next);
      };
      return h.warning;
    },
    displayTargetActionTile: () => ({ id: "display-target", title: "Display Target", value: "Unavailable", detail: "Unavailable" }),
    callable: name => name === "get_egpu_disconnect_status"
      ? async () => { h.reads++; return h.status; }
      : async () => null,
    GamepadButton: { DIR_UP: 9, DIR_DOWN: 10, DIR_LEFT: 11, DIR_RIGHT: 12 },
    EgpuConfirmModal: "confirm",
    parsePendingRecord: raw => {
      const match = /^v2:(disconnect|disconnect_only|sleep|shutdown):([^:]+):([^:]+)$/.exec(raw ?? "");
      return match ? { intent: match[1], panel: match[2], request: match[3] } : null;
    },
    jsx: (type, props) => ({ type, props }),
    jsxs: (type, props) => ({ type, props }),
    useEffect: callback => h.cleanup.push(callback()),
    useState: value => [value, () => {}],
    useSyncExternalStore: (_subscribe, readSnapshot) => readSnapshot(),
    Button: "button", Focusable: "focusable", ModalRoot: "modal", Dropdown: "dropdown",
    ExpandedCommandCenter: "expanded", WholeDockControl: "dock", ShortcutSettings: "settings",
    recoverTerminalDockReceipt: async () => null,
    loadMenuBinding: () => "view-y", saveMenuBinding: () => true, menuBindingOptions: [],
    startMenuShortcut: () => ({ available: true, reset() {}, stop() {} }),
    findModuleExport: predicate => {
      const dispatcher = { PlayNavSound: value => h.sounds.push(value) };
      const sounds = { IntoGameDetail: 1, DefaultOk: 2, BasicNav: 3 };
      return predicate(dispatcher) ? dispatcher : predicate(sounds) ? sounds : undefined;
    },
    showModal: (node, parent, options) => {
      const modal = { node, parent, options, closed: false, Close() { this.closed = true; } };
      h.modals.push(modal);
      return modal;
    },
  };
  const exports = {};
  new Function("require", "exports", compile(read("native.tsx")))(() => runtime, exports);
  h.host = {
    localStorage: h.storage,
    setTimeout(callback, delay) { const id = h.nextTimer++; h.timers.set(id, { callback, delay }); return id; },
    clearTimeout(id) { h.timers.delete(id); },
    setInterval(callback) { const id = h.nextTimer++; h.intervals.set(id, callback); return id; },
    clearInterval(id) { h.intervals.delete(id); },
  };
  h.source = { read: () => ({ quick: [], egpu: [] }), subscribe: () => () => {} };
  h.menu = exports.createExpandedMenu(
    undefined, h.host, () => true, h.source,
    () => ({ schema_version: 3 }), () => null,
  );
  h.mount = () => {
    const child = h.modals.at(-1).node.props.children.find(item => typeof item?.type === "function");
    return child.type(child.props);
  };
  h.runOwnerPoll = async () => {
    const entry = [...h.timers.entries()].find(([, timer]) => timer.delay === 2_000);
    assert.ok(entry, "owner warning poll is scheduled");
    h.timers.delete(entry[0]);
    entry[1].callback();
    for (let index = 0; index < 8; index++) await Promise.resolve();
  };
  return h;
}

test("all dock surfaces share one owner-lifetime warning coordinator", () => {
  const h = harness();
  h.menu.open();
  const view = h.mount();
  const detailDock = view.props.disconnectControl.props.children.find(child => child?.type === "dock");
  assert.equal(detailDock.props.unplugWarning, h.warning);

  view.props.onDisconnect();
  const active = h.modals.at(-1).node;
  const activeDock = active.props.children.find(child => child?.type === "dock");
  assert.equal(activeDock.props.unplugWarning, h.warning);
  assert.equal(h.warningPorts.playWarning instanceof Function, true);
  h.warningPorts.playWarning();
  assert.deepEqual(h.sounds, [2], "the alarm uses the existing Steam feedback channel");

  h.menu.stop();
  assert.equal(h.warningStopped, true);
  assert.equal(h.modals.at(-1).closed, true);
});

test("Hide cannot clear an active warning; exact cleared state dismisses it", () => {
  const pending = `v2:disconnect_only:retired-panel:${REQUEST}`;
  const h = harness(pending);
  const popup = h.modals[0];
  const dock = popup.node.props.children.find(child => child?.type === "dock");
  assert.equal(dock.props.unplugWarning, h.warning);

  h.emitWarning({ phase: "prompt", requestId: REQUEST });
  popup.node.props.onOK();
  assert.equal(popup.closed, false);
  assert.equal(h.storage.getItem("regear.whole-dock.pending-request"), pending);

  h.emitWarning({ phase: "alarm", requestId: REQUEST });
  popup.node.props.onCancel();
  assert.equal(popup.closed, false);
  assert.equal(h.storage.getItem("regear.whole-dock.pending-request"), pending);

  h.emitWarning({ phase: "cleared", requestId: "b".repeat(32) });
  assert.equal(popup.closed, false, "another request cannot dismiss this popup");
  h.emitWarning({ phase: "cleared", requestId: REQUEST });
  assert.equal(popup.closed, true);
  assert.equal(h.storage.getItem("regear.whole-dock.pending-request"), null);
  h.menu.stop();
});

test("host-driven close keeps exact warning polling and restores the unplug prompt", async () => {
  const pending = `v2:disconnect_only:retired-panel:${REQUEST}`;
  const h = harness(pending);
  const original = h.modals[0];
  original.options.fnOnClose();
  assert.equal(original.closed, true);
  assert.equal(h.storage.getItem("regear.whole-dock.pending-request"), pending);

  h.status = {
    schema_version: 1, request_id: REQUEST, code: "dock_teardown.software_down",
    software_down: true, safe_to_unplug: false, busy: false, ok: true,
  };
  await h.runOwnerPoll();
  assert.equal(h.reads, 1);
  assert.equal(h.warning.read().phase, "prompt");
  assert.equal(h.modals.length, 2, "the exact pending prompt is restored read-only");
  assert.equal(h.storage.getItem("regear.whole-dock.pending-request"), pending);

  const restored = h.modals[1];
  restored.options.fnOnClose();
  h.status = { ...h.status, physical_absence_verified: true };
  await h.runOwnerPoll();
  assert.equal(h.warning.read().phase, "cleared");
  assert.equal(h.storage.getItem("regear.whole-dock.pending-request"), null);
  h.menu.stop();
});
