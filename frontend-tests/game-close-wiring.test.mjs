/** The gates between a press and the device.
 *
 * `game-close-flow.test.mjs` covers the flow's own sequence. This covers what
 * the wiring adds in front of it, and every test here is a way the panel could
 * remove an eGPU or sleep a handheld that it had no permission to touch.
 *
 * The rig records every port call in order, so "nothing happened" is asserted
 * as an empty or short call list rather than as an absent side effect nobody
 * looked for.
 */

import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const load = (name) => {
  const source = readFileSync(
    new URL(`../src/${name}.ts`, import.meta.url),
    "utf8",
  );
  // Strips single- and multi-line imports alike: these modules are concatenated
  // in dependency order, so every specifier is already in scope.
  const stripped = source.replace(/^import\s[\s\S]*?;\s*$/gm, "");
  return ts.transpileModule(stripped, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
};

const bundle =
  load("egpu-disconnect-tile") +
  load("game-close-flow") +
  load("quick-access/game-close-wiring");
const {
  runGameClosePress,
  claimRelaunchOnMount,
  pressFromDialog,
  closableAppId,
  gameCloseWiringMessage,
  disconnectPresentation,
} = await import(
  `data:text/javascript;base64,${Buffer.from(bundle).toString("base64")}`
);

const APP = "1145360";
const OTHER_APP = "620";

const game = (over = {}) => ({
  app_id: APP,
  title: "Hades",
  save_capability: "verified_save_on_exit",
  egpu_handoff: "",
  save_known: true,
  identity_exact: true,
  ...over,
});

const prompt = (over = {}) => ({
  schema_version: 1,
  decision: "confirm",
  code: "game_close.confirm_required",
  intent: "disconnect",
  may_proceed: false,
  progress_at_risk: false,
  save_known: true,
  remember_offered: true,
  relaunch_offered: true,
  relaunch_requested: false,
  ...over,
});

/** A game is running on the eGPU and the backend is asking about it. */
const running = (over = {}) => ({
  schema_version: 1,
  availability: "attemptable",
  code: "removal_safety.game_running",
  ready: false,
  attemptable: true,
  busy: false,
  holders: ["gamescope"],
  scan_complete: true,
  external_display_committed: false,
  display_release_required: false,
  game: game(),
  close_prompt: prompt(),
  last: null,
  ...over,
});

/** The backend reports, over a finished scan, that nothing is left to close. */
const cleared = (over = {}) =>
  running({
    availability: "ready",
    code: "removal_safety.clear",
    ready: true,
    holders: [],
    game: null,
    close_prompt: prompt({
      decision: "nothing_to_close",
      code: "game_close.nothing_running",
      may_proceed: true,
      remember_offered: false,
      relaunch_offered: false,
    }),
    ...over,
  });

const outcome = (over = {}) => ({
  schema_version: 1,
  stage: "removed",
  code: "live_disconnect.removed",
  ok: true,
  released: true,
  session_disturbed: true,
  removed: ["0000:08:00.0"],
  restored: [],
  display_released: [],
  display_release_code: "display_release.not_required",
  filter_disarmed: true,
  device_disturbed: false,
  ...over,
});

const readiness = (over = {}) => ({
  schema_version: 1,
  code: "sleep.requires_disconnect",
  requires_disconnect: true,
  game: game(),
  // Re-derived for the sleep intent: agreeing a game may close for a
  // disconnect is not agreeing it may close for a sleep.
  close_prompt: prompt({ intent: "sleep" }),
  disconnect: running(),
  ...over,
});

/** Records every port call in order.
 *
 * `statuses` is consumed one entry per `readStatus`: the first is the press's
 * own fresh reading, the rest are the flow polling for the game to be gone.
 * The last entry repeats, so a status that never clears produces a timeout.
 */
function rig({
  statuses = [running(), cleared()],
  sleep = readiness(),
  disconnectOutcome = outcome(),
  disconnectThrows = false,
  pendingRelaunch = "",
  throwOn = null,
  rememberResult = { ok: true, code: "game_close.stored" },
} = {}) {
  const calls = [];
  let index = 0;
  let clock = 0;
  // Stands in for the backend's durable record: written by the disconnect,
  // consumed exactly once by claiming.
  let recorded = pendingRelaunch;
  const ports = {
    async readStatus() {
      calls.push(["readStatus"]);
      if (throwOn === "readStatus") throw new Error("rpc down");
      return statuses[Math.min(index++, statuses.length - 1)];
    },
    async readSleepReadiness() {
      calls.push(["readSleepReadiness"]);
      if (throwOn === "readSleepReadiness") throw new Error("rpc down");
      return sleep;
    },
    async terminateGame(appId) {
      calls.push(["terminateGame", appId]);
      if (throwOn === "terminateGame") throw new Error("no steam");
    },
    async disconnect(releaseDisplay, relaunchAppId, relaunchIntent) {
      calls.push(["disconnect", releaseDisplay, relaunchAppId, relaunchIntent]);
      if (disconnectThrows) throw new Error("transport");
      if (relaunchAppId) recorded = relaunchAppId;
      return disconnectOutcome;
    },
    async relaunchGame(appId) {
      calls.push(["relaunchGame", appId]);
      if (throwOn === "relaunchGame") throw new Error("no steam");
    },
    async takePendingRelaunch() {
      calls.push(["takePendingRelaunch"]);
      if (throwOn === "takePendingRelaunch") throw new Error("rpc down");
      const claimed = recorded;
      recorded = "";
      return {
        steam_app_id: claimed,
        code: claimed ? "relaunch.approved" : "relaunch.nothing_recorded",
      };
    },
    async rememberChoice(appId, skipConfirmation, relaunchAfter) {
      calls.push(["rememberChoice", appId, skipConfirmation, relaunchAfter]);
      if (throwOn === "rememberChoice") throw new Error("refused");
      return rememberResult;
    },
    async suspend() {
      calls.push(["suspend"]);
      if (throwOn === "suspend") throw new Error("no suspend");
    },
    async wait(ms) {
      clock += ms;
    },
    now() {
      return clock;
    },
  };
  return { calls, ports, names: () => calls.map((c) => c[0]) };
}

const press = (over = {}) => ({
  intent: "disconnect",
  appId: APP,
  confirmed: true,
  gameCloseAnswered: true,
  remember: false,
  relaunch: false,
  releaseDisplay: false,
  ...over,
});

// ---------------------------------------------------------------------------
// Cancellation
// ---------------------------------------------------------------------------

test("a cancelled press performs no action whatsoever", async () => {
  // Not a terminate, not a disconnect, and not a stored preference either: an
  // answer of "no" that still writes something down outlives the press.
  const r = rig();
  const result = await runGameClosePress(press({ confirmed: false }), r.ports);
  assert.equal(result.code, "wiring.cancelled");
  assert.equal(result.ok, false);
  assert.equal(result.refusedBeforeAction, true);
  assert.deepEqual(r.calls, []);
});

test("a cancelled sleep never suspends and never even asks", async () => {
  const r = rig();
  const result = await runGameClosePress(
    press({ intent: "sleep", confirmed: false }),
    r.ports,
  );
  assert.equal(result.code, "wiring.cancelled");
  assert.deepEqual(r.calls, []);
});

test("a cancel after the dialog was shown is still a cancel", async () => {
  const view = disconnectPresentation(running());
  const built = pressFromDialog(view, "disconnect", {
    confirmed: false,
    remember: true,
    relaunch: true,
  });
  // Ticking the boxes and then dismissing is not consent to either.
  assert.equal(built.confirmed, false);
  assert.equal(built.gameCloseAnswered, false);
  assert.equal(built.remember, false);
  assert.equal(built.relaunch, false);
  const r = rig();
  assert.equal((await runGameClosePress(built, r.ports)).code, "wiring.cancelled");
  assert.deepEqual(r.calls, []);
});

// ---------------------------------------------------------------------------
// Consent: per game and per intent
// ---------------------------------------------------------------------------

test("a confirm decision with no answered dialog closes nothing", async () => {
  // The panel rendered while the answer was remembered and the backend is
  // asking again by the press. There is no answer to the question being asked.
  const r = rig();
  const result = await runGameClosePress(
    press({ gameCloseAnswered: false }),
    r.ports,
  );
  assert.equal(result.code, "wiring.consent_required");
  assert.equal(result.refusedBeforeAction, true);
  assert.deepEqual(r.names(), ["readStatus"]);
});

test("a remembered decision proceeds without a dialog", async () => {
  const remembered = prompt({
    decision: "remembered",
    code: "game_close.remembered",
    may_proceed: true,
  });
  const r = rig({
    statuses: [running({ close_prompt: remembered }), cleared()],
  });
  const result = await runGameClosePress(
    press({ gameCloseAnswered: false }),
    r.ports,
  );
  assert.equal(result.ok, true);
  assert.equal(result.gameClosed, true);
  assert.ok(r.names().includes("terminateGame"));
  assert.ok(r.names().includes("disconnect"));
});

test("a remembered decision that also says it must ask is a disagreement", async () => {
  // A prompt claiming a standing answer while saying interaction is still
  // needed disagrees with itself. A disagreement about someone's unsaved
  // progress is resolved by asking, not by picking the convenient half.
  const r = rig({
    statuses: [
      running({
        close_prompt: prompt({ decision: "remembered", may_proceed: false }),
      }),
    ],
  });
  const result = await runGameClosePress(
    press({ gameCloseAnswered: false }),
    r.ports,
  );
  assert.equal(result.code, "wiring.consent_contradictory");
  assert.deepEqual(r.names(), ["readStatus"]);
});

test("consent given for a disconnect does not authorise a sleep", async () => {
  // The sleep readiness carries a prompt re-derived for sleeping. A prompt
  // still describing the disconnect cannot judge the press the player made.
  const r = rig({ sleep: readiness({ close_prompt: prompt({ intent: "disconnect" }) }) });
  const result = await runGameClosePress(press({ intent: "sleep" }), r.ports);
  assert.equal(result.code, "wiring.intent_mismatch");
  assert.ok(!r.names().includes("terminateGame"));
  assert.ok(!r.names().includes("suspend"));
});

test("a sleep with its own re-derived consent runs and then suspends", async () => {
  const r = rig({ statuses: [running(), cleared()] });
  const result = await runGameClosePress(press({ intent: "sleep" }), r.ports);
  assert.equal(result.ok, true);
  assert.equal(result.code, "flow.slept");
  // The order is the safety argument: the suspend is last, after the removal.
  const names = r.names();
  assert.ok(names.indexOf("disconnect") < names.indexOf("suspend"));
  // Sleeping does not reopen the game before the machine goes off.
  assert.ok(!names.includes("relaunchGame"));
});

test("a missing prompt is not permission", async () => {
  const r = rig({ statuses: [running({ close_prompt: null })] });
  const result = await runGameClosePress(press(), r.ports);
  // Silence from the backend about a game it can see is not a yes.
  assert.equal(result.code, "wiring.close_prompt_unavailable");
  assert.deepEqual(r.names(), ["readStatus"]);
});

test("the remember box is only ever sent when it was offered", async () => {
  // Null label means the catalog says closing loses progress, so the choice
  // must not be offered at all -- and must not arrive from a panel either.
  const view = disconnectPresentation(
    running({
      game: game({ save_capability: "manual_save_required" }),
      close_prompt: prompt({ remember_offered: false, relaunch_offered: false }),
    }),
  );
  assert.equal(view.dialog.rememberLabel, null);
  const built = pressFromDialog(view, "disconnect", {
    confirmed: true,
    remember: true,
    relaunch: true,
  });
  assert.equal(built.remember, false);
  assert.equal(built.relaunch, false);
});

test("a stored reopen wish is honoured even with no dialog to tick", async () => {
  // A `remembered` decision draws no dialog, so the tick box the player used
  // on an earlier press does not exist now. The wish is the backend's record.
  const r = rig({
    statuses: [
      running({
        close_prompt: prompt({
          decision: "remembered",
          may_proceed: true,
          relaunch_requested: true,
        }),
      }),
      cleared(),
    ],
  });
  const result = await runGameClosePress(
    press({ gameCloseAnswered: false, relaunch: false }),
    r.ports,
  );
  assert.equal(result.ok, true);
  const sent = r.calls.find((c) => c[0] === "disconnect");
  assert.deepEqual(sent, ["disconnect", false, APP, "disconnect"]);
  assert.equal(result.relaunched, true);
});

// ---------------------------------------------------------------------------
// Game-exit verification
// ---------------------------------------------------------------------------

test("a game already gone is not closed again", async () => {
  // Nothing to close, so nothing is terminated and no reopen is recorded.
  const view = disconnectPresentation(cleared());
  assert.equal(view.closesGame, false);
  assert.equal(view.dialog, null);
  const built = pressFromDialog(view, "disconnect", { confirmed: true });
  assert.equal(built.appId, null);
  const r = rig({ statuses: [cleared()] });
  const result = await runGameClosePress(built, r.ports);
  assert.equal(result.ok, true);
  assert.equal(result.gameClosed, false);
  assert.ok(!r.names().includes("terminateGame"));
  assert.deepEqual(r.calls.find((c) => c[0] === "disconnect"), [
    "disconnect",
    false,
    "",
    "disconnect",
  ]);
});

test("a close Steam refuses removes nothing", async () => {
  const r = rig({ throwOn: "terminateGame" });
  const result = await runGameClosePress(press(), r.ports);
  assert.equal(result.code, "flow.close_request_failed");
  assert.equal(result.ok, false);
  // The game may still be running, so the device is left alone.
  assert.ok(!r.names().includes("disconnect"));
});

test("a game that will not exit is never escalated and nothing is removed", async () => {
  // The status never clears. No harder kill, no removal underneath it: a game
  // that will not exit gracefully is a game with something to lose.
  const r = rig({ statuses: [running(), running()] });
  const result = await runGameClosePress(press(), r.ports);
  assert.equal(result.code, "flow.game_did_not_close");
  assert.ok(!r.names().includes("disconnect"));
  assert.equal(r.names().filter((n) => n === "terminateGame").length, 1);
});

test("a different game appearing mid-flow stops the removal", async () => {
  // The agreed game exits and another starts while the flow is still waiting.
  // The status reports a game to close rather than a clear device, so the
  // deadline is reached and nothing is removed. Identity is re-read, never
  // assumed from the terminate having returned.
  const swapped = running({
    game: game({ app_id: OTHER_APP, title: "Portal 2" }),
  });
  const r = rig({ statuses: [running(), swapped] });
  const result = await runGameClosePress(press(), r.ports);
  assert.equal(result.ok, false);
  assert.equal(result.code, "flow.game_did_not_close");
  assert.ok(!r.names().includes("disconnect"));
  assert.ok(!r.names().includes("relaunchGame"));
});

test("a different game at the press closes nothing at all", async () => {
  // The dialog was about one game; another is running by the time it is
  // confirmed. The consent on hand does not cover what is running.
  const r = rig({
    statuses: [running({ game: game({ app_id: OTHER_APP, title: "Portal 2" }) })],
  });
  const result = await runGameClosePress(press({ appId: APP }), r.ports);
  assert.equal(result.code, "wiring.game_changed");
  assert.equal(result.refusedBeforeAction, true);
  assert.deepEqual(r.names(), ["readStatus"]);
});

test("an identity that stopped being exact closes nothing", async () => {
  // Something is rendering that could not be named. It still has a save to
  // lose; it just cannot be matched to the answer the player gave.
  const r = rig({
    statuses: [running({ game: game({ identity_exact: false }) })],
  });
  const result = await runGameClosePress(press({ appId: APP }), r.ports);
  assert.equal(result.code, "wiring.game_changed");
  assert.deepEqual(r.names(), ["readStatus"]);
});

test("an unnamed game is never promised a close or a reopen", async () => {
  const view = disconnectPresentation(
    running({ game: game({ identity_exact: false }) }),
  );
  assert.equal(view.dialog.canCloseGame, false);
  assert.equal(closableAppId(view), null);
  const built = pressFromDialog(view, "disconnect", {
    confirmed: true,
    relaunch: true,
  });
  assert.equal(built.appId, null);
  assert.equal(built.relaunch, false);
  // The backend stays the authority on the removal itself.
  const r = rig({ statuses: [running({ game: game({ identity_exact: false }) })] });
  const result = await runGameClosePress(built, r.ports);
  assert.ok(!r.names().includes("terminateGame"));
  assert.deepEqual(r.calls.find((c) => c[0] === "disconnect"), [
    "disconnect",
    false,
    "",
    "disconnect",
  ]);
  assert.equal(result.gameClosed, false);
});

// ---------------------------------------------------------------------------
// Stale and unavailable readings at the press
// ---------------------------------------------------------------------------

test("an unreadable status removes nothing", async () => {
  const r = rig({ throwOn: "readStatus" });
  const result = await runGameClosePress(press(), r.ports);
  assert.equal(result.code, "wiring.status_unavailable");
  assert.deepEqual(r.names(), ["readStatus"]);
});

test("a half-detached device refuses the press and asks for a person", async () => {
  const r = rig({
    statuses: [
      running({
        availability: "recovery_required",
        code: "removal_transaction.partially_detached",
      }),
    ],
  });
  const result = await runGameClosePress(press(), r.ports);
  assert.equal(result.code, "wiring.needs_attention");
  assert.deepEqual(r.names(), ["readStatus"]);
  assert.match(gameCloseWiringMessage(result), /unexpected state/i);
});

test("a disconnect already running is not joined by a second one", async () => {
  const r = rig({ statuses: [running({ availability: "busy", busy: true })] });
  const result = await runGameClosePress(press(), r.ports);
  assert.equal(result.code, "wiring.busy");
  assert.deepEqual(r.names(), ["readStatus"]);
});

test("a reading that is no longer attemptable removes nothing", async () => {
  const r = rig({
    statuses: [
      running({
        availability: "blocked",
        attemptable: false,
        code: "removal_safety.client_scan_incomplete",
      }),
    ],
  });
  const result = await runGameClosePress(press(), r.ports);
  assert.equal(result.code, "wiring.not_attemptable");
  assert.deepEqual(r.names(), ["readStatus"]);
});

test("turning the display off needs its own approval", async () => {
  // Visible to whoever is watching the TV, who pressed nothing.
  const r = rig({ statuses: [running({ display_release_required: true })] });
  const result = await runGameClosePress(
    press({ releaseDisplay: false }),
    r.ports,
  );
  assert.equal(result.code, "wiring.display_approval_required");
  assert.deepEqual(r.names(), ["readStatus"]);
});

test("the display approval is passed through exactly as given", async () => {
  const r = rig({
    statuses: [running({ display_release_required: true }), cleared()],
  });
  await runGameClosePress(press({ releaseDisplay: true }), r.ports);
  assert.deepEqual(r.calls.find((c) => c[0] === "disconnect"), [
    "disconnect",
    true,
    "",
    "disconnect",
  ]);
});

// ---------------------------------------------------------------------------
// No power action after a failed prerequisite
// ---------------------------------------------------------------------------

test("a sleep whose game will not close never suspends", async () => {
  const r = rig({ statuses: [running(), running()] });
  const result = await runGameClosePress(press({ intent: "sleep" }), r.ports);
  assert.equal(result.code, "flow.game_did_not_close");
  assert.ok(!r.names().includes("suspend"));
  assert.ok(!r.names().includes("disconnect"));
});

test("a sleep whose disconnect failed never suspends", async () => {
  const r = rig({
    statuses: [running(), cleared()],
    disconnectOutcome: outcome({ ok: false, code: "live_disconnect.declined" }),
  });
  const result = await runGameClosePress(press({ intent: "sleep" }), r.ports);
  assert.equal(result.ok, false);
  // Sleeping with the eGPU still attached is the state the guard exists for.
  assert.ok(!r.names().includes("suspend"));
});

test("a sleep whose disconnect threw never suspends and puts the game back", async () => {
  const r = rig({ statuses: [running(), cleared()], disconnectThrows: true });
  const result = await runGameClosePress(
    press({ intent: "sleep", relaunch: true }),
    r.ports,
  );
  assert.equal(result.code, "flow.disconnect_failed");
  assert.ok(!r.names().includes("suspend"));
  // A sleep that never happened leaves the player awake with a closed game.
  assert.equal(result.relaunched, true);
});

test("unknown sleep readiness leaves the handheld awake and attached", async () => {
  const r = rig({
    sleep: readiness({ code: "sleep.readiness_unknown", requires_disconnect: true }),
  });
  const result = await runGameClosePress(press({ intent: "sleep" }), r.ports);
  assert.equal(result.code, "wiring.sleep_readiness_unknown");
  assert.deepEqual(r.names(), ["readSleepReadiness"]);
  assert.ok(!r.names().includes("suspend"));
});

test("an unreadable sleep readiness leaves the handheld awake", async () => {
  const r = rig({ throwOn: "readSleepReadiness" });
  const result = await runGameClosePress(press({ intent: "sleep" }), r.ports);
  assert.equal(result.code, "wiring.sleep_readiness_unavailable");
  assert.deepEqual(r.names(), ["readSleepReadiness"]);
});

test("a sleep that needs no disconnect does not remove the eGPU", async () => {
  // Removing a device nobody asked about is not a smaller harm than refusing.
  // Display return, sleep and shutdown are distinct journeys.
  const r = rig({
    sleep: readiness({ code: "sleep.available", requires_disconnect: false }),
  });
  const result = await runGameClosePress(press({ intent: "sleep" }), r.ports);
  assert.equal(result.code, "wiring.sleep_needs_no_disconnect");
  assert.deepEqual(r.names(), ["readSleepReadiness"]);
  assert.ok(!r.names().includes("disconnect"));
  assert.ok(!r.names().includes("suspend"));
});

test("a failed suspend is reported without claiming the handheld slept", async () => {
  const r = rig({ statuses: [running(), cleared()], throwOn: "suspend" });
  const result = await runGameClosePress(press({ intent: "sleep" }), r.ports);
  assert.equal(result.code, "flow.suspend_failed");
  assert.equal(result.ok, false);
  assert.match(gameCloseWiringMessage(result), /did not sleep the handheld/i);
});

test("a half-detached outcome is attention, and no game is launched into it", async () => {
  const r = rig({
    statuses: [running(), cleared()],
    disconnectOutcome: outcome({ ok: false, device_disturbed: true }),
  });
  const result = await runGameClosePress(press({ relaunch: true }), r.ports);
  assert.equal(result.attention, true);
  assert.equal(result.relaunched, false);
  // The record is not even claimed, so it cannot fire later into that state.
  assert.ok(!r.names().includes("takePendingRelaunch"));
  assert.ok(!r.names().includes("relaunchGame"));
});

// ---------------------------------------------------------------------------
// The player's answer is stored before it is acted on
// ---------------------------------------------------------------------------

test("the remembered answer is stored before anything is done with it", async () => {
  const r = rig({ statuses: [running(), cleared()] });
  await runGameClosePress(
    press({ remember: true, relaunch: true }),
    r.ports,
  );
  const names = r.names();
  assert.ok(names.indexOf("rememberChoice") < names.indexOf("terminateGame"));
  assert.deepEqual(r.calls.find((c) => c[0] === "rememberChoice"), [
    "rememberChoice",
    APP,
    true,
    true,
  ]);
});

test("a refused preference does not stop the disconnect the player pressed", async () => {
  const r = rig({
    statuses: [running(), cleared()],
    throwOn: "rememberChoice",
  });
  const result = await runGameClosePress(press({ remember: true }), r.ports);
  // Being asked again next time is the harmless failure.
  assert.equal(result.ok, true);
  assert.ok(r.names().includes("disconnect"));
});

// ---------------------------------------------------------------------------
// The mount-time pending relaunch claim
// ---------------------------------------------------------------------------

test("a pending relaunch is claimed and performed on mount", async () => {
  // The regression this exists for: the session restart that frees the eGPU
  // destroys the panel that asked for the reopen, so the panel that comes up
  // afterwards is the one that has to do it. Without this the game never
  // returns and the record quietly expires.
  const r = rig({ statuses: [cleared()], pendingRelaunch: APP });
  const result = await claimRelaunchOnMount(r.ports);
  assert.equal(result.appId, APP);
  assert.equal(result.code, "wiring.mount_relaunched");
  assert.equal(result.deferred, false);
  assert.deepEqual(r.names(), [
    "readStatus",
    "takePendingRelaunch",
    "relaunchGame",
  ]);
});

test("claiming on mount consumes the record exactly once", async () => {
  const r = rig({ statuses: [cleared()], pendingRelaunch: APP });
  assert.equal((await claimRelaunchOnMount(r.ports)).appId, APP);
  const second = await claimRelaunchOnMount(r.ports);
  assert.equal(second.appId, null);
  assert.equal(second.code, "wiring.mount_nothing_claimed");
  assert.equal(r.names().filter((n) => n === "relaunchGame").length, 1);
});

test("mounting with nothing recorded does nothing and says so", async () => {
  const r = rig({ statuses: [cleared()], pendingRelaunch: "" });
  const result = await claimRelaunchOnMount(r.ports);
  assert.equal(result.appId, null);
  assert.equal(result.code, "wiring.mount_nothing_claimed");
  assert.equal(result.deferred, false);
  assert.ok(!r.names().includes("relaunchGame"));
});

test("a half-detached device is never launched into on mount", async () => {
  // The record is left unclaimed rather than consumed, so it is not burned on
  // a state that needs a person.
  const r = rig({
    statuses: [
      cleared({
        availability: "recovery_required",
        code: "removal_transaction.partially_detached",
      }),
    ],
    pendingRelaunch: APP,
  });
  const result = await claimRelaunchOnMount(r.ports);
  assert.equal(result.appId, null);
  assert.equal(result.code, "wiring.mount_device_disturbed");
  assert.equal(result.deferred, true);
  assert.deepEqual(r.names(), ["readStatus"]);
});

test("mounting while a disconnect runs leaves the record to that disconnect", async () => {
  // Claiming underneath a running disconnect races it for the same game.
  const r = rig({
    statuses: [cleared({ availability: "busy", busy: true })],
    pendingRelaunch: APP,
  });
  const result = await claimRelaunchOnMount(r.ports);
  assert.equal(result.code, "wiring.mount_busy");
  assert.equal(result.deferred, true);
  assert.deepEqual(r.names(), ["readStatus"]);
});

test("a busy flag without a busy availability still defers", async () => {
  const r = rig({
    statuses: [cleared({ busy: true })],
    pendingRelaunch: APP,
  });
  const result = await claimRelaunchOnMount(r.ports);
  assert.equal(result.code, "wiring.mount_busy");
  assert.ok(!r.names().includes("takePendingRelaunch"));
});

test("an unreadable status on mount leaves the record for the next mount", async () => {
  // Not reopening a game is recoverable. Reopening it onto a half-detached
  // eGPU is not, and an unreadable status cannot tell the two apart.
  const r = rig({ throwOn: "readStatus", pendingRelaunch: APP });
  const result = await claimRelaunchOnMount(r.ports);
  assert.equal(result.appId, null);
  assert.equal(result.code, "wiring.mount_status_unknown");
  assert.equal(result.deferred, true);
  assert.deepEqual(r.names(), ["readStatus"]);
});

test("a relaunch Steam refuses is reported, not claimed twice", async () => {
  const r = rig({
    statuses: [cleared()],
    pendingRelaunch: APP,
    throwOn: "relaunchGame",
  });
  const result = await claimRelaunchOnMount(r.ports);
  assert.equal(result.appId, null);
  assert.equal(result.code, "wiring.mount_nothing_claimed");
  // Consumed on refusal too, so a relaunch that happens cannot happen twice.
  assert.ok(r.names().includes("takePendingRelaunch"));
});

// ---------------------------------------------------------------------------
// What the player is told
// ---------------------------------------------------------------------------

test("no refusal message implies unplugging is safe", async () => {
  const codes = [
    "wiring.cancelled",
    "wiring.status_unavailable",
    "wiring.sleep_readiness_unavailable",
    "wiring.sleep_readiness_unknown",
    "wiring.sleep_needs_no_disconnect",
    "wiring.needs_attention",
    "wiring.busy",
    "wiring.not_attemptable",
    "wiring.close_prompt_unavailable",
    "wiring.intent_mismatch",
    "wiring.consent_required",
    "wiring.consent_contradictory",
    "wiring.game_changed",
    "wiring.display_approval_required",
  ];
  for (const code of codes) {
    const message = gameCloseWiringMessage({
      ok: false,
      code,
      flow: null,
      outcome: null,
      gameClosed: false,
      relaunched: false,
      attention: false,
      refusedBeforeAction: true,
    });
    assert.ok(message.length > 0, code);
    // Every refusal must read as a refusal, and none may describe the cable.
    assert.doesNotMatch(message, /safe to (unplug|disconnect|remove)/i, code);
    assert.doesNotMatch(message, /you can now unplug|safely unplug/i, code);
  }
});

test("a successful flow keeps the owning module's cable sentence", async () => {
  const r = rig({ statuses: [running(), cleared()] });
  const result = await runGameClosePress(press(), r.ports);
  assert.equal(result.ok, true);
  // Passed through from closeFlowMessage rather than restated here.
  assert.match(gameCloseWiringMessage(result), /does not make unplugging safe/i);
});

test("an unmapped code quotes itself rather than inventing a sentence", async () => {
  const message = gameCloseWiringMessage({
    ok: false,
    code: "wiring.something_new",
    flow: null,
    outcome: null,
    gameClosed: false,
    relaunched: false,
    attention: false,
    refusedBeforeAction: true,
  });
  assert.match(message, /wiring\.something_new/);
});
