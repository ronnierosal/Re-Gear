import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { runtimeDependencies, executableSource } from "./presentation-dependencies.mjs";

const source = readFileSync(new URL("../src/quick-access/expanded-command-center/egpu-ui.tsx", import.meta.url), "utf8");

test("eGPU detail keeps the approved observed-state concepts separate", () => {
  for (const label of ["External GPU", "Dock mode", "Display output", "Render GPU", "Connection link"]) {
    assert.match(source, new RegExp(label.replace(/[.*+?^${}()|[\\]\\]/g, "\\$&")));
  }
});

test("eGPU detail preserves safe-disconnect truth boundary", () => {
  assert.match(source, /Safe Disconnect/);
  assert.match(source, /physical unplug clearance/);
  assert.match(source, /separate states/);
});

test("eGPU UI owns presentation only and does not import runtime hardware modules", () => {
  assert.deepEqual(runtimeDependencies(source,/usb4|pci|drm|gamescope|rpc|backend|@decky\/api/i),[]);
});

test("lifecycle progress is step-based and never fabricates a percentage", () => {
  assert.match(source, /CommandProgressSteps/);
  assert.doesNotMatch(executableSource(source), /percent|% complete|progressPercent/i);
});

test("runtime action slots are stable for wiring", () => {
  for (const slot of ["dockMode", "displayOutput", "safeDisconnect", "details"]) {
    assert.match(source, new RegExp(`controls\\?\\.${slot}`));
  }
});
