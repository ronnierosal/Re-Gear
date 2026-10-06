import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";
import { createUnplugWarningCoordinator as realWarningCoordinator } from "../src/unplug-warning-coordinator.ts";

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

const modelExports = {};
new Function("exports", compile(readFileSync(new URL("../src/whole-dock-control-model.ts", import.meta.url), "utf8")))(modelExports);
const REQUEST = "a".repeat(32);

function harness(pending = null, recoverTerminalDockReceipt = async () => null, realWarning = false) {
  const h = {
    cleanup: [], modals: [], sounds: [], timers: new Map(), intervals: new Map(),
    nextTimer: 1, warningStopped: false, reads: 0, calls: [],
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
    ...modelExports,
    createUnplugWarningCoordinator: ports => {
      h.warningPorts = ports;
      if (realWarning) {
        h.warning = realWarningCoordinator(ports);
        return h.warning;
      }
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
        retire(requestId) {
          if (warningState.requestId === requestId
              && (warningState.phase === "prompt" || warningState.phase === "alarm"))
            h.emitWarning({ phase: "retired", requestId });
        },
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
      : async (...args) => { h.calls.push({ name, args }); return null; },
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
    recoverTerminalDockReceipt,
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

test("actual owner and coordinator retire correlated unverified terminal warning", async () => {
  const pending = `v2:sleep:retired-panel:${REQUEST}`;
  const h = harness(pending, undefined, true);
  h.warning.observe({ requestId: REQUEST, deauthorized: true });
  const popup = h.modals[0];
  popup.options.fnOnClose();
  h.status = { schema_version: 1, request_id: REQUEST,
    code: "dock_power.sleep_protection_unverified", busy: false,
    software_down: true, safe_to_unplug: false, ok: false };
  await h.runOwnerPoll();
  assert.equal(h.warning.read().phase, "retired");
  assert.equal(h.intervals.size, 0);
  assert.equal(h.storage.getItem("regear.whole-dock.pending-request"), pending);
  const terminal = h.modals.at(-1);
  terminal.node.props.onOK();
  assert.equal(terminal.closed, true, "terminal result is dismissable without a safe claim");
  h.menu.stop();
});

test("simulated native auto-close restores blocking warning immediately, not at next poll", () => {
  const pending = `v2:sleep:retired-panel:${REQUEST}`;
  const h = harness(pending, undefined, true);
  h.warning.observe({ requestId: REQUEST, deauthorized: true });
  const popup = h.modals[0];
  popup.node.props.onOK();
  popup.closed = true; // Native host semantics injected; not native proof.
  popup.options.fnOnClose();
  assert.equal(h.modals.length, 2);
  assert.equal(h.modals[1].closed, false);
  assert.equal(h.warning.read().phase, "prompt");
  assert.equal(h.storage.getItem("regear.whole-dock.pending-request"), pending);
  h.menu.stop();
});

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

test("re-activating Safe Disconnect cannot acknowledge an active alarm", async () => {
  const pending = `v2:disconnect_only:retired-panel:${REQUEST}`;
  const h = harness();
  h.menu.open();
  h.mount();
  h.storage.setItem("regear.whole-dock.pending-request", pending);
  h.emitWarning({ phase: "alarm", requestId: REQUEST });

  h.menu.disconnect("disconnect_only");
  assert.equal(h.modals.length, 2, "the status popup and menu remain the only surfaces");
  assert.equal(h.storage.getItem("regear.whole-dock.pending-request"), pending);
  assert.equal(h.warning.read().phase, "alarm");

  const popup = h.modals[1];
  popup.options.fnOnClose();
  h.status = {
    schema_version: 1, request_id: REQUEST, code: "dock_teardown.software_down",
    software_down: true, safe_to_unplug: false, busy: false, ok: true,
    physical_absence_verified: true,
  };
  await h.runOwnerPoll();
  assert.equal(h.storage.getItem("regear.whole-dock.pending-request"), null,
    "the retained observer clears only after exact physical absence");
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

test("an asynchronously recovered receipt starts the owner watcher", async () => {
  const pending = `v2:disconnect_only:backend-terminal:${REQUEST}`;
  const h = harness(null, async storage => {
    storage.setItem("regear.whole-dock.pending-request", pending);
    return { intent: "disconnect_only", request: REQUEST };
  });
  for (let index = 0; index < 8; index++) await Promise.resolve();
  assert.equal(h.modals.length, 1, "recovery presents one status-only surface");
  h.modals[0].options.fnOnClose();
  h.status = {
    schema_version: 1, request_id: REQUEST, code: "dock_teardown.software_down",
    software_down: true, safe_to_unplug: false, busy: false, ok: true,
  };
  await h.runOwnerPoll();
  assert.equal(h.warning.read().phase, "prompt");
  assert.equal(h.modals.length, 2, "host close cannot orphan the recovered warning");

  h.modals[1].options.fnOnClose();
  h.status = { ...h.status, physical_absence_verified: true };
  await h.runOwnerPoll();
  assert.equal(h.storage.getItem("regear.whole-dock.pending-request"), null);
  h.menu.stop();
});

test("a recovered active sleep receipt restores the unplug warning without replay", async () => {
  const pending = `v2:sleep:backend-terminal:${REQUEST}`;
  const h = harness(null, async storage => {
    storage.setItem("regear.whole-dock.pending-request", pending);
    return { intent: "sleep", request: REQUEST };
  });
  for (let index = 0; index < 8; index++) await Promise.resolve();
  assert.equal(h.modals.length, 1);
  const dock = h.modals[0].node.props.children.find(child => child?.type === "dock");
  assert.equal(dock.props.intent, "sleep");
  assert.equal(dock.props.statusOnly, true);
  assert.equal(dock.props.startRequest, undefined);
  h.modals[0].options.fnOnClose();
  h.status = {
    schema_version: 1, request_id: REQUEST, code: "dock_power.unplug_required",
    software_down: true, safe_to_unplug: false, unplug_required: true,
    busy: true, in_flight: true, ok: false, power_action: "sleep", power_requested: false,
    route_action: "whole_dock_sleep",
  };
  await h.runOwnerPoll();
  assert.equal(h.warning.read().phase, "prompt");
  assert.equal(h.modals.length, 2);
  assert.equal(h.storage.getItem("regear.whole-dock.pending-request"), pending);
  h.menu.stop();
});

test("expired recovered sleep still warns but never promises automatic sleep", async () => {
  const pending = `v2:sleep:backend-terminal:${REQUEST}`;
  const h = harness(null, async storage => {
    storage.setItem("regear.whole-dock.pending-request", pending);
    return { intent: "sleep", request: REQUEST };
  });
  for (let index = 0; index < 8; index++) await Promise.resolve();
  h.modals[0].options.fnOnClose();
  h.status = {
    schema_version: 1, request_id: REQUEST, code: "dock_power.unplug_request_expired",
    software_down: true, safe_to_unplug: false, unplug_required: true,
    busy: false, in_flight: false, ok: false, power_action: "sleep", power_requested: false,
    route_action: "whole_dock_sleep",
  };
  await h.runOwnerPoll();
  assert.equal(h.warning.read().phase, "prompt");
  assert.equal(h.modals.length, 2);
  const dock=h.modals[1].node.props.children.find(child=>child?.type==="dock");
  assert.equal(dock.props.statusOnly,true);
  assert.equal(dock.props.startRequest,undefined);
  h.menu.stop();
});

test("an inline warning remains observed after the Command Center closes", async () => {
  const pending = `v2:disconnect_only:inline-panel:${REQUEST}`;
  const h = harness();
  h.menu.open();
  h.mount();
  h.storage.setItem("regear.whole-dock.pending-request", pending);
  h.emitWarning({ phase: "prompt", requestId: REQUEST });
  const viewCleanup = h.cleanup.find(cleanup => typeof cleanup === "function");
  assert.ok(viewCleanup);
  viewCleanup();
  h.status = {
    schema_version: 1, request_id: REQUEST, code: "dock_teardown.software_down",
    software_down: true, safe_to_unplug: false, busy: false, ok: true,
  };
  await h.runOwnerPoll();
  assert.equal(h.warning.read().phase, "prompt");
  assert.equal(h.modals.length, 2, "closing the menu restores a read-only warning surface");
  assert.equal(h.storage.getItem("regear.whole-dock.pending-request"), pending);
  h.menu.stop();
});

for (const code of ["dock_power.unplug_required", "dock_power.unplug_request_expired", "dock_power.unplug_request_cancelled"]) {
  test("actual owner preserves shutdown warning across Hide/B/host close: " + code, async () => {
    const pending = `v2:shutdown:backend-terminal:${REQUEST}`;
    const h = harness(pending, undefined, true);
    h.status = { schema_version: 1, request_id: REQUEST, code, busy: true, in_flight: true,
      ok: false, software_down: true, safe_to_unplug: false, unplug_required: true,
      power_action: "shutdown", power_requested: false, route_action: "whole_dock_shutdown", phase: "power_verification" };
    h.modals.at(-1).options.fnOnClose();
    await h.runOwnerPoll();
    assert.equal(h.warning.read().phase, "prompt");
    const popup = h.modals.at(-1);
    popup.node.props.onOK(); popup.node.props.onCancel();
    assert.equal(popup.closed, false);
    popup.closed = true; popup.options.fnOnClose();
    assert.equal(h.modals.at(-1).closed, false);
    assert.equal(h.storage.getItem("regear.whole-dock.pending-request"), pending);
    assert.ok(h.reads > 0);
    assert.equal(h.calls.some(call => call.name === "cancel_egpu_shutdown" || call.name === "execute_egpu_disconnect"), false);
    h.menu.stop();
  });
}
