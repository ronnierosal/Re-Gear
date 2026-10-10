import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync, existsSync } from "node:fs";
import ts from "typescript";

function load(path, decky = {}) {
  const exports = {};
  const jsx = (type, props) => ({ type, props: props ?? {} });
  const code = ts.transpileModule(readFileSync(path, "utf8"), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022,
  } }).outputText;
  new Function("exports", "require", code)(exports, name => {
    if (name === "react/jsx-runtime") return { jsx, jsxs: jsx };
    if (name === "react") return { useSyncExternalStore: (_subscribe, read) => read() };
    if (name === "@decky/ui") return { DialogButton: "button", Focusable: "focusable", ModalRoot: "modal",
      Field: "field", GamepadButton: { DIR_UP: 9, DIR_DOWN: 10 }, ...decky };
    if (name.endsWith(".svg")) return "synthetic-asset";
    if (name === "./readiness-row") return { StatusIcon: "status-icon" };
    if (name.startsWith(".")) {
      const candidate = new URL(`${name}.tsx`, path);
      return load(existsSync(candidate) ? candidate : new URL(`${name}.ts`, path), decky);
    }
    throw Error(`Unexpected effect/runtime import: ${name}`);
  });
  return exports;
}
const path = new URL("../src/usb4-waiting-runtime.tsx", import.meta.url);
const { createUsb4WaitingRuntime, Usb4WaitingPopup, Usb4WaitingStatus } = load(path);
const key = n => `uw-${n.toString(16).padStart(32, "0")}`;
const receipt = (n = 1, changes = {}) => Object.freeze({ payload: {
  snapshot: { schema_version: 3, observed_at: new Date(0).toISOString() },
  runtime_admission: { schema_version: 1, sleep_interceptor_admission: "observation-only",
    mode: "observation-only", mutation_allowed: false },
  usb4_waiting: { schema_version: 1, state: "unauthorized", notice_key: key(n) },
}, requestStartedAtMs: 0, receivedAtMs: 0, expiresAtMs: 10000, generation: 0,
supportedLifetime: false, ...changes });
function harness() {
  const modals = []; let now = 0;
  const runtime = createUsb4WaitingRuntime({ now: () => now, show(closed) {
    const modal = { closed, count: 0, close() { this.count++; closed(); } };
    modals.push(modal); return modal;
  } });
  return { runtime, modals, setNow(value) { now = value; } };
}
function mount(node) {
  if (Array.isArray(node)) return node.flatMap(mount);
  if (!node || typeof node !== "object") return [];
  if (typeof node.type === "function") return mount(node.type(node.props));
  return [node, ...mount(node.props.children)];
}
test("actual modal has only presentation-only Hide/Back and read-only guidance", () => {
  let dismissals = 0;
  const nodes = mount(Usb4WaitingPopup({ onDismiss: () => dismissals++ }));
  const buttons = nodes.filter(n => n.type === "button");
  assert.equal(buttons.length, 1);
  buttons[0].props.onClick();
  const focus = nodes.find(n => n.type === "focusable");
  let stopped = 0;
  focus.props.onCancelButton({ preventDefault() { stopped++; }, stopPropagation() { stopped++; } });
  assert.equal(stopped, 2); assert.equal(dismissals, 2);
  for (const handler of ["onOKButton", "onSecondaryButton", "onOptionsButton"]) assert.equal(focus.props[handler], undefined);
  const reading = nodes.find(n => n.type === "field");
  assert.equal(reading.props.focusable, true); assert.equal(reading.props.highlightOnFocus, false);
  for (const handler of ["onClick", "onOKButton", "onActivate"]) assert.equal(reading.props[handler], undefined);
  const rendered = JSON.stringify(nodes);
  assert.match(rendered, /Re-Gear cannot approve devices on this handheld/);
  assert.doesNotMatch(rendered, /uw-|Allow once|Always trust|G1|serial|token/);
});
test("dismiss/withdraw/reopen and A B A retain one-notice-per-key memory", () => {
  const h = harness(); h.runtime.observe(receipt());
  h.modals[0].closed(); h.runtime.observe(receipt());
  assert.equal(h.modals.length, 1);
  h.runtime.observe(receipt(2)); h.runtime.withdraw(); h.runtime.observe(receipt(1));
  assert.equal(h.modals.length, 2); assert.equal(h.modals[1].count, 1);
  h.runtime.observe(receipt(3, { generation: 1 }));
  h.runtime.observe(receipt(4, { generation: 0 }));
  assert.equal(h.modals.length, 3);
});
test("malformed expired and admission-changed receipts withdraw without fallback", () => {
  const h = harness(); h.runtime.observe(receipt());
  h.setNow(10000); h.runtime.observe(receipt());
  assert.equal(h.modals[0].count, 1); assert.equal(h.modals.length, 1);
  h.setNow(0); h.runtime.observe(receipt(2));
  const bad = receipt(3); bad.payload.runtime_admission.mode = "supported-runtime";
  h.runtime.observe(bad); assert.equal(h.modals[1].count, 1);
  assert.equal(h.modals.length, 2);
});
test("supported lifetime suppresses permanently including a fresh older reply", () => {
  const h = harness(); h.setNow(5);
  h.runtime.observe(receipt(1, { requestStartedAtMs: 5, receivedAtMs: 5 }));
  h.runtime.observe(receipt(2, { supportedLifetime: true }));
  assert.equal(h.modals[0].count, 1);
  h.runtime.observe(receipt(3, { generation: 1 }));
  assert.equal(h.modals.length, 1);
});
test("64-key saturation never evicts or allows automatic rearming", () => {
  const h = harness();
  for (let n = 1; n <= 100; n++) h.runtime.observe(receipt(n));
  h.runtime.observe(receipt(1)); assert.equal(h.modals.length, 64);
  assert.equal(h.runtime.source.read().automaticNoticeSuppressed, true);
  assert.match(h.runtime.source.read().guidance, /cannot approve/);
  h.runtime.stop(); h.runtime.observe(receipt(101));
  assert.equal(h.modals.length, 64);
});
test("unknown and ambiguous have only passive read-only status; stale/supported withdraw it", () => {
  const h = harness();
  for (const state of ["unknown", "ambiguous"]) {
    const value = receipt(); value.payload.usb4_waiting = { schema_version: 1, state, notice_key: null };
    h.runtime.observe(value);
    assert.equal(h.modals.length, 0);
    assert.equal(h.runtime.source.read().state, state);
    const nodes = mount(Usb4WaitingStatus({ source: h.runtime.source }));
    assert.equal(nodes.filter(n => n.type === "button").length, 0);
    assert.match(JSON.stringify(nodes), /unverified/);
    assert.doesNotMatch(JSON.stringify(nodes), /uw-|Waiting for system authorization/);
  }
  h.setNow(10000); h.runtime.observe(receipt()); assert.equal(h.runtime.source.read(), null);
  h.setNow(0); h.runtime.observe(receipt(2, { supportedLifetime: true }));
  assert.equal(h.runtime.source.read(), null);
});
test("expired older receipt and withdrawn old-generation evidence cannot remove a newer surface", () => {
  const h = harness(); h.setNow(9999);
  const payload = receipt().payload;
  payload.snapshot.observed_at = new Date(9999).toISOString();
  h.runtime.observe(receipt(2, { payload, requestStartedAtMs: 9999, receivedAtMs: 9999, expiresAtMs: 19999 }));
  h.setNow(10000); h.runtime.observe(receipt(1));
  assert.equal(h.modals[0].count, 0);
  const newPayload = { ...payload, usb4_waiting: { ...payload.usb4_waiting, notice_key: key(3) } };
  h.runtime.observe(receipt(3, { payload: newPayload, requestStartedAtMs: 9999, receivedAtMs: 9999, expiresAtMs: 19999, generation: 1 }));
  h.runtime.observe(receipt(4, { generation: 0 }));
  assert.equal(h.modals[1].count, 0);
});
test("source subscriptions cannot activate a notice after synchronous disposal", () => {
  const h = harness();
  h.runtime.source.subscribe(() => h.runtime.stop());
  h.runtime.observe(receipt());
  assert.equal(h.modals.length, 0);
  assert.equal(h.runtime.source.read(), null);
  assert.equal(Usb4WaitingStatus({ source: h.runtime.source }), null);
});
test("synchronous host dismissal/stop and late closed callbacks cannot close a newer surface", () => {
  const h = harness(); h.runtime.observe(receipt(1)); const oldClosed = h.modals[0].closed;
  h.runtime.observe(receipt(2)); oldClosed();
  assert.equal(h.modals[1].count, 0);
  let runtime, closeCalls = 0;
  runtime = createUsb4WaitingRuntime({ now: () => 0, show() {
    runtime.stop(); return { close() { closeCalls++; } };
  } });
  runtime.observe(receipt()); assert.equal(closeCalls, 1);
  runtime.observe(receipt(2)); assert.equal(closeCalls, 1);
});
test("a failed native close is not claimed closed or replaced by another notice", () => {
  let shows = 0, fail = true;
  const runtime = createUsb4WaitingRuntime({ now: () => 0, show() {
    shows++; return { close() { if (fail) throw Error("native close failed"); } };
  } });
  runtime.observe(receipt(1));
  assert.throws(() => runtime.observe(receipt(2)), /native close failed/);
  assert.equal(shows, 1);
  fail = false; runtime.observe(receipt(2)); assert.equal(shows, 2);
});
test("native modal adapter closes once on Hide/Back and never receives security dependencies", () => {
  const previous = globalThis.window;
  globalThis.window = {};
  try {
    let closeCalls = 0, callbacks = 0, nativeNode;
    const { showUsb4WaitingNotice } = load(path, { showModal(node, parent, options) {
      nativeNode = node;
      assert.equal(parent, globalThis.window);
      assert.equal(options.bNeverPopOut, true);
      return { Close() { closeCalls++; } };
    } });
    const modal = showUsb4WaitingNotice(() => callbacks++);
    const nodes = mount(nativeNode);
    nodes.find(n => n.type === "button").props.onClick();
    modal.close();
    assert.equal(closeCalls, 1); assert.equal(callbacks, 1);
  } finally { globalThis.window = previous; }
});
test("a failed show cannot storm repeats and source listeners remain isolated", () => {
  let shows = 0, notifications = 0;
  const runtime = createUsb4WaitingRuntime({ now: () => 0, show() { shows++; throw Error("host failed"); } });
  runtime.source.subscribe(() => { throw Error("subscriber failed"); });
  const unsubscribe = runtime.source.subscribe(() => notifications++);
  assert.throws(() => runtime.observe(receipt()), /host failed/);
  runtime.observe(receipt());
  assert.equal(shows, 1); assert.ok(notifications > 0);
  const prior = notifications; unsubscribe(); runtime.withdraw();
  assert.equal(notifications, prior); assert.equal(runtime.source.read(), null);
});
test("fresh older completion cannot overwrite the latest receipt unless suppressing supported lifetime", () => {
  const h = harness(); h.setNow(10);
  h.runtime.observe(receipt(2, { requestStartedAtMs: 5, receivedAtMs: 5 }));
  h.runtime.observe(receipt(1));
  assert.equal(h.modals.length, 1); assert.equal(h.modals[0].count, 0);
  h.runtime.observe(receipt(1, { supportedLifetime: true }));
  assert.equal(h.modals[0].count, 1); assert.equal(h.runtime.source.read(), null);
});
