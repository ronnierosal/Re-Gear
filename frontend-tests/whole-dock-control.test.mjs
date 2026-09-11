import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";
const js = ts.transpileModule(readFileSync(new URL("../src/whole-dock-control-model.ts", import.meta.url), "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { dockControl } = await import("data:text/javascript;base64," + Buffer.from(js).toString("base64"));
const idle = { game_state: "idle", egpu_link: { state: "up" } };
const fresh = { schema_version: 1, busy: false, safe_to_unplug: false, code: "dock_teardown.no_trial", attachment_token: "a".repeat(64)+":"+"b".repeat(64) };
test("initial disconnect requires supported status and idle detected GPU", () => {
  assert.equal(dockControl(fresh, idle).action, "whole_dock_disconnect");
  for (const status of [null, {}, { ...fresh, schema_version: 2 }, { ...fresh, busy: true }, { ...fresh, safe_to_unplug: true }, { ...fresh, code: "unavailable" }]) assert.equal(dockControl(status, idle).action, null);
  for (const snapshot of [null, {}, { ...idle, game_state: "running" }, { ...idle, game_state: "unknown" }, { ...idle, egpu_link: { state: "down" } }]) assert.equal(dockControl(fresh, snapshot).action, null);
});
test("only verified software down offers reconnect, without GPU-present requirement", () => {
  const down = { ...fresh, code: "dock_teardown.software_down", software_down: true };
  assert.equal(dockControl(down, { game_state: "idle" }).action, "whole_dock_reconnect");
  assert.equal(dockControl({ ...down, software_down: "true" }, idle).action, null);
  assert.equal(dockControl(down, { game_state: "running" }).action, null);
  assert.match(dockControl(down, idle).message, /Keep the cable connected/);
});
test("partial and interrupted results cannot enable another write", () => {
  for (const code of ["dock_teardown.trial_unresolved", "dock_reconnect.timeout", "dock_reconnect.unresolved", "dock_teardown.trial_running"]) assert.equal(dockControl({ ...fresh, code }, idle).action, null);
});
test("reconnected result requires exact verified fields", () => {
  const restored = { ...fresh, code: "dock_reconnect.software_reconnected", software_reconnected: true, ok: true };
  assert.equal(dockControl(restored, idle).action, "whole_dock_disconnect");
  assert.equal(dockControl({ ...restored, ok: false }, idle).action, null);
  assert.match(dockControl(restored, idle).message, /picture, audio and controls/);
});
