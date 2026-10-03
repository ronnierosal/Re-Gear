import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";
import { createUnplugWarningCoordinator } from "../src/unplug-warning-coordinator.ts";

const modelJs = ts.transpileModule(
  readFileSync(new URL("../src/whole-dock-control-model.ts", import.meta.url), "utf8"),
  { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } },
).outputText;
const model = await import(`data:text/javascript;base64,${Buffer.from(modelJs).toString("base64")}`);
const componentJs = ts.transpileModule(
  readFileSync(new URL("../src/whole-dock-control.tsx", import.meta.url), "utf8"),
  { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022, jsx: ts.JsxEmit.React } },
).outputText.replace(/^import .*;\r?$/gm, "")
  .replace(/export async function recoverTerminalDockReceipt/, "async function recoverTerminalDockReceipt")
  .replace(/export function WholeDockControl/, "function WholeDockControl");

const settle = async () => { for (let n = 0; n < 12; n++) await Promise.resolve(); };
const REQUEST = "f".repeat(32);
const pendingKey = "regear.whole-dock.pending-request";

function harness(status, unplugWarning) {
  const storage = new Map([[pendingKey, model.formatPendingRecord("disconnect_only", "backend-terminal", REQUEST)]]);
  const h = { status, timers: new Map(), serial: 0 };
  let slots = [], index = 0, effects = [], cleanups = [];
  const useState = value => {
    const slot = index++;
    if (!(slot in slots)) slots[slot] = value;
    return [slots[slot], next => { slots[slot] = typeof next === "function" ? next(slots[slot]) : next; }];
  };
  const useRef = value => {
    const slot = index++;
    if (!(slot in slots)) slots[slot] = { current: value };
    return slots[slot];
  };
  const useEffect = fn => {
    const slot = index++;
    if (!(slot in slots)) { slots[slot] = true; effects.push(fn); }
  };
  const useSyncExternalStore = (_subscribe, read) => { index++; return read(); };
  const React = { createElement: (type, props, ...children) => ({ type, props: { ...props, children } }) };
  const callable = name => name === "get_egpu_disconnect_status"
    ? () => Promise.resolve(h.status)
    : () => Promise.resolve(h.status);
  const window = { localStorage: {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: key => storage.delete(key),
  } };
  const runtime = new Function(
    "React", "useState", "useRef", "useEffect", "useSyncExternalStore",
    "callable", "DialogButton", "showModal", "EgpuConfirmModal",
    "dockIntentControl", "dockRequestAbandoned", "dockRequestSettled",
    "formatPendingRecord", "parsePendingRecord", "window", "crypto",
    "setTimeout", "clearTimeout",
    `${componentJs}\nreturn WholeDockControl;`,
  )(
    React, useState, useRef, useEffect, useSyncExternalStore,
    callable, "button", () => ({ Close() {} }), "confirm",
    model.dockIntentControl, model.dockRequestAbandoned, model.dockRequestSettled,
    model.formatPendingRecord, model.parsePendingRecord, window,
    { randomUUID: () => REQUEST },
    fn => { const id = ++h.serial; h.timers.set(id, fn); return id; },
    id => h.timers.delete(id),
  );
  h.render = () => {
    index = 0;
    h.tree = runtime({
      intent: "disconnect_only",
      readCurrentSnapshot: () => ({ schema_version: 3, observed_at: new Date().toISOString() }),
      statusOnly: true,
      onSettled() {},
      unplugWarning,
    });
    for (const effect of effects.splice(0)) cleanups.push(effect());
    return h.tree;
  };
  h.poll = () => {
    const [id, callback] = h.timers.entries().next().value;
    h.timers.delete(id);
    callback();
  };
  h.unmount = () => { for (const cleanup of cleanups.splice(0)) cleanup?.(); };
  h.render();
  return h;
}

test("the existing WholeDock poll drives exact prompt and physical-absence cleanup", async () => {
  const observations = [];
  let warning = { phase: "idle", requestId: null };
  const unplugWarning = {
    observe(next) {
      observations.push(next);
      warning = next.physicalAbsenceVerified === true
        ? { phase: "cleared", requestId: next.requestId }
        : { phase: "prompt", requestId: next.requestId };
    },
    read: () => warning,
    subscribe: () => () => {},
  };
  const terminal = {
    schema_version: 1,
    code: "dock_teardown.software_down",
    request_id: REQUEST,
    busy: false,
    in_flight: false,
    ok: true,
    software_down: true,
    safe_to_unplug: false,
    hardware_write: false,
    release_stage: "removed",
    release: { released: true, filter_disarmed: true },
  };
  const h = harness(terminal, unplugWarning);
  await settle();
  assert.deepEqual(observations.at(-1), {
    requestId: REQUEST,
    deauthorized: true,
    physicalAbsenceVerified: false,
  });
  assert.match(JSON.stringify(h.render()), /Safe disconnect is complete. Physically unplug the eGPU now/);

  h.status = { ...terminal, physical_absence_verified: true };
  h.poll();
  await settle();
  assert.deepEqual(observations.at(-1), {
    requestId: REQUEST,
    deauthorized: true,
    physicalAbsenceVerified: true,
  });
  assert.equal(unplugWarning.read().phase, "cleared");
  h.unmount();
});

test("actual WholeDock terminal mapping retires warning but not busy or foreign status", async () => {
  const warning = createUnplugWarningCoordinator({
    schedule: () => 1, cancel() {}, repeat: () => 2, cancelRepeat() {}, playWarning() {},
  });
  warning.observe({ requestId: REQUEST, deauthorized: true });
  const terminal = { schema_version: 1, code: "dock_power.sleep_protection_unverified",
    request_id: REQUEST, busy: false, ok: false, software_down: true, safe_to_unplug: false };
  const h = harness({ ...terminal, request_id: "a".repeat(32) }, warning);
  await settle();
  assert.equal(warning.read().phase, "prompt", "foreign terminal cannot retire this request");
  h.status = { ...terminal, busy: true };
  h.poll();
  await settle();
  assert.equal(warning.read().phase, "prompt", "busy status cannot retire this request");
  h.status = terminal;
  h.poll();
  await settle();
  assert.equal(warning.read().phase, "retired");
  assert.notEqual(warning.read().phase, "cleared", "no physical absence is invented");
  assert.doesNotMatch(JSON.stringify(h.render()), /Physically unplug the eGPU now/);
  h.unmount();
  warning.stop();
});
