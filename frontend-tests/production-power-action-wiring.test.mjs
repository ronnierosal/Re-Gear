import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const read = file => readFileSync(new URL(`../src/${file}`, import.meta.url), "utf8");
const buildSource = read("build-profile.ts");
const compiled = ts.transpileModule(buildSource, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { buildAllowsDockIntent, productionEgpuTiles } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`
);

test("production exposes only the three guarded WholeDockControl intents", () => {
  for (const intent of ["disconnect_only", "sleep", "shutdown"])
    assert.equal(buildAllowsDockIntent("production", intent), true, intent);
  for (const intent of ["disconnect", "reconnect", "sleep_connected", "future"])
    assert.equal(buildAllowsDockIntent("production", intent), false, intent);

  const source = { egpu: [
    { id: "egpu", title: "eGPU Status", value: "Connected", detail: "Observed" },
    { id: "disconnect", title: "Safe Disconnect", value: "Check status", detail: "Guarded" },
    { id: "disconnect-sleep", title: "Disconnect + Sleep", value: "Check status", detail: "Guarded" },
    { id: "disconnect-shutdown", title: "Safe Disconnect + Shutdown", value: "Check status", detail: "Guarded" },
    { id: "software-reconnect", title: "Reconnect", value: "Ready", detail: "Forbidden" },
  ] };
  assert.deepEqual(productionEgpuTiles(source).egpu.map(tile => tile.id),
    ["egpu", "disconnect", "disconnect-sleep", "disconnect-shutdown"]);
});

test("production native actions dispatch sleep and shutdown through WholeDockControl", () => {
  const native = read("quick-access/expanded-command-center/native.tsx");
  assert.match(native, /!production \|\| intent === "disconnect_only" \|\| intent === "sleep" \|\| intent === "shutdown"/);
  assert.match(native, /tile\.id==="disconnect-sleep"\)\{disconnect\("sleep"\);return true;\}/);
  assert.match(native, /tile\.id==="disconnect-shutdown"\)\{disconnect\("shutdown"\);return true;\}/);
  assert.doesNotMatch(native, /production && intent !== "disconnect_only"/);

  const shell = read("quick-access/expanded-command-center/shell.tsx");
  assert.match(shell, /tile\.id === "disconnect-sleep" \|\| tile\.id === "disconnect-shutdown"/);

  const control = read("whole-dock-control.tsx");
  assert.match(control, /action === "whole_dock_sleep"/);
  assert.match(control, /action === "whole_dock_shutdown"/);
  assert.match(control, /Keep the cable connected until Re-Gear asks you to unplug it/);
  const model = read("whole-dock-control-model.ts");
  assert.match(model, /status\.unplug_required === true/);
  assert.match(model, /Unplug the eGPU cable now/);
  assert.match(model, /verified physical absence/);
  assert.doesNotMatch(buildSource, /whole_dock_reconnect|sleep_connected/);
});
