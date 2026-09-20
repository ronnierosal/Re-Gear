import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const js = ts.transpileModule(
  readFileSync(new URL("../src/whole-dock-control-model.ts", import.meta.url), "utf8"),
  { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } },
).outputText;
const model = await import(
  "data:text/javascript;base64," + Buffer.from(js).toString("base64")
);
const { dockControl, dockIntentControl, dockRequestAbandoned,
  dockRequestSettled, formatPendingRecord, parsePendingRecord } = model;

const now = Date.parse("2026-09-19T18:00:00.000Z");
const token = "a".repeat(64) + ":" + "b".repeat(64);
const snapshot = {
  schema_version: 3,
  observed_at: new Date(now).toISOString(),
  game_state: "idle",
  egpu_link: { state: "up" },
};
const normalized = {
  schema_version: 1,
  code: "dock_teardown.no_trial",
  busy: false,
  safe_to_unplug: false,
  in_flight: false,
  attachment_token: token,
};

test("fresh no-trial status for a new attachment reaches existing admission", () => {
  assert.equal(dockControl(normalized, snapshot, now).action, "whole_dock_disconnect");
});

test("unresolved old software-down evidence remains non-actionable", () => {
  const old = {
    schema_version: 1,
    code: "dock_teardown.software_down",
    busy: false,
    ok: true,
    software_down: true,
    safe_to_unplug: false,
    request_id: "old-request",
  };
  assert.equal(dockControl(old, snapshot, now).action, null);
});

const componentJs = ts.transpileModule(
  readFileSync(new URL("../src/whole-dock-control.tsx", import.meta.url), "utf8"),
  { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022,
    jsx: ts.JsxEmit.React } },
).outputText.replace(/^import .*;\r?$/gm, "")
  .replace(/export function WholeDockControl/, "function WholeDockControl");
const settle = async () => { for (let n = 0; n < 12; n++) await Promise.resolve(); };

function componentHarness(statuses, snapshots) {
  const calls = [];
  const routes = [];
  const storage = new Map();
  let slots = [], index = 0, effects = [], timer = 0, activated = false;
  const useState = value => {
    const slot = index++;
    if (!(slot in slots)) slots[slot] = value;
    return [slots[slot], next => {
      slots[slot] = typeof next === "function" ? next(slots[slot]) : next;
    }];
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
  const React = { createElement: (type, props, ...children) =>
    ({ type, props: { ...props, children } }) };
  const callable = name => (...args) => {
    routes.push(name);
    if (name === "get_egpu_disconnect_status") {
      return Promise.resolve(statuses.shift() ?? normalized);
    }
    assert.equal(name, "execute_egpu_disconnect");
    calls.push(args);
    return Promise.resolve({ ...normalized, code: "dock_teardown.software_down",
      software_down: true, ok: true, request_id: args.at(-1) });
  };
  const localStorage = {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: key => storage.delete(key),
  };
  const Component = new Function("React", "useState", "useRef", "useEffect",
    "callable", "DialogButton", "showModal", "EgpuConfirmModal",
    "dockIntentControl", "dockRequestAbandoned", "dockRequestSettled",
    "formatPendingRecord", "parsePendingRecord", "window", "crypto",
    "setTimeout", "clearTimeout", componentJs + "\nreturn WholeDockControl;")(
      React, useState, useRef, useEffect, callable, "button", () => ({ Close() {} }),
      "confirm", dockIntentControl, dockRequestAbandoned, dockRequestSettled,
      formatPendingRecord, parsePendingRecord, { localStorage },
      { randomUUID: () => "12345678-1234-1234-1234-123456789abc" },
      () => ++timer, () => {});
  index = 0;
  Component({ intent: "disconnect_only",
    readCurrentSnapshot: () => snapshots.shift() ?? snapshot,
    startRequest: () => { if (activated) return false; activated = true; return true; } });
  for (const effect of effects.splice(0)) effect();
  return { calls, routes };
}

test("WholeDockControl admits normalized attachment only after fresh revalidation", async () => {
  const freshSnapshot = { ...snapshot, observed_at: new Date().toISOString() };
  const h = componentHarness([{ ...normalized }, { ...normalized }],
    [{ ...freshSnapshot }, { ...freshSnapshot }]);
  await settle();
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0][3], "whole_dock_disconnect");
  assert.equal(h.calls[0][5], token);
  assert.deepEqual(new Set(h.routes), new Set([
    "get_egpu_disconnect_status", "execute_egpu_disconnect",
  ]));
});

for (const changed of ["attachment", "snapshot"]) {
  test(`WholeDockControl refuses changed ${changed} before dispatch`, async () => {
    const freshSnapshot = { ...snapshot, observed_at: new Date().toISOString() };
    const secondStatus = changed === "attachment"
      ? { ...normalized, attachment_token: "c".repeat(64) + ":" + "d".repeat(64) }
      : { ...normalized };
    const secondSnapshot = changed === "snapshot"
      ? { ...freshSnapshot, observed_at: new Date(Date.now() - 60000).toISOString() }
      : { ...freshSnapshot };
    const h = componentHarness([{ ...normalized }, secondStatus],
      [{ ...freshSnapshot }, secondSnapshot]);
    await settle();
    assert.equal(h.calls.length, 0);
    assert.deepEqual(new Set(h.routes), new Set(["get_egpu_disconnect_status"]));
  });
}
