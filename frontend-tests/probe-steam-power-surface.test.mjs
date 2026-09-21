import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

// This probe runs against a live handheld and looks for shutdown methods. The
// one thing it must never do is call one. These pins are the guard: a probe
// that powered off the device while "just looking" would be the worst possible
// bug in a file whose entire purpose is to avoid guessing.
const source = readFileSync(new URL("../scripts/probe_steam_power_surface.mjs", import.meta.url), "utf8");
const program = source.slice(source.indexOf("const expression"), source.indexOf("const evaluation"));

test("the probe never invokes a discovered power member", () => {
  // Inside the evaluated program, members are reached only by `typeof x[key]`
  // or listed by name. No call through a discovered key in any form.
  assert.doesNotMatch(program, /candidate\[[^\]]+\]\s*\(/, "no candidate[key](...)");
  assert.doesNotMatch(program, /system\[[^\]]+\]\s*\(/, "no system[key](...)");
  assert.doesNotMatch(program, /\.(SuspendPC|ShutdownPC|RestartPC|RequestSleep|BlockSuspendAction|OnSuspendRequest|PowerOff)\s*\(/,
    "no named power call");
  assert.doesNotMatch(program, /\.(call|apply)\(/, "no .call/.apply on a discovered member");
});

test("power members are read as names and types only", () => {
  assert.match(program, /typeof candidate\[key\]/);
  assert.match(program, /typeof system\[key\]/);
  // The capability test for the known sleep store compares typeof, and does
  // not exercise the functions it finds.
  assert.match(program, /typeof candidate\.BlockSuspendAction === "function"/);
});

test("the probe mutates nothing on the device", () => {
  for (const forbidden of ["localStorage", "setItem", "removeItem", "api.call", "connect(2",
    "deckyLoaderAPIInit", "Runtime.callFunctionOn", "Page.navigate", "Input."]) {
    assert.ok(!source.includes(forbidden), `probe must not reference ${forbidden}`);
  }
  // One evaluation, one target, then the socket closes.
  assert.equal((source.match(/Runtime\.evaluate/g) ?? []).length, 1);
  assert.match(source, /item\.title === "SharedJSContext"/);
});

test("the probe keeps off another agent's tunnel port", () => {
  assert.match(source, /"http:\/\/127\.0\.0\.1:19224"/);
  assert.doesNotMatch(source, /19223/);
});
