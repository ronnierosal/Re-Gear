import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const js = ts.transpileModule(readFileSync(new URL("../src/controller-safe-disconnect.ts", import.meta.url), "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const {
  startControllerSafeDisconnect, planShortcutBindings,
  DEFAULT_SHORTCUT_BINDINGS, VIEW_BUTTON: G, Y_BUTTON: Y,
} = await import("data:text/javascript;base64," + Buffer.from(js).toString("base64"));

// An arbitrary second code used only to exercise the chord mechanism. It is
// deliberately NOT named after a physical button: the ControllerInputGamepadButton
// index for anything beyond View and Y is not established in this repository.
const OTHER = 2;

const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
function context(mode = "tv_docked") {
  return { snapshot: { delivery_schema_version: 2, inference: { mode }, snapshot: {
    schema_version: 3, observed_at: new Date().toISOString(),
    game_state: "idle", support_tier: "certified", gamescope: { running: true },
    disconnect_readiness: { applicable: true },
    gpus: [{ role: "external", present: true, confidence: "verified" }],
  } }, journal: { code: "journal.idle" } };
}
function setup(t, { bindings, deliverableActions } = {}) {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let input, state, subscribed = 0;
  const current = context(); const confirmations = [];
  const handle = startControllerSafeDisconnect({
    input: {
      RegisterForControllerInputMessages(callback) { subscribed++; input = callback; return { unregister() {} }; },
      RegisterForControllerListChanges(callback) { subscribed++; state = callback; return { unregister() {} }; },
    },
    readContext: () => Promise.resolve(structuredClone(current)),
    isBusy: () => false,
    confirm: target => confirmations.push(target),
    bindings, deliverableActions,
  });
  t.after(handle.stop);
  return { handle, current, confirmations, subscribed: () => subscribed,
    input: (...args) => input(...args), state: () => state() };
}

test("a configured chord other than the default opens the same guarded confirmation", async t => {
  const s = setup(t, { bindings: [{ buttons: [G, OTHER], action: "display_switch" }] });
  assert.equal(s.handle.available, true);
  s.input(0, G, true); s.input(0, OTHER, true); await flush();
  t.mock.timers.tick(3000); await flush();
  assert.deepEqual(s.confirmations, ["ally"]);
});

test("the previously hard-coded chord stops matching once it is not configured", async t => {
  const s = setup(t, { bindings: [{ buttons: [G, OTHER], action: "display_switch" }] });
  s.input(0, G, true); s.input(0, Y, true); await flush();
  t.mock.timers.tick(10000); await flush();
  assert.deepEqual(s.confirmations, []);
});

test("two configured chords are watched independently", async t => {
  const s = setup(t, { bindings: [
    { buttons: [G, Y], action: "display_switch" },
    { buttons: [G, OTHER], action: "display_switch" },
  ] });
  assert.equal(s.handle.watching.length, 2);
  s.input(0, G, true); s.input(0, Y, true); await flush();
  t.mock.timers.tick(3000); await flush();
  s.input(0, G, false); s.input(0, Y, false);
  s.current.snapshot.inference.mode = "portable";
  s.input(0, G, true); s.input(0, OTHER, true); await flush();
  t.mock.timers.tick(3000); await flush();
  assert.deepEqual(s.confirmations, ["ally", "tv"]);
});

test("a longer chord never inherits the hold already running for the shorter one it contains", async t => {
  // Without a per-binding identity check, adding the third button leaves the
  // two-button timer running and it fires while the player holds a different
  // chord entirely. The shorter hold must be abandoned, not completed.
  const s = setup(t, { bindings: [
    { buttons: [G, Y], action: "display_switch" },
    { buttons: [G, Y, OTHER], action: "display_switch" },
  ] });
  s.input(0, G, true); s.input(0, Y, true); await flush();
  t.mock.timers.tick(1000); await flush();
  s.input(0, OTHER, true); await flush();
  t.mock.timers.tick(2000); await flush();
  assert.deepEqual(s.confirmations, [], "the two-button deadline must not fire");
  t.mock.timers.tick(1000); await flush();
  assert.deepEqual(s.confirmations, ["ally"], "the three-button hold completes on its own deadline");
});

test("a chord bound to an action nothing delivers is refused and never opens anything", async t => {
  const s = setup(t, { bindings: [
    { buttons: [G, Y], action: "display_switch" },
    { buttons: [G, OTHER], action: "egpu_safe_disconnect" },
  ] });
  assert.deepEqual(s.handle.refused.map(entry => entry.code), ["controller_binding.action_not_deliverable"]);
  assert.equal(s.handle.watching.length, 1);
  s.input(0, G, true); s.input(0, OTHER, true); await flush();
  t.mock.timers.tick(10000); await flush();
  assert.deepEqual(s.confirmations, []);
});

test("an empty or fully refused configuration never subscribes to controller input", () => {
  for (const bindings of [[], [{ buttons: [G], action: "display_switch" }]]) {
    let subscribed = 0;
    const handle = startControllerSafeDisconnect({
      input: {
        RegisterForControllerInputMessages() { subscribed++; return { unregister() {} }; },
        RegisterForControllerListChanges() { subscribed++; return { unregister() {} }; },
      },
      readContext: () => Promise.resolve(context()),
      isBusy: () => false, confirm: () => {}, bindings,
    });
    assert.equal(handle.available, false);
    assert.equal(subscribed, 0, "no listener should exist with nothing to watch");
    handle.stop();
  }
});

test("a per-chord hold is honoured instead of the three second default", async t => {
  const s = setup(t, { bindings: [{ buttons: [G, Y], action: "display_switch", holdMs: 5000 }] });
  s.input(0, G, true); s.input(0, Y, true); await flush();
  t.mock.timers.tick(3000); await flush();
  assert.deepEqual(s.confirmations, []);
  t.mock.timers.tick(2000); await flush();
  assert.deepEqual(s.confirmations, ["ally"]);
});

test("planning refuses each unusable chord with its own reason and keeps the rest", () => {
  const plan = planShortcutBindings([
    { buttons: [G], action: "display_switch" },
    { buttons: [G, Y], action: "display_switch" },
    { buttons: [Y, G], action: "display_switch" },
    { buttons: [G, 999], action: "display_switch" },
    { buttons: [G, 1.5], action: "display_switch" },
    { buttons: "nope", action: "display_switch" },
    { buttons: [G, OTHER], action: "display_switch", holdMs: 100 },
    { buttons: [G, OTHER], action: "egpu_safe_disconnect" },
  ]);
  assert.deepEqual(plan.refused.map(entry => entry.code), [
    "controller_binding.single_button_chord",
    "controller_binding.duplicate_chord",
    "controller_binding.invalid_button",
    "controller_binding.invalid_button",
    "controller_binding.invalid_button",
    "controller_binding.hold_out_of_range",
    "controller_binding.action_not_deliverable",
  ]);
  assert.deepEqual(plan.watched.map(entry => entry.buttons), [[G, Y]]);
});

test("a chord repeating one button is not a two-button chord", () => {
  const plan = planShortcutBindings([{ buttons: [G, G], action: "display_switch" }]);
  assert.deepEqual(plan.refused.map(entry => entry.code), ["controller_binding.single_button_chord"]);
});

test("the shipped default is exactly the delivered View plus Y chord", () => {
  const plan = planShortcutBindings(DEFAULT_SHORTCUT_BINDINGS);
  assert.deepEqual(plan.refused, []);
  assert.deepEqual(plan.watched, [{ buttons: [G, Y], action: "display_switch", holdMs: 3000 }]);
});
