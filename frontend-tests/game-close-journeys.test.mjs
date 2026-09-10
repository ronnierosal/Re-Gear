/** Whole journeys, from the press to the last port call.
 *
 * The other two files each cover one layer: `game-close-flow.test.mjs` the
 * close-and-remove sequence, `game-close-wiring.test.mjs` the gates in front of
 * it. Both pass while the layers disagree with each other, which is exactly the
 * failure this product already shipped -- a tile promising close-game-then-detach
 * over a panel that called the removal directly.
 *
 * So nothing here is stubbed between the layers. Each test builds a real
 * `DisconnectStatusPayload`, runs it through the real `disconnectPresentation`,
 * the real `pressFromDialog` and `runGameClosePress`, and into the real
 * `runDisconnectWithGameClose`. Only the ports are fakes, because they are the
 * device. Assertions are on the recorded call sequence, in order, so "nothing
 * happened" is a short list rather than an absent side effect nobody looked for.
 */

import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const load = (name) => {
  const source = readFileSync(new URL(`../src/${name}.ts`, import.meta.url), "utf8");
  const stripped = source.replace(/^import\s[\s\S]*?;\s*$/gm, "");
  return ts.transpileModule(stripped, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText;
};

const bundle =
  load("egpu-disconnect-tile") +
  load("game-close-flow") +
  load("quick-access/game-close-wiring");
const {
  runGameClosePress,
  pressFromDialog,
  claimRelaunchOnMount,
  disconnectPresentation,
  runDisconnectWithGameClose,
} = await import(`data:text/javascript;base64,${Buffer.from(bundle).toString("base64")}`);

const APP = "1145360";
const OTHER = "620";

const game = (over = {}) => ({
  app_id: APP, title: "Hades", save_capability: "verified_save_on_exit",
  egpu_handoff: "", save_known: true, identity_exact: true, ...over,
});

const prompt = (over = {}) => ({
  schema_version: 1, decision: "confirm", code: "game_close.confirm_required",
  intent: "disconnect", may_proceed: false, progress_at_risk: false,
  save_known: true, remember_offered: true, relaunch_offered: true,
  relaunch_requested: false, ...over,
});

const running = (over = {}) => ({
  schema_version: 1, availability: "attemptable", code: "removal_safety.game_running",
  ready: false, attemptable: true, busy: false, holders: ["gamescope"],
  scan_complete: true, external_display_committed: false,
  display_release_required: false, game: game(), close_prompt: prompt(),
  last: null, ...over,
});

const cleared = (over = {}) =>
  running({
    availability: "ready", code: "removal_safety.clear", ready: true, holders: [],
    game: null,
    close_prompt: prompt({
      decision: "nothing_to_close", code: "game_close.nothing_running",
      may_proceed: true, remember_offered: false, relaunch_offered: false,
    }),
    ...over,
  });

const outcome = (over = {}) => ({
  schema_version: 1, stage: "removed", code: "live_disconnect.removed", ok: true,
  released: true, session_disturbed: true, removed: ["0000:08:00.0"], restored: [],
  display_released: [], display_release_code: "display_release.not_required",
  filter_disarmed: true, device_disturbed: false, ...over,
});

/** Ports that record every call, and a backend that clears after `closesAfter`.
 *
 * `recorded` is the backend's durable relaunch record: written by the
 * disconnect, consumed exactly once by claiming. Modelling it as state rather
 * than a return value is what lets the pending-relaunch journey be tested at
 * all -- the panel that asks for the reopen is destroyed by the session restart.
 */
function rig({ closesAfter = 1, statuses = null, disconnectOutcome = outcome(), readiness = null } = {}) {
  const calls = [];
  let polls = 0;
  let recorded = "";
  // The flow gives up on a close using now() against its own deadline, so the
  // clock has to advance when it waits. A fixed now() makes the wait loop
  // unbounded -- the first version of this file hung until the heap gave out
  // rather than reporting the game-exit failure it was written to check.
  let clock = 0;
  return {
    calls,
    get recorded() { return recorded; },
    ports: {
      async readStatus() {
        polls += 1;
        calls.push(["status", polls]);
        if (statuses) return statuses[Math.min(polls - 1, statuses.length - 1)];
        return polls >= closesAfter ? cleared() : running();
      },
      async readSleepReadiness() {
        calls.push(["readiness"]);
        return readiness;
      },
      async terminateGame(appId) { calls.push(["terminate", appId]); },
      async disconnect(releaseDisplay, relaunchAppId, relaunchIntent) {
        calls.push(["disconnect", releaseDisplay, relaunchAppId, relaunchIntent]);
        recorded = relaunchAppId;
        return disconnectOutcome;
      },
      async suspend() { calls.push(["suspend"]); },
      async takePendingRelaunch() {
        calls.push(["take", recorded]);
        const claimed = recorded;
        recorded = "";
        return {
          steam_app_id: claimed,
          code: claimed ? "relaunch.approved" : "relaunch.nothing_recorded",
        };
      },
      async relaunchGame(appId) { calls.push(["relaunch", appId]); },
      async rememberChoice(appId, skip, relaunch) {
        calls.push(["remember", appId, skip, relaunch]);
        return { ok: true, code: "game_close.preference_stored" };
      },
      async wait(ms) { clock += ms; },
      now() { return clock; },
    },
  };
}

/** One press, assembled the way the panel assembles it. */
const press = (status, intent, answers) =>
  pressFromDialog(disconnectPresentation(status), intent, answers);

const names = (calls) => calls.map((c) => c[0]);

test("consent journey: the agreed game closes, then the device, then the reopen", async () => {
  const r = rig({ closesAfter: 2 });
  const result = await runGameClosePress(
    press(running(), "disconnect", { confirmed: true, remember: true, relaunch: true }),
    r.ports,
  );

  assert.equal(result.ok, true);
  assert.equal(result.gameClosed, true);
  // Order is the safety argument: the preference and the terminate come before
  // the removal, and the reopen only after the device reported back.
  assert.deepEqual(names(r.calls), [
    "status", "remember", "terminate", "status", "disconnect", "take", "relaunch",
  ]);
  assert.deepEqual(r.calls.find((c) => c[0] === "remember"), ["remember", APP, true, true]);
  assert.deepEqual(r.calls.find((c) => c[0] === "disconnect"), ["disconnect", false, APP, "disconnect"]);
  assert.deepEqual(r.calls.find((c) => c[0] === "relaunch"), ["relaunch", APP]);
});

test("cancellation journey: a dismissal reaches no port at all", async () => {
  const r = rig();
  const result = await runGameClosePress(
    // Ticked boxes on a dismissal must not survive. A "no" that still writes a
    // preference is a bug that outlives the press.
    press(running(), "disconnect", { confirmed: false, remember: true, relaunch: true }),
    r.ports,
  );

  assert.equal(result.ok, false);
  assert.equal(result.code, "wiring.cancelled");
  assert.equal(result.refusedBeforeAction, true);
  assert.deepEqual(r.calls, [], "a cancel must not read status, store a choice, close a game or touch the device");
});

test("game-exit failure journey: the device is never touched if the game will not go", async () => {
  // The backend keeps reporting the game running, so the close is never verified.
  const r = rig({ statuses: [running(), running(), running(), running(), running()] });
  const result = await runGameClosePress(
    press(running(), "disconnect", { confirmed: true }),
    r.ports,
  );

  assert.equal(result.ok, false);
  assert.equal(result.code, "flow.game_did_not_close");
  assert.ok(!names(r.calls).includes("disconnect"), "an unverified close must not reach a removal");
  assert.ok(!names(r.calls).includes("suspend"), "no power action after a failed prerequisite");
  assert.ok(!names(r.calls).includes("relaunch"), "nothing to put back: the game never closed");
});

test("stale-state journey: the dialog's game is not the running game, so nothing happens", async () => {
  // The dialog was drawn for APP. By the press, OTHER is running.
  const r = rig({ statuses: [running({ game: game({ app_id: OTHER }) })] });
  const result = await runGameClosePress(
    press(running(), "disconnect", { confirmed: true, relaunch: true }),
    r.ports,
  );

  assert.equal(result.code, "wiring.game_changed");
  assert.equal(result.refusedBeforeAction, true);
  assert.deepEqual(names(r.calls), ["status"], "the fresh read is allowed; acting on it is not");
});

test("stale-state journey: an identity that is no longer exact refuses too", async () => {
  const r = rig({ statuses: [running({ game: game({ identity_exact: false }) })] });
  const result = await runGameClosePress(
    press(running(), "disconnect", { confirmed: true }),
    r.ports,
  );

  assert.equal(result.code, "wiring.game_changed");
  assert.ok(!names(r.calls).includes("terminate"), "a game that cannot be named exactly must not be closed");
});

test("pending-relaunch journey: the record is honoured once, by whichever panel comes up", async () => {
  const r = rig({ closesAfter: 2 });
  await runGameClosePress(
    press(running(), "disconnect", { confirmed: true, relaunch: true }),
    r.ports,
  );
  // The session restart destroyed that panel. A fresh mount finds nothing left
  // to claim, because the disconnect already honoured it.
  const second = await claimRelaunchOnMount(r.ports);
  assert.equal(second.appId, null);
  assert.equal(r.recorded, "", "the record is consumed exactly once");

  // A disconnect that leaves a record behind is claimed by the next mount.
  const r2 = rig({ closesAfter: 2, disconnectOutcome: outcome({ session_disturbed: false }) });
  r2.ports.takePendingRelaunchOriginal = r2.ports.takePendingRelaunch;
  await runDisconnectWithGameClose(
    { appId: APP, intent: "disconnect", releaseDisplay: false, remember: false, relaunch: true },
    r2.ports,
  );
  assert.ok(names(r2.calls).includes("relaunch"));
});

test("pending-relaunch journey: a reading that needs a person is not somewhere to launch a game", async () => {
  for (const [availability, code] of [
    ["recovery_required", "wiring.mount_device_disturbed"],
    ["busy", "wiring.mount_busy"],
  ]) {
    const r = rig({ statuses: [cleared({ availability, busy: availability === "busy" })] });
    const claimed = await claimRelaunchOnMount(r.ports);
    assert.equal(claimed.code, code);
    assert.equal(claimed.deferred, true, "the record is left for a later mount, not consumed");
    assert.ok(!names(r.calls).includes("take"), "claiming would consume a record it cannot honour");
  }
});

test("destination journey: sleep asks for its own consent and does not reopen the game", async () => {
  const r = rig({
    closesAfter: 2,
    readiness: {
      schema_version: 1, code: "sleep.requires_disconnect", requires_disconnect: true,
      game: game(),
      // Re-derived for sleep: agreeing a game may close for a disconnect is not
      // agreeing it may close so the machine can suspend.
      close_prompt: prompt({ intent: "sleep" }),
      disconnect: running(),
    },
  });
  const result = await runGameClosePress(
    press(running(), "sleep", { confirmed: true, relaunch: true }),
    r.ports,
  );

  assert.equal(result.ok, true);
  assert.deepEqual(r.calls.find((c) => c[0] === "disconnect"), ["disconnect", false, APP, "sleep"]);
  assert.ok(names(r.calls).includes("suspend"), "the sleep destination still suspends");
  assert.ok(
    !names(r.calls).includes("relaunch"),
    "reopening now would launch the game seconds before the suspend; the record waits for the wake",
  );
});

test("destination journey: consent given for a disconnect does not authorise a sleep", async () => {
  const r = rig({
    readiness: {
      schema_version: 1, code: "sleep.requires_disconnect", requires_disconnect: true,
      game: game(),
      // The backend is asking about a disconnect, but the player pressed sleep.
      close_prompt: prompt({ intent: "disconnect" }),
      disconnect: running(),
    },
  });
  const result = await runGameClosePress(
    press(running(), "sleep", { confirmed: true }),
    r.ports,
  );

  assert.equal(result.code, "wiring.intent_mismatch");
  assert.ok(!names(r.calls).includes("terminate"));
  assert.ok(!names(r.calls).includes("suspend"), "no power action on consent that was never given for it");
});

/** Correction 3: the relaunch rule is an allow-list, proved before the journey exists.
 *
 * This is deliberately testing an intent the contract does not yet carry. The
 * old condition was `intent !== "sleep"`, so a shutdown would have inherited a
 * relaunch and reopened the game seconds before the machine powered off. The
 * test exists now so that adding the shutdown journey cannot quietly enable it:
 * whoever adds it has to add the intent to REOPEN_AFTER on purpose, and this
 * test fails if they do so without thinking about it.
 */
test("a shutdown-shaped intent never reopens the game", async () => {
  const r = rig({ closesAfter: 2 });
  const result = await runDisconnectWithGameClose(
    { appId: APP, intent: "shutdown", releaseDisplay: false, remember: false, relaunch: true },
    r.ports,
  );

  assert.equal(result.gameClosed, true, "the game still closes for a shutdown");
  assert.equal(result.relaunched, false);
  assert.ok(
    !names(r.calls).includes("relaunch"),
    "a shutdown must never reopen the game: nothing comes back afterwards to finish the job",
  );
  // The wish is still recorded with the removal, so it is not silently dropped
  // either -- it simply is not acted on now.
  assert.deepEqual(r.calls.find((c) => c[0] === "disconnect"), ["disconnect", false, APP, "shutdown"]);
});

test("an intent nobody has named yet also does not reopen", async () => {
  const r = rig({ closesAfter: 2 });
  const result = await runDisconnectWithGameClose(
    { appId: APP, intent: "reboot-for-firmware", releaseDisplay: false, remember: false, relaunch: true },
    r.ports,
  );
  assert.equal(result.relaunched, false, "an allow-list means an unknown intent defaults to not reopening");
  assert.ok(!names(r.calls).includes("relaunch"));
});

test("the disconnect destination still reopens, so the allow-list is not vacuous", async () => {
  const r = rig({ closesAfter: 2 });
  const result = await runDisconnectWithGameClose(
    { appId: APP, intent: "disconnect", releaseDisplay: false, remember: false, relaunch: true },
    r.ports,
  );
  assert.equal(result.relaunched, true);
  assert.deepEqual(r.calls.find((c) => c[0] === "relaunch"), ["relaunch", APP]);
});
