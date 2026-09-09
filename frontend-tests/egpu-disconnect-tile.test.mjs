import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(
  new URL("../src/egpu-disconnect-tile.ts", import.meta.url),
  "utf8",
).replace(/^import type .*$/m, "");
const js = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { disconnectPresentation, outcomeNeedsAttention } = await import(
  "data:text/javascript;base64," + Buffer.from(js).toString("base64")
);

const status = (over = {}) => ({
  schema_version: 1,
  availability: "ready",
  code: "removal_safety.ready_for_supervised_removal",
  ready: true,
  busy: false,
  holders: [],
  scan_complete: true,
  external_display_committed: false,
  display_release_required: false,
  last: null,
  ...over,
});

test("a ready device offers the action and confirms what will happen", () => {
  const view = disconnectPresentation(status());

  assert.equal(view.available, true);
  assert.equal(view.actionLabel, "Disconnect");
  assert.equal(view.reason, null);
  assert.match(view.confirmation, /detach the eGPU in software/i);
});

test("every confirmation warns that the Steam session restarts", () => {
  // Today the session restart is what frees the device. A player is told
  // before, not surprised after.
  for (const over of [{}, { display_release_required: true }]) {
    const view = disconnectPresentation(status(over));
    assert.match(view.confirmation, /Steam session will restart/i);
  }
});

test("no confirmation ever implies that unplugging is safe", () => {
  for (const over of [{}, { display_release_required: true }]) {
    const view = disconnectPresentation(status(over));
    assert.match(view.confirmation, /Keep the cable connected/i);
    assert.doesNotMatch(view.confirmation, /safe to unplug|you can unplug|remove the cable/i);
  }
});

test("a standing display is offered, not reported as a blocker", () => {
  // The one blocker a disconnect clears itself. Rendering it as blocked would
  // say nothing can be done when only the player's approval is missing.
  const view = disconnectPresentation(
    status({ code: "removal_safety.external_display_still_active", display_release_required: true }),
  );

  assert.equal(view.available, true);
  assert.equal(view.displayApprovalRequired, true);
  assert.match(view.confirmation, /external display will turn off/i);
});

test("a display that needs no release does not mention turning one off", () => {
  const view = disconnectPresentation(status());
  assert.doesNotMatch(view.confirmation, /display will turn off/i);
  assert.equal(view.displayApprovalRequired, false);
});

test("a half-detached device outranks everything and reads as attention", () => {
  const view = disconnectPresentation(
    status({ availability: "recovery_required", code: "removal_transaction.partially_detached", ready: false }),
  );

  assert.equal(view.attention, true);
  assert.equal(view.available, false);
  assert.equal(view.actionLabel, null);
  assert.match(view.reason, /half detached/i);
});

test("a blocked device explains itself in words, never a raw code", () => {
  const view = disconnectPresentation(
    status({ availability: "blocked", ready: false, code: "removal_safety.clients_active_or_protected" }),
  );

  assert.equal(view.available, false);
  assert.equal(view.reason, "Something is still using the eGPU.");
});

test("an unmapped code still produces something a bug report can act on", () => {
  const view = disconnectPresentation(
    status({ availability: "blocked", ready: false, code: "removal_safety.some_future_fact" }),
  );

  assert.equal(view.available, false);
  assert.match(view.reason, /removal_safety\.some_future_fact/);
});

test("an incomplete scan is never presented as a free device", () => {
  // The exact fail-open removed from the backend twice: an empty holder list
  // from a scan that could not finish is not evidence of anything.
  const view = disconnectPresentation(
    status({
      availability: "blocked",
      ready: false,
      code: "removal_safety.client_scan_incomplete",
      holders: [],
      scan_complete: false,
    }),
  );

  assert.equal(view.available, false);
  assert.match(view.reason, /could not check every process/i);
});

test("ready false is refused even if availability says otherwise", () => {
  // Two fields that should agree; if they ever disagree, refuse.
  const view = disconnectPresentation(status({ availability: "ready", ready: false }));
  assert.equal(view.available, false);
});

test("busy is not an error and offers nothing to press", () => {
  const view = disconnectPresentation(status({ availability: "busy", ready: false, code: "live_disconnect.busy" }));

  assert.equal(view.available, false);
  assert.equal(view.attention, false);
  assert.equal(view.actionLabel, null);
  assert.match(view.reason, /already running/i);
});

test("no status at all reads as unknown rather than unavailable", () => {
  const view = disconnectPresentation(null);
  assert.equal(view.available, false);
  assert.equal(view.attention, false);
  assert.match(view.reason, /has not read/i);
});

test("only a disturbed device raises an alert after an attempt", () => {
  assert.equal(outcomeNeedsAttention(null), false);
  assert.equal(outcomeNeedsAttention({ device_disturbed: false }), false);
  assert.equal(outcomeNeedsAttention({ device_disturbed: true }), true);
});
