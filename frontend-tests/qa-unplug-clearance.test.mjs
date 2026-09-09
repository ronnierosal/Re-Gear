import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/quick-access/unplug-clearance.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } });
const { unplugClearance } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

/** A status reading taken after a successful removal: the device is gone. */
const goneStatus = (over = {}) => ({
  schema_version: 1, availability: "unavailable", code: "live_disconnect.egpu_unavailable",
  ready: false, attemptable: false, busy: false, holders: [], scan_complete: true,
  external_display_committed: false, display_release_required: false, last: null, ...over,
});

const goodOutcome = (over = {}) => ({
  schema_version: 1, stage: "removed", code: "live_disconnect.ok", ok: true, released: true,
  session_disturbed: true, removed: ["0000:08:00.1", "0000:08:00.0"], restored: [],
  display_released: [98], display_release_code: "ok", filter_disarmed: true,
  device_disturbed: false, ...over,
});

const CLEARED = /you can now disconnect the eGPU cable/i;
const failing = (c) => c.checks.filter((entry) => !entry.passed).map((entry) => entry.label);

test("full evidence clears the disconnect", () => {
  const c = unplugClearance(goneStatus(), goodOutcome());
  assert.equal(c.cleared, true, `unexpected failures: ${failing(c).join(", ")}`);
  assert.match(c.statement, CLEARED);
  assert.ok(c.checks.length >= 6);
  assert.ok(c.checks.every((entry) => entry.passed));
});

test("the decisive check is the bus, not the command", () => {
  // A success code says an action ran. Only "no eGPU is connected" says the
  // device is actually gone, and without it there is still something bound.
  const c = unplugClearance(
    goneStatus({ availability: "ready", code: "removal_safety.clear", ready: true, attemptable: true }),
    goodOutcome(),
  );
  assert.equal(c.cleared, false);
  assert.ok(failing(c).includes("eGPU no longer connected to the system"));
  assert.doesNotMatch(c.statement, CLEARED);
});

test("no evidence at all never clears", () => {
  for (const args of [[null, null], [undefined, undefined], [goneStatus(), null], [null, goodOutcome()]]) {
    const c = unplugClearance(...args);
    assert.equal(c.cleared, false, JSON.stringify(args));
    assert.doesNotMatch(c.statement, CLEARED);
  }
});

test("a half-detached device never clears, even when the command succeeded", () => {
  const c = unplugClearance(goneStatus(), goodOutcome({ device_disturbed: true }));
  assert.equal(c.cleared, false);
  assert.ok(failing(c).includes("Device not left half detached"));
});

test("functions restored after removal do not count as removed", () => {
  const c = unplugClearance(goneStatus(), goodOutcome({ restored: ["0000:08:00.0"] }));
  assert.equal(c.cleared, false);
  assert.ok(failing(c).includes("PCI functions removed"));
});

test("an unfinished holder scan never clears", () => {
  // An empty list from a scan that could not finish found nothing, and that is
  // not the same as there being nothing.
  const c = unplugClearance(goneStatus({ holders: [], scan_complete: false }), goodOutcome());
  assert.equal(c.cleared, false);
  assert.ok(failing(c).includes("Nothing still using the eGPU"));
});

test("a remaining holder never clears", () => {
  const c = unplugClearance(goneStatus({ holders: ["wireplumber.service"] }), goodOutcome());
  assert.equal(c.cleared, false);
});

test("an armed filter never clears", () => {
  const c = unplugClearance(goneStatus(), goodOutcome({ filter_disarmed: false }));
  assert.equal(c.cleared, false);
  assert.ok(failing(c).includes("Re-Gear's device filter disarmed"));
});

test("every single check is load bearing", () => {
  // Removing any one piece of evidence must withdraw the clearance. If one
  // could be dropped without effect it was decoration on a safety decision.
  const breakers = [
    [goneStatus(), goodOutcome({ ok: false })],
    [goneStatus(), goodOutcome({ released: false })],
    [goneStatus(), goodOutcome({ device_disturbed: true })],
    [goneStatus(), goodOutcome({ removed: [] })],
    [goneStatus(), goodOutcome({ filter_disarmed: false })],
    [goneStatus({ scan_complete: false }), goodOutcome()],
    [goneStatus({ holders: ["x.service"] }), goodOutcome()],
    [goneStatus({ availability: "ready" }), goodOutcome()],
    [goneStatus({ code: "removal_safety.clear" }), goodOutcome()],
  ];
  for (const args of breakers) {
    assert.equal(unplugClearance(...args).cleared, false, JSON.stringify(args[1] ?? args[0]));
  }
});

test("a refused clearance says what to do instead", () => {
  const c = unplugClearance(goneStatus({ availability: "ready" }), goodOutcome());
  assert.match(c.statement, /do not disconnect/i);
  assert.match(c.statement, /shut the handheld down first/i);
});

test("every check reports what was observed, not just a verdict", () => {
  const c = unplugClearance(goneStatus({ holders: ["wireplumber.service"] }), goodOutcome());
  for (const entry of c.checks) {
    assert.ok(entry.detail.length > 0, entry.label);
    assert.notEqual(entry.detail, entry.label, "detail must add information");
  }
  const held = c.checks.find((entry) => entry.label === "Nothing still using the eGPU");
  assert.match(held.detail, /still held by 1 unit/i);
});

test("the dock caveat is carried whether or not clearance is granted", () => {
  // A clean GPU removal says nothing about the USB branch behind the dock.
  for (const args of [[goneStatus(), goodOutcome()], [null, null]]) {
    const c = unplugClearance(...args);
    assert.match(c.caveat, /eGPU only/i);
    assert.match(c.caveat, /USB controllers and storage/i);
  }
});

test("clearance never mentions the dock or other devices as safe", () => {
  const rendered = JSON.stringify(unplugClearance(goneStatus(), goodOutcome()));
  assert.doesNotMatch(rendered, /dock is safe|safe to unplug the dock|everything is safe/i);
});
