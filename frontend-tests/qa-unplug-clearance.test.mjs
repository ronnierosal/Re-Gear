import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/quick-access/unplug-clearance.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } });
const { unplugClearance } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

/** The v1 "unavailable" status. Ambiguous by construction: the same code is
 *  emitted when the observation throws and when attachment identity is
 *  missing, so it never attested that anything left the bus. */
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

/** What the backend would have to attest before clearance could ever open.
 *  None of it is emitted today; these fixtures describe the contract. */
const BINDING = { attachmentBinding: "egpu-stable-id", operationId: "op-public-1" };
const fullTeardown = (over = {}) => ({
  usbBranchRemoved: true, tunnelDeauthorized: true, scanComplete: true,
  attachmentBinding: "egpu-stable-id", operationId: "op-public-1", ...over,
});

/** Any wording that would tell a player the cable may come out. */
const GRANTS_UNPLUG =
  /you can now disconnect|safe to (unplug|disconnect|remove)|you (can|may) (now )?(unplug|remove)|remove the cable|ok to (unplug|disconnect)|ready to (unplug|disconnect)/i;

const failing = (c) => c.checks.filter((entry) => !entry.passed).map((entry) => entry.label);
const labelled = (c, label) => c.checks.find((entry) => entry.label === label);
const DOCK_CHECK = "Dock USB and Thunderbolt link brought down";

// ── AC1: observation failure, unknown state, or GPU absence alone ───────────

test("v1 unavailable status never verifies bus absence", () => {
  const c = unplugClearance(goneStatus(), goodOutcome());

  assert.equal(c.busAbsenceVerified, false);
  assert.ok(failing(c).includes("eGPU absence confirmed on the bus"));
});

test("an observation failure is never read as the device being gone", () => {
  // The status code is identical whether the eGPU left the bus or the
  // observation threw. It cannot distinguish them, so it clears nothing.
  for (const over of [
    {},
    { code: "live_disconnect.egpu_unavailable", holders: [], scan_complete: true },
    { availability: "unavailable", code: "live_disconnect.session_unavailable" },
  ]) {
    const c = unplugClearance(goneStatus(over), goodOutcome());
    assert.equal(c.cableClearance, false, JSON.stringify(over));
    assert.equal(c.busAbsenceVerified, false, JSON.stringify(over));
  }
});

test("a successful removal alone never clears the cable", () => {
  // Every GPU check passing is the strongest evidence this module can gather,
  // and it is still evidence about the GPU.
  const c = unplugClearance(goneStatus(), goodOutcome());

  assert.equal(c.removalVerified, true);
  assert.equal(c.cableClearance, false);
});

test("no evidence at all clears nothing and verifies nothing", () => {
  for (const args of [[null, null], [undefined, undefined], [goneStatus(), null], [null, goodOutcome()]]) {
    const c = unplugClearance(...args);
    assert.equal(c.removalVerified, false, JSON.stringify(args));
    assert.equal(c.cableClearance, false, JSON.stringify(args));
  }
});

// ── AC2: clearance needs fresh, positive, bound teardown evidence ───────────

test("complete dock evidence still cannot clear while bus absence is unproven", () => {
  // The v1 contract gap outranks even a perfect teardown attestation.
  const c = unplugClearance(goneStatus(), goodOutcome(), fullTeardown(), BINDING);

  assert.equal(labelled(c, DOCK_CHECK).passed, true);
  assert.equal(c.busAbsenceVerified, false);
  assert.equal(c.cableClearance, false);
});

test("partial teardown never satisfies the dock check", () => {
  const partial = [
    [fullTeardown({ usbBranchRemoved: false }), /USB branch is still attached/i],
    [fullTeardown({ tunnelDeauthorized: false }), /Thunderbolt link is still authorized/i],
    [fullTeardown({ usbBranchRemoved: false, tunnelDeauthorized: false }), /still attached/i],
  ];
  for (const [evidence, reason] of partial) {
    const c = unplugClearance(goneStatus(), goodOutcome(), evidence, BINDING);
    const dock = labelled(c, DOCK_CHECK);
    assert.equal(dock.passed, false, JSON.stringify(evidence));
    assert.match(dock.detail, reason);
    assert.equal(c.cableClearance, false);
  }
});

test("an unfinished dock observation is not an empty dock", () => {
  // The fail-open this codebase has removed more than once. Here it would cost
  // someone their files rather than a prompt.
  const c = unplugClearance(
    goneStatus(), goodOutcome(), fullTeardown({ scanComplete: false }), BINDING,
  );
  const dock = labelled(c, DOCK_CHECK);

  assert.equal(dock.passed, false);
  assert.match(dock.detail, /did not finish/i);
});

test("evidence about a different device is refused, not tolerated", () => {
  // A teardown of the dock the player unplugged an hour ago must not clear the
  // one they have now.
  const c = unplugClearance(
    goneStatus(), goodOutcome(),
    fullTeardown({ attachmentBinding: "some-other-egpu" }), BINDING,
  );
  const dock = labelled(c, DOCK_CHECK);

  assert.equal(dock.passed, false);
  assert.match(dock.detail, /different device/i);
});

test("evidence from a different transaction is refused", () => {
  const c = unplugClearance(
    goneStatus(), goodOutcome(),
    fullTeardown({ operationId: "op-public-2" }), BINDING,
  );
  const dock = labelled(c, DOCK_CHECK);

  assert.equal(dock.passed, false);
  assert.match(dock.detail, /different disconnect/i);
});

test("unbound evidence is refused exactly as absent evidence is", () => {
  for (const [evidence, binding, reason] of [
    [fullTeardown({ attachmentBinding: "" }), BINDING, /names no device or transaction/i],
    [fullTeardown({ operationId: "" }), BINDING, /names no device or transaction/i],
    [fullTeardown(), {}, /no device or transaction to bind/i],
    [fullTeardown(), null, /no device or transaction to bind/i],
    [fullTeardown(), { attachmentBinding: "egpu-stable-id" }, /no device or transaction to bind/i],
  ]) {
    const c = unplugClearance(goneStatus(), goodOutcome(), evidence, binding);
    const dock = labelled(c, DOCK_CHECK);
    assert.equal(dock.passed, false, JSON.stringify(evidence));
    assert.match(dock.detail, reason);
  }
});

test("no combination of inputs this module accepts can grant clearance", () => {
  // Swept rather than spot-checked. While the v1 contract stands there is no
  // path through this function that returns cableClearance true.
  const statuses = [null, goneStatus(), goneStatus({ availability: "ready" }), goneStatus({ scan_complete: false })];
  const outcomes = [null, goodOutcome(), goodOutcome({ device_disturbed: true }), goodOutcome({ ok: false })];
  const teardowns = [null, undefined, fullTeardown(), fullTeardown({ scanComplete: false })];
  const bindings = [null, BINDING, {}];
  for (const status of statuses) {
    for (const outcome of outcomes) {
      for (const teardown of teardowns) {
        for (const binding of bindings) {
          const c = unplugClearance(status, outcome, teardown, binding);
          assert.equal(c.cableClearance, false);
          assert.doesNotMatch(c.statement, GRANTS_UNPLUG);
          assert.doesNotMatch(c.caveat, GRANTS_UNPLUG);
        }
      }
    }
  }
});

// ── AC3: GPU-detached is separate from whole-dock safe-to-unplug ────────────

test("a good disconnect reports its own success, and only its own", () => {
  // The regression this replaces: every verdict was false, so a disconnect
  // that worked told the player Re-Gear could not confirm anything.
  const c = unplugClearance(goneStatus(), goodOutcome());

  assert.equal(c.removalVerified, true);
  assert.equal(c.busAbsenceVerified, false);
  assert.equal(c.cableClearance, false);
});

test("the three verdicts are distinct fields, not one flag", () => {
  const c = unplugClearance(goneStatus(), goodOutcome());

  for (const field of ["removalVerified", "busAbsenceVerified", "cableClearance"]) {
    assert.equal(typeof c[field], "boolean", field);
  }
});

test("a verified removal still says the dock is connected", () => {
  const c = unplugClearance(goneStatus(), goodOutcome());

  assert.equal(c.removalVerified, true);
  assert.match(c.statement, /dock is still connected/i);
  assert.match(c.statement, /not yet clearance to unplug/i);
  assert.doesNotMatch(c.statement, GRANTS_UNPLUG);
});

test("the dock is listed as an outstanding check, never omitted", () => {
  // Shown as unverified rather than left off the list, so a player sees that
  // something was not checked instead of inferring it from prose.
  const c = unplugClearance(goneStatus(), goodOutcome());
  const dock = labelled(c, DOCK_CHECK);

  assert.ok(dock, "the outstanding dock check is missing");
  assert.equal(dock.passed, false);
  assert.match(dock.detail, /not checked/i);
});

test("what a software removal leaves behind is always named", () => {
  for (const args of [[goneStatus(), goodOutcome()], [null, null]]) {
    const c = unplugClearance(...args);
    assert.match(c.caveat, /eGPU only/i);
    assert.match(c.caveat, /USB controller/i);
    assert.match(c.caveat, /Thunderbolt/i);
    assert.match(c.caveat, /shut the handheld down/i);
  }
});

// ── AC4: regressions for observation failure and partial teardown ───────────

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

test("every removal check is load bearing", () => {
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
  ];
  for (const args of breakers) {
    assert.equal(unplugClearance(...args).removalVerified, false, JSON.stringify(args[1] ?? args[0]));
  }
});

test("an unverified removal says what to do instead", () => {
  const c = unplugClearance(goneStatus(), goodOutcome({ ok: false }));

  assert.match(c.statement, /do not disconnect/i);
  assert.match(c.statement, /shut the handheld down/i);
});

test("every check reports what was observed, not just a verdict", () => {
  const c = unplugClearance(goneStatus(), goodOutcome());

  for (const entry of c.checks) {
    assert.ok(entry.detail.length > 0, entry.label);
    assert.notEqual(entry.detail, entry.label);
  }
});

test("clearance never mentions the dock or other devices as safe", () => {
  const rendered = JSON.stringify(
    unplugClearance(goneStatus(), goodOutcome(), fullTeardown(), BINDING),
  );

  assert.doesNotMatch(rendered, /dock is safe|safe to unplug the dock|everything is safe/i);
});
