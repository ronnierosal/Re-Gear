import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const read = (p) => readFileSync(new URL(`../${p}`, import.meta.url), "utf8");

const modelSource = read("src/whole-dock-control-model.ts");
const { outputText } = ts.transpileModule(modelSource, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
});
const model = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

// Outcomes that are NOT refusals: the teardown succeeded, or the preflight said
// it may proceed. Everything else the backend can emit ends a request without a
// software disconnect and therefore has to settle it.
const NOT_REFUSALS = new Set(["dock_teardown.software_down", "dock_teardown.permitted"]);

/** Every `dock_teardown.*` code the backend can put in a payload.
 *
 * Derived from the backend source rather than restated here. A hand-maintained
 * mirror of a backend enum is exactly what drifted and bricked the control, so
 * this test must fail when the backend gains a code -- not when someone
 * remembers to update a list. */
function backendCodes() {
  const sources = [
    read("backend/regear/application/whole_dock_teardown.py"),
    read("backend/regear/domain/dock_teardown.py"),
  ].join("\n");
  const found = new Set();
  // Both quote styles: main.py already writes several codes single-quoted, so a
  // formatter pass over these files would otherwise empty the scan silently.
  for (const [, code] of sources.matchAll(/['"](dock_teardown\.[a-z_]+)['"]/g)) found.add(code);
  return found;
}

/** The backend inventory as reviewed, committed so drift has to be looked at.
 *
 * An earlier version of this guard asserted only `size >= 20` against an
 * inventory of 28. A review broke it: convert eight codes to f-strings so the
 * scan misses them, delete the same eight from the model set, and the whole
 * suite passed green -- exactly the silent drift this file exists to stop. A
 * threshold cannot do this job; the set has to be pinned. */
const REVIEWED_INVENTORY = [
  "dock_teardown.already_down", "dock_teardown.approval_required",
  "dock_teardown.approval_superseded", "dock_teardown.busy",
  "dock_teardown.final_state_unverified", "dock_teardown.gpu_scan_incomplete",
  "dock_teardown.gpu_still_attached", "dock_teardown.identity_or_idle_unknown",
  "dock_teardown.mounted_storage", "dock_teardown.operation_required",
  "dock_teardown.permitted", "dock_teardown.preflight_changed",
  "dock_teardown.software_down", "dock_teardown.storage_in_use",
  "dock_teardown.storage_scan_incomplete", "dock_teardown.transaction_owned",
  "dock_teardown.tunnel_capability_unknown", "dock_teardown.tunnel_capability_unsupported",
  "dock_teardown.tunnel_preflight_changed", "dock_teardown.tunnel_scan_incomplete",
  "dock_teardown.tunnel_state_unknown", "dock_teardown.tunnel_unidentified",
  "dock_teardown.tunnel_write_permission_denied", "dock_teardown.tunnel_write_permission_unknown",
  "dock_teardown.unresolved", "dock_teardown.usb_preflight_changed",
  "dock_teardown.usb_removal_unverified", "dock_teardown.usb_scan_incomplete",
];

test("the backend inventory matches the reviewed snapshot exactly", () => {
  // Pinned, not thresholded. Movement in EITHER direction fails: a new backend
  // code, a renamed one, or a code rewritten in a form the scan cannot see.
  // If this fails, read the diff and decide -- do not widen the assertion.
  const codes = [...backendCodes()].sort();
  assert.deepEqual(codes, [...REVIEWED_INVENTORY].sort(),
    "backend teardown codes moved; review each and update REVIEWED_INVENTORY and the refusal set together");
});

test("every backend teardown refusal settles the request", () => {
  const missing = [];
  for (const code of backendCodes()) {
    if (NOT_REFUSALS.has(code)) continue;
    // A refusal payload as main.py actually shapes it: correlated, not busy,
    // never claiming unplug safety.
    const status = {
      schema_version: 1, ok: false, busy: false, safe_to_unplug: false,
      code, request_id: "a".repeat(32),
    };
    if (!model.dockRequestSettled(status, "a".repeat(32), "disconnect_only")) missing.push(code);
  }
  assert.deepEqual(missing, [],
    `these backend codes leave the control stuck behind the retry guard: ${missing.join(", ")}`);
});

test("a mounted USB drive on the dock does not brick the button", () => {
  // The concrete first-press case. mounted_storage is returned, not raised, so
  // it reached the payload verbatim and was not in the refusal set.
  const status = {
    schema_version: 1, ok: false, busy: false, safe_to_unplug: false,
    code: "dock_teardown.mounted_storage", request_id: "b".repeat(32),
  };
  assert.equal(model.dockRequestSettled(status, "b".repeat(32), "disconnect_only"), true);
});

test("a pre-correlation refusal settles even though it carries no request id", () => {
  // main.py rejects a malformed or busy trial before minting anything, so these
  // payloads have neither request_id nor busy. Nothing started; nothing to wait for.
  for (const code of ["dock_teardown.trial_confirmation_required", "dock_teardown.busy"]) {
    const status = { schema_version: 1, ok: false, code, safe_to_unplug: false };
    assert.equal(model.dockRequestSettled(status, "c".repeat(32), "disconnect_only"), true, code);
    assert.equal(model.dockRequestSettled(status, "c".repeat(32), "shutdown"), true, code);
  }
});

test("an uncorrelated response with any other code still refuses to settle", () => {
  // The closed set matters: releasing the guard on an arbitrary uncorrelated
  // payload would act on a stale or foreign status, which is the unsafe
  // direction. Only the two pre-correlation refusals are exempt.
  for (const code of ["dock_teardown.software_down", "dock_teardown.mounted_storage", "whatever"]) {
    const status = { schema_version: 1, ok: false, code, safe_to_unplug: false };
    assert.equal(model.dockRequestSettled(status, "d".repeat(32), "disconnect_only"), false, code);
  }
});

test("nothing settles a request that claims the cable may be pulled", () => {
  // safe_to_unplug is never true anywhere in the backend; if one ever appeared,
  // it must not be treated as a normal settled outcome.
  const status = {
    schema_version: 1, ok: false, busy: false, safe_to_unplug: true,
    code: "dock_teardown.mounted_storage", request_id: "e".repeat(32),
  };
  assert.equal(model.dockRequestSettled(status, "e".repeat(32), "disconnect_only"), false);
  const pre = { schema_version: 1, ok: false, safe_to_unplug: true, code: "dock_teardown.busy" };
  assert.equal(model.dockRequestSettled(pre, "e".repeat(32), "disconnect_only"), false);
});

test("a successful software disconnect still settles, and still grants nothing", () => {
  const status = {
    schema_version: 1, ok: true, busy: false, safe_to_unplug: false,
    code: "dock_teardown.software_down", software_down: true, request_id: "f".repeat(32),
  };
  assert.equal(model.dockRequestSettled(status, "f".repeat(32), "disconnect_only"), true);
  const view = model.dockIntentControl(status, null, "disconnect_only");
  assert.equal(view.action, null, "a completed disconnect offers no further action");
  assert.match(view.message, /not permission to unplug/i);
});

test("power-route pre-correlation refusals settle too", () => {
  // Same shape as the trial-route ones -- no request_id, no busy -- and they
  // orphan the record identically. Latent until a shutdown control is mounted.
  for (const code of ["dock_power.request_action_changed", "dock_power.boot_unverified",
                      "dock_power.invalid_intent", "dock_power.sleep_unverified"]) {
    const status = { schema_version: 1, ok: false, code, safe_to_unplug: false };
    assert.equal(model.dockRequestSettled(status, "g".repeat(32), "shutdown"), true, code);
  }
});
