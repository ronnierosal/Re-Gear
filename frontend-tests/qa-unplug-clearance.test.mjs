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

// Any wording that would tell a player the cable may come out. Nothing this
// module produces may match it: every check here is about the GPU, and the
// dock's USB controller and Thunderbolt link survive a software removal.
const GRANTS_UNPLUG =
  /you can now disconnect|safe to (unplug|disconnect)|you can unplug|remove the cable|ok to (unplug|disconnect)/i;
const failing = (c) => c.checks.filter((entry) => !entry.passed).map((entry) => entry.label);

test("full evidence verifies the removal", () => {
  const c = unplugClearance(goneStatus(), goodOutcome());
  assert.equal(c.removalVerified, true, `unexpected failures: ${failing(c).join(", ")}`);
  assert.ok(c.checks.length >= 6);
});

test("a verified removal is still not clearance to unplug", () => {
  // The whole point. Every check above is about the GPU; the dock's USB
  // controller, the bridges above it and the tunnel are all still attached.
  const c = unplugClearance(goneStatus(), goodOutcome());

  assert.equal(c.removalVerified, true);
  assert.doesNotMatch(c.statement, GRANTS_UNPLUG);
  assert.match(c.statement, /not yet clearance to unplug/i);
});

test("no statement this module can produce ever grants an unplug", () => {
  // Swept rather than spot-checked: a future branch that says otherwise fails
  // here rather than reaching a player.
  const cases = [
    [goneStatus(), goodOutcome()],
    [null, null],
    [goneStatus(), null],
    [null, goodOutcome()],
    [goneStatus({ availability: "ready" }), goodOutcome()],
    [goneStatus(), goodOutcome({ device_disturbed: true })],
    [goneStatus(), goodOutcome({ filter_disarmed: false })],
    [goneStatus({ holders: ["x.service"] }), goodOutcome()],
  ];
  for (const args of cases) {
    const c = unplugClearance(...args);
    assert.doesNotMatch(c.statement, GRANTS_UNPLUG, JSON.stringify(args));
    assert.doesNotMatch(c.caveat, GRANTS_UNPLUG, JSON.stringify(args));
  }
});

test("what a software removal leaves behind is always named", () => {
  // A caveat a player has to already know about is not a caveat.
  for (const args of [[goneStatus(), goodOutcome()], [null, null]]) {
    const c = unplugClearance(...args);
    assert.match(c.caveat, /USB controller/i);
    assert.match(c.caveat, /Thunderbolt/i);
    assert.match(c.caveat, /shut the handheld down/i);
  }
});

test("the dock teardown is listed as an outstanding check, not omitted", () => {
  // Shown as unverified rather than left off the list, so a player sees that
  // something was not checked instead of inferring it from prose.
  const c = unplugClearance(goneStatus(), goodOutcome());
  const outstanding = c.checks.find(
    (entry) => entry.label === "Dock USB and Thunderbolt link brought down",
  );

  assert.ok(outstanding, "the outstanding dock check is missing");
  assert.equal(outstanding.passed, false);
  assert.match(outstanding.detail, /not checked/i);
});

test("the outstanding dock check does not fail the removal itself", () => {
  // The eGPU removal did succeed. Reporting it as failed because a different,
  // unbuilt step has not run would make a working disconnect look broken.
  const c = unplugClearance(goneStatus(), goodOutcome());

  assert.equal(c.removalVerified, true);
  assert.ok(failing(c).includes("Dock USB and Thunderbolt link brought down"));
});

test("the decisive check is the bus, not the command", () => {
  // A success code says an action ran. Only "no eGPU is connected" says the
  // device is actually gone, and without it there is still something bound.
  const c = unplugClearance(
    goneStatus({ availability: "ready", code: "removal_safety.clear", ready: true, attemptable: true }),
    goodOutcome(),
  );
  assert.equal(c.removalVerified, false);
  assert.ok(failing(c).includes("eGPU no longer connected to the system"));
  assert.doesNotMatch(c.statement, GRANTS_UNPLUG);
});

test("no evidence at all never verifies a removal", () => {
  for (const args of [[null, null], [undefined, undefined], [goneStatus(), null], [null, goodOutcome()]]) {
    const c = unplugClearance(...args);
    assert.equal(c.removalVerified, false, JSON.stringify(args));
    assert.doesNotMatch(c.statement, GRANTS_UNPLUG);
  }
});

test("a half-detached device never verifies, even when the command succeeded", () => {
  const c = unplugClearance(goneStatus(), goodOutcome({ device_disturbed: true }));
  assert.equal(c.removalVerified, false);
  assert.ok(failing(c).includes("Device not left half detached"));
});

test("functions restored after removal do not count as removed", () => {
  const c = unplugClearance(goneStatus(), goodOutcome({ restored: ["0000:08:00.0"] }));
  assert.equal(c.removalVerified, false);
  assert.ok(failing(c).includes("PCI functions removed"));
});

test("an unfinished holder scan never verifies", () => {
  // An empty list from a scan that could not finish found nothing, and that is
  // not the same as there being nothing.
  const c = unplugClearance(goneStatus({ holders: [], scan_complete: false }), goodOutcome());
  assert.equal(c.removalVerified, false);
  assert.ok(failing(c).includes("Nothing still using the eGPU"));
});

test("a remaining holder never verifies", () => {
  const c = unplugClearance(goneStatus({ holders: ["wireplumber.service"] }), goodOutcome());
  assert.equal(c.removalVerified, false);
});

test("an armed filter never verifies", () => {
  const c = unplugClearance(goneStatus(), goodOutcome({ filter_disarmed: false }));
  assert.equal(c.removalVerified, false);
  assert.ok(failing(c).includes("Re-Gear's device filter disarmed"));
});

test("every single check is load bearing", () => {
  // Removing any one piece of evidence must withdraw the verification. If one
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
    assert.equal(unplugClearance(...args).removalVerified, false, JSON.stringify(args[1] ?? args[0]));
  }
});

test("an unverified removal says what to do instead", () => {
  const c = unplugClearance(goneStatus({ availability: "ready" }), goodOutcome());
  assert.match(c.statement, /do not disconnect/i);
  assert.match(c.statement, /could not confirm every check/i);
  assert.match(c.statement, /shut the handheld down/i);
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
    assert.match(c.caveat, /USB controller/i);
    assert.match(c.caveat, /Thunderbolt/i);
  }
});

test("clearance never mentions the dock or other devices as safe", () => {
  const rendered = JSON.stringify(unplugClearance(goneStatus(), goodOutcome()));
  assert.doesNotMatch(rendered, /dock is safe|safe to unplug the dock|everything is safe/i);
});
