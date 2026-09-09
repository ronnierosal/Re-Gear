import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(
  new URL("../src/egpu-disconnect-tile.ts", import.meta.url),
  "utf8",
).replace(/^import type [\s\S]*?;$/m, "");
const js = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { disconnectPresentation, gameCloseDialog, outcomeNeedsAttention } =
  await import("data:text/javascript;base64," + Buffer.from(js).toString("base64"));

const status = (over = {}) => ({
  schema_version: 1,
  availability: "ready",
  code: "removal_safety.ready_for_supervised_removal",
  ready: true,
  attemptable: true,
  busy: false,
  holders: [],
  scan_complete: true,
  external_display_committed: false,
  display_release_required: false,
  game: null,
  close_prompt: nothingToClose,
  last: null,
  ...over,
});

const nothingToClose = {
  schema_version: 1,
  decision: "nothing_to_close",
  code: "game_close.no_game_running",
  intent: "disconnect",
  may_proceed: true,
  progress_at_risk: false,
  save_known: false,
  remember_offered: false,
  relaunch_offered: false,
  relaunch_requested: false,
};

const prompt = (over = {}) => ({
  ...nothingToClose,
  decision: "confirm",
  code: "game_close.confirmation_required",
  may_proceed: false,
  remember_offered: true,
  relaunch_offered: true,
  ...over,
});

const hades = (over = {}) => ({
  app_id: "1145360",
  title: "Hades",
  save_capability: "untested",
  egpu_handoff: "untested",
  save_known: false,
  identity_exact: true,
  ...over,
});

/** A running game: blocked on removal safety, offered by the flow. */
const running = (over = {}, gameOver = {}) =>
  status({
    availability: "blocked",
    ready: false,
    attemptable: false,
    code: "removal_safety.game_running",
    game: hades(gameOver),
    close_prompt: prompt(over),
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
    status({ availability: "attemptable", ready: false, code: "removal_safety.external_display_still_active", display_release_required: true }),
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
    status({ availability: "recovery_required", code: "removal_transaction.partially_detached", ready: false, attemptable: false }),
  );

  assert.equal(view.attention, true);
  assert.equal(view.available, false);
  assert.equal(view.actionLabel, null);
  assert.match(view.reason, /half detached/i);
});

test("a blocked device explains itself in words, never a raw code", () => {
  const view = disconnectPresentation(
    status({ availability: "blocked", ready: false, attemptable: false, code: "removal_safety.clients_active_or_protected" }),
  );

  assert.equal(view.available, false);
  assert.equal(view.reason, "Something is still using the eGPU.");
});

test("an unmapped code still produces something a bug report can act on", () => {
  const view = disconnectPresentation(
    status({ availability: "blocked", ready: false, attemptable: false, code: "removal_safety.some_future_fact" }),
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
      attemptable: false,
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
  const view = disconnectPresentation(status({ availability: "ready", ready: false, attemptable: false }));
  assert.equal(view.available, false);
});

test("busy is not an error and offers nothing to press", () => {
  const view = disconnectPresentation(status({ availability: "busy", ready: false, attemptable: false, code: "live_disconnect.busy" }));

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

test("an attemptable device says it will try, not that it will succeed", () => {
  // Removal safety declines before any release, so offering the action only on
  // ready would tell a player their eGPU can never be disconnected.
  const view = disconnectPresentation(
    status({ availability: "attemptable", ready: false, code: "removal_safety.clients_active_or_protected" }),
  );

  assert.equal(view.available, true);
  assert.equal(view.actionLabel, "Disconnect");
  assert.match(view.confirmation, /will try to free the eGPU/i);
  assert.match(view.confirmation, /Keep the cable connected/i);
});

test("a ready device does not hedge its confirmation", () => {
  const view = disconnectPresentation(status());
  assert.doesNotMatch(view.confirmation, /will try/i);
});

test("a running game is named, because 'close the running game' is not actionable", () => {
  // A player looking at a Steam overlay cannot see which game holds the eGPU.
  const view = disconnectPresentation(running());

  assert.equal(view.available, true);
  assert.equal(view.value, "Close game");
  assert.match(view.dialog.title, /Hades/);
  assert.match(view.dialog.body, /^Hades is using the eGPU/);
  assert.equal(view.game.app_id, "1145360");
});

test("an untested game is told to save, never reassured", () => {
  const view = disconnectPresentation(running());

  assert.match(view.dialog.body, /cannot confirm this game saves/i);
  assert.doesNotMatch(view.dialog.body, /saves your progress/i);
});

test("a game known to save on exit says so", () => {
  const view = disconnectPresentation(
    running({ save_known: true }, { save_capability: "verified_save_on_exit", save_known: true }),
  );

  assert.match(view.dialog.body, /saves your progress/i);
});

test("a game needing a manual save says that plainly", () => {
  for (const capability of ["manual_save_required", "manual_save_recommended"]) {
    const view = disconnectPresentation(
      running({ save_known: true }, { save_capability: capability, save_known: true }),
    );
    assert.match(view.dialog.body, /Save your progress first/i);
  }
});

test("a game the backend named but the panel cannot still gets a dialog", () => {
  // The status says a game is running; the game record is missing. Offering
  // nothing would leave a player with a tile that refuses forever.
  const view = disconnectPresentation(
    status({ availability: "blocked", ready: false, attemptable: false,
             code: "removal_safety.game_running", game: null,
             close_prompt: prompt({ code: "game_close.identity_unverified",
                                    remember_offered: false, relaunch_offered: false }) }),
  );

  assert.equal(view.available, true);
  assert.equal(view.closesGame, true);
  assert.match(view.dialog.body, /^A game is using the eGPU/);
  assert.equal(view.dialog.rememberLabel, null);
});

test("a running game with no prompt at all is still not treated as idle", () => {
  // A backend mid-upgrade: the readiness code names a game, the prompt field
  // is absent. The safe reading of that disagreement is that a game closes.
  const view = disconnectPresentation(
    status({ availability: "blocked", ready: false, attemptable: false,
             code: "removal_safety.game_running", game: null, close_prompt: null }),
  );

  assert.equal(view.closesGame, true);
  assert.match(view.confirmation, /will close the running game/i);
});

test("only a disturbed device raises an alert after an attempt", () => {
  assert.equal(outcomeNeedsAttention(null), false);
  assert.equal(outcomeNeedsAttention({ device_disturbed: false }), false);
  assert.equal(outcomeNeedsAttention({ device_disturbed: true }), true);
});

test("a running game is offered, not reported as a dead end", () => {
  // The exact trap that `attemptable` was added for, in a new guise: removal
  // safety declines while a game holds the eGPU, and closing that game is
  // what the flow does. Refusing here would decline the action at the only
  // moment a player wants it.
  const view = disconnectPresentation(running());

  assert.equal(view.available, true);
  assert.equal(view.actionLabel, "Disconnect");
  assert.equal(view.closesGame, true);
  assert.equal(view.reason, null);
});

test("the confirmation names the game it is about to close", () => {
  const view = disconnectPresentation(running());

  assert.match(view.confirmation, /close Hades/i);
  assert.match(view.confirmation, /Steam session will restart/i);
  assert.match(view.confirmation, /Keep the cable connected/i);
});

test("the dialog says what closing an untested game costs", () => {
  const view = disconnectPresentation(running());

  assert.match(view.dialog.title, /Hades/);
  assert.match(view.dialog.body, /cannot confirm this game saves/i);
  assert.doesNotMatch(view.dialog.body, /safe to unplug|you can unplug/i);
  assert.match(view.dialog.body, /Keep the cable connected/i);
});

test("the do-not-ask-again box names one game, never all games", () => {
  // The player agreed about this game. Wording that reads as a global setting
  // would collect consent they did not give.
  const view = disconnectPresentation(running());

  assert.equal(view.dialog.rememberLabel, "Don't ask again for Hades");
  assert.equal(view.dialog.relaunchLabel, "Reopen Hades afterwards");
});

test("a game known to lose progress is never offered the checkbox", () => {
  const view = disconnectPresentation(
    running(
      { remember_offered: false, progress_at_risk: true, save_known: true },
      { save_capability: "manual_save_required" },
    ),
  );

  assert.equal(view.dialog.rememberLabel, null);
  assert.equal(view.dialog.progressAtRisk, true);
  assert.match(view.dialog.body, /Save your progress first/i);
});

test("a remembered answer shows no dialog but still closes a game", () => {
  // Null dialog is not "nothing will happen": the player already agreed.
  const view = disconnectPresentation(
    running({ decision: "remembered", may_proceed: true }),
  );

  assert.equal(view.dialog, null);
  assert.equal(view.closesGame, true);
  assert.equal(view.available, true);
  assert.match(view.confirmation, /close Hades/i);
});

test("a remembered relaunch starts the box ticked", () => {
  const view = disconnectPresentation(running({ relaunch_requested: true }));

  assert.equal(view.dialog.relaunchChecked, true);
});

test("an unnamed game is asked about and never offered a checkbox", () => {
  const view = disconnectPresentation(
    running({ code: "game_close.identity_unverified", remember_offered: false, relaunch_offered: false },
      { identity_exact: false, title: "", app_id: "" }),
  );

  assert.equal(view.dialog.rememberLabel, null);
  assert.equal(view.dialog.relaunchLabel, null);
  assert.match(view.dialog.body, /could not identify which game/i);
  assert.match(view.dialog.body, /Save and close your game/i);
});

test("a game scan that failed is never presented as an empty screen", () => {
  // The fail-open removed from the backend three times now. An unfinished look
  // is not evidence that nothing is running.
  const view = disconnectPresentation(
    status({ close_prompt: prompt({ code: "game_close.scan_incomplete", remember_offered: false, relaunch_offered: false }) }),
  );

  assert.equal(view.closesGame, true);
  assert.match(view.dialog.body, /could not check whether a game is running/i);
  assert.doesNotMatch(view.dialog.body, /no game is running|nothing is running/i);
  assert.equal(view.dialog.rememberLabel, null);
});

test("no game running produces no dialog and no close", () => {
  const view = disconnectPresentation(status());

  assert.equal(view.dialog, null);
  assert.equal(view.closesGame, false);
  assert.doesNotMatch(view.confirmation, /close/i);
});

test("a ready device with a game running does not claim to be ready", () => {
  // Closing a game is not the no-op that "Ready" promises.
  const view = disconnectPresentation(
    status({ game: hades(), close_prompt: prompt() }),
  );

  assert.equal(view.value, "Close game");
  assert.match(view.confirmation, /will close Hades/i);
});

test("every dialog keeps the cable sentence last", () => {
  // It is the sentence that has to survive skim-reading.
  const cases = [
    running(),
    running({ code: "game_close.scan_incomplete" }),
    running({ remember_offered: false, progress_at_risk: true }, { save_capability: "unsafe_unknown" }),
    running({ code: "game_close.identity_unverified" }, { identity_exact: false }),
  ];
  for (const state of cases) {
    const view = disconnectPresentation(state);
    assert.ok(view.dialog.body.trimEnd().endsWith("Keep the cable connected: this does not make unplugging safe."), view.dialog.body);
  }
});

test("no dialog ever implies unplugging is safe", () => {
  for (const capability of [
    "untested",
    "verified_save_on_exit",
    "manual_save_required",
    "unsafe_unknown",
  ]) {
    const view = disconnectPresentation(
      running({ progress_at_risk: capability === "unsafe_unknown" }, { save_capability: capability }),
    );
    assert.doesNotMatch(view.dialog.body, /safe to unplug|you can unplug|remove the cable/i);
  }
});

test("gameCloseDialog returns null unless a confirmation is required", () => {
  assert.equal(gameCloseDialog(null, hades()), null);
  assert.equal(gameCloseDialog(nothingToClose, null), null);
  assert.equal(
    gameCloseDialog(prompt({ decision: "remembered" }), hades()),
    null,
  );
});

test("a game Re-Gear cannot name is not promised a close it cannot perform", () => {
  // Without an app id there is nothing to terminate. Offering "Close and
  // disconnect" would break the promise one second after making it.
  const view = disconnectPresentation(
    running({ code: "game_close.identity_unverified", remember_offered: false, relaunch_offered: false },
      { identity_exact: false, title: "", app_id: "" }),
  );

  assert.equal(view.dialog.canCloseGame, false);
  assert.equal(view.dialog.confirmLabel, "Try disconnect anyway");
  assert.match(view.dialog.body, /cannot close it for you/i);
  assert.match(view.dialog.body, /close your game, then try again/i);
});

test("a named game is the only case that promises to close it", () => {
  const view = disconnectPresentation(running());

  assert.equal(view.dialog.canCloseGame, true);
  assert.equal(view.dialog.confirmLabel, "Close and disconnect");
});

test("an unfinished scan promises no close either", () => {
  const view = disconnectPresentation(
    status({ close_prompt: prompt({ code: "game_close.scan_incomplete", remember_offered: false, relaunch_offered: false }) }),
  );

  assert.equal(view.dialog.canCloseGame, false);
  assert.equal(view.dialog.confirmLabel, "Disconnect anyway");
});

test("a sleep prompt talks about sleeping, not about disconnecting", () => {
  // A player who pressed Sleep is not thinking about the eGPU. Telling them
  // the game must close "before it can be disconnected" answers a question
  // they did not ask.
  const view = disconnectPresentation(running({ intent: "sleep" }));

  assert.match(view.dialog.title, /Close Hades and sleep\?/);
  assert.match(view.dialog.body, /before the handheld can sleep/);
  assert.equal(view.dialog.confirmLabel, "Close and sleep");
});

test("a sleep prompt still says the eGPU will be disconnected", () => {
  // Because it will. A player must not wake to find it detached without
  // having been told.
  const view = disconnectPresentation(running({ intent: "sleep" }));

  assert.match(view.dialog.body, /eGPU will be disconnected first/i);
  assert.match(view.dialog.body, /Keep the cable connected/i);
});

test("the sleep checkbox names the action as well as the game", () => {
  // The stored answer is keyed by both. A label naming only the game would
  // collect consent broader than what is recorded.
  const view = disconnectPresentation(running({ intent: "sleep" }));

  assert.equal(
    view.dialog.rememberLabel,
    "Don't ask again when sleeping with Hades open",
  );
});

test("a disconnect prompt is unchanged by the sleep wording", () => {
  const view = disconnectPresentation(running());

  assert.match(view.dialog.body, /before it can be disconnected/);
  assert.doesNotMatch(view.dialog.body, /sleep/i);
  assert.equal(view.dialog.confirmLabel, "Close and disconnect");
});

test("every sleep dialog keeps the cable sentence last too", () => {
  for (const over of [
    { intent: "sleep" },
    { intent: "sleep", code: "game_close.scan_incomplete" },
    { intent: "sleep", code: "game_close.identity_unverified" },
  ]) {
    const view = disconnectPresentation(
      running(over, over.code === "game_close.identity_unverified" ? { identity_exact: false } : {}),
    );
    assert.ok(
      view.dialog.body
        .trimEnd()
        .endsWith("Keep the cable connected: this does not make unplugging safe."),
      view.dialog.body,
    );
  }
});
