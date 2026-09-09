/** Turn the backend's disconnect status into what a player is shown.
 *
 * The backend reports facts. This decides what they mean on screen, and it
 * exists so the things a caller must not infer are enforced in one place
 * instead of described in a document nobody rereads.
 *
 * Five of those, because each one has already gone wrong somewhere:
 *
 * 1. **An empty holder list is not a clear device.** `holders` and
 *    `scanComplete` travel separately; an empty list from a scan that could
 *    not finish means the check did not complete, not that nothing is using
 *    the eGPU.
 * 2. **A blocker the disconnect exists to clear is not a blocker to report.**
 *    Removal safety is assessed before any release, and before one it always
 *    declines: the holders are still there and the eGPU is still driving a
 *    display. The backend reports those as `attemptable`, and offering the
 *    action only on `ready` would tell a player their eGPU can never be
 *    disconnected.
 * 3. **A half-detached device is not a failed action.** It is a system that
 *    needs attention, and it outranks every other state.
 * 4. **A running game is not a blocker either.** Closing it is exactly what
 *    the flow does. Reporting it as a dead end would refuse the action at the
 *    only moment a player wants it -- while they are playing on the eGPU.
 * 5. **Nothing here may imply that unplugging is safe.** Re-Gear detaches the
 *    eGPU in software; the cable stays connected. That distinction is the
 *    whole safety position and no string below softens it.
 *
 * The confirmation also states that the Steam session will restart, because
 * today it does -- that is what releases the device -- and a player must be
 * told before rather than surprised after.
 *
 * What it does *not* decide is whether a game may be closed unasked. That is
 * the backend's `close_prompt`, which is read here and never re-derived: a
 * second opinion about someone's unsaved progress is one too many.
 */

import type {
  ClosePromptPayload,
  DisconnectGamePayload,
  DisconnectStatusPayload,
} from "./backend";

export type DisconnectPresentation = {
  /** Whether the tile may be activated. */
  available: boolean;
  /** The tile's value line. */
  value: string;
  /** Why it cannot be used, or null when it can. Never a raw code. */
  reason: string | null;
  /** Label for the action, or null when there is nothing to press. */
  actionLabel: string | null;
  /** Confirmation a player must accept first, or null when none is needed. */
  confirmation: string | null;
  /** True when the display has to be turned off for the removal. */
  displayApprovalRequired: boolean;
  /** True when this is a system state needing attention, not a failed action. */
  attention: boolean;
  /** The game that would have to close first, when one is running. */
  game: DisconnectGamePayload | null;
  /** The dialog to show before acting, or null when nothing has to be asked.
   *
   * Null for two very different reasons -- nothing is running, or the player
   * already answered for this game -- so it is never the field to branch on.
   * `closesGame` says whether a game will end either way. */
  dialog: GameCloseDialog | null;
  /** True when acting will close a running game, asked about or not. */
  closesGame: boolean;
};

/** The confirm-and-close dialog, as facts a panel renders.
 *
 * A checkbox that is absent is not the same as one that is unticked: the
 * label being null means the player must not be offered that choice at all,
 * which is how a game with reviewed evidence of losing progress stays
 * confirmable-only.
 */
export type GameCloseDialog = {
  title: string;
  /** What will happen, and what it costs, in the order a player needs it. */
  body: string;
  confirmLabel: string;
  cancelLabel: string;
  /** "Don't ask again for <game>", or null when it must not be offered. */
  rememberLabel: string | null;
  /** "Reopen <game> afterwards", or null when the game cannot be reopened. */
  relaunchLabel: string | null;
  /** Whether the reopen box starts ticked, from the player's stored answer. */
  relaunchChecked: boolean;
  /** True when the catalog has reviewed evidence that closing loses progress.
   * A panel may emphasise this; it must not use it to hide the dialog. */
  progressAtRisk: boolean;
};

/** What each blocking code means to a player.
 *
 * Codes absent here fall through to a reason that quotes the code, so an
 * unmapped state reads as something a bug report can act on rather than as a
 * confident sentence that happens to be wrong.
 */
const BLOCKED_REASON: Record<string, string> = {
  "removal_safety.clients_active_or_protected":
    "Something is still using the eGPU.",
  "removal_safety.client_scan_incomplete":
    "Re-Gear could not check every process, so it cannot confirm the eGPU is free.",
  // Reached only when a status names a running game but carries no prompt to
  // act on it; the ordinary path offers the close instead of reporting this.
  "removal_safety.game_running": "Close the running game first.",
  "removal_safety.evidence_insufficient":
    "Re-Gear does not have enough information about the eGPU yet.",
  "live_disconnect.egpu_unavailable": "No eGPU is connected.",
  "live_disconnect.session_unavailable":
    "Re-Gear cannot reach the Steam session.",
  "live_disconnect.status_unavailable": "Re-Gear could not read the eGPU state.",
};

const ATTENTION_REASON: Record<string, string> = {
  "removal_transaction.partially_detached":
    "A previous disconnect stopped partway and the eGPU is half detached. Restore it before trying again.",
  "live_disconnect.record_unreadable":
    "Re-Gear cannot read its record of the last disconnect, which may describe a half-detached eGPU.",
  "removal_transaction.complete":
    "A previous disconnect finished and its record is still present.",
};

/** The one sentence that must never drift.
 *
 * Software removal is not unplug clearance. Every confirmation says so, and
 * says it after the disruptive part rather than buried ahead of it.
 */
const KEEP_CABLE = "Keep the cable connected: this does not make unplugging safe.";

const SESSION_WARNING = "Your Steam session will restart.";

/** What closing this game will cost, in words a player can act on.
 *
 * Driven by the reviewed catalog. The default is the honest one: for a game
 * nobody has reported on, Re-Gear does not know whether it saves, and says so
 * rather than implying it is fine.
 */
export function gameCloseAdvice(game: DisconnectGamePayload): string {
  switch (game.save_capability) {
    case "verified_triggerable_autosave":
    case "verified_save_on_exit":
    case "graceful_exit_verified":
      return "Closing it saves your progress.";
    case "manual_save_recommended":
    case "manual_save_required":
      return "Save your progress first: this game does not save when it closes.";
    case "unsafe_unknown":
      return "Closing it may lose progress. Save your game first.";
    default:
      return "Re-Gear cannot confirm this game saves when it closes. Save it first.";
  }
}

function gameName(game: DisconnectGamePayload | null): string {
  return game?.title || "the running game";
}

/** The dialog shown before a disconnect closes whatever is running.
 *
 * Returns null when nothing has to be asked: either nothing is running, or
 * the player already gave a standing answer for this game.
 *
 * The body is ordered the way a player needs it -- what is about to happen,
 * what it costs them, then the two things they must not be surprised by. The
 * cable sentence is last in every branch, for the same reason it is last in
 * the tile confirmation: it is the sentence that must survive skim-reading.
 */
export function gameCloseDialog(
  prompt: ClosePromptPayload | null,
  game: DisconnectGamePayload | null,
): GameCloseDialog | null {
  if (prompt === null || prompt.decision !== "confirm") {
    return null;
  }

  const named = game !== null && game.identity_exact;

  if (prompt.code === "game_close.scan_incomplete") {
    // Not "nothing is running": Re-Gear could not look. Saying the first
    // would close a player's game without a word about it.
    return {
      title: "Disconnect the eGPU?",
      body: [
        "Re-Gear could not check whether a game is running, so it cannot tell you what disconnecting will close.",
        "Save anything you have open first.",
        SESSION_WARNING,
        KEEP_CABLE,
      ].join(" "),
      confirmLabel: "Disconnect anyway",
      cancelLabel: "Cancel",
      rememberLabel: null,
      relaunchLabel: null,
      relaunchChecked: false,
      progressAtRisk: false,
    };
  }

  if (!named) {
    return {
      title: "Close the running game?",
      body: [
        "A game is using the eGPU and has to close before it can be disconnected.",
        "Re-Gear could not identify which game, so it cannot tell you whether closing it saves your progress, and cannot reopen it afterwards.",
        "Save your game first.",
        SESSION_WARNING,
        KEEP_CABLE,
      ].join(" "),
      confirmLabel: "Close and disconnect",
      cancelLabel: "Cancel",
      rememberLabel: null,
      relaunchLabel: null,
      relaunchChecked: false,
      progressAtRisk: prompt.progress_at_risk,
    };
  }

  const name = gameName(game);
  return {
    title: `Close ${name}?`,
    body: [
      `${name} is using the eGPU and has to close before it can be disconnected.`,
      gameCloseAdvice(game as DisconnectGamePayload),
      SESSION_WARNING,
      KEEP_CABLE,
    ].join(" "),
    confirmLabel: "Close and disconnect",
    cancelLabel: "Cancel",
    // Absent, not unticked, when the catalog says closing loses progress:
    // that prompt carries something to act on now, which a box ticked last
    // week cannot carry.
    rememberLabel: prompt.remember_offered
      ? `Don't ask again for ${name}`
      : null,
    relaunchLabel: prompt.relaunch_offered
      ? `Reopen ${name} afterwards`
      : null,
    relaunchChecked: prompt.relaunch_requested,
    progressAtRisk: prompt.progress_at_risk,
  };
}

export function disconnectPresentation(
  status: DisconnectStatusPayload | null,
): DisconnectPresentation {
  if (status === null) {
    return {
      available: false,
      value: "Unknown",
      reason: "Re-Gear has not read the eGPU state yet.",
      actionLabel: null,
      confirmation: null,
      displayApprovalRequired: false,
      attention: false,
      game: null,
      dialog: null,
      closesGame: false,
    };
  }

  if (status.availability === "recovery_required") {
    return {
      available: false,
      value: "Needs attention",
      reason:
        ATTENTION_REASON[status.code] ??
        `A previous disconnect left the eGPU in an unexpected state (${status.code}).`,
      actionLabel: null,
      confirmation: null,
      displayApprovalRequired: false,
      attention: true,
      game: null,
      dialog: null,
      closesGame: false,
    };
  }

  if (status.availability === "busy") {
    return {
      available: false,
      value: "Working",
      reason: "A disconnect is already running.",
      actionLabel: null,
      confirmation: null,
      displayApprovalRequired: false,
      attention: false,
      game: null,
      dialog: null,
      closesGame: false,
    };
  }

  if (status.availability === "unavailable") {
    return {
      available: false,
      value: "Unavailable",
      reason: BLOCKED_REASON[status.code] ?? "No eGPU is connected.",
      actionLabel: null,
      confirmation: null,
      displayApprovalRequired: false,
      attention: false,
      game: null,
      dialog: null,
      closesGame: false,
    };
  }

  // A running game is the fifth thing that must not be reported as a blocker.
  // Closing it is exactly what the flow does, so declining here would tell a
  // player their eGPU can never be disconnected while they are playing --
  // which is the only time they would want to.
  const gameIsTheBlocker = status.code === "removal_safety.game_running";
  // A backend too old to send the field is not a backend reporting a running
  // game, so a missing prompt reads the same as no prompt rather than as an
  // undefined that leaks into every comparison below.
  const prompt = status.close_prompt ?? null;
  // Either signal is enough. A backend that names a running game in its
  // readiness code but reports no prompt is a backend mid-upgrade, and the
  // safe reading of the disagreement is that a game will close.
  const closesGame =
    gameIsTheBlocker ||
    (prompt !== null && prompt.decision !== "nothing_to_close");

  if (!status.attemptable && !gameIsTheBlocker) {
    return {
      available: false,
      value: "Not ready",
      reason:
        BLOCKED_REASON[status.code] ??
        `Re-Gear cannot confirm the eGPU is free (${status.code}).`,
      actionLabel: null,
      confirmation: null,
      displayApprovalRequired: false,
      attention: false,
      game: null,
      dialog: null,
      closesGame: false,
    };
  }

  const display = status.display_release_required;
  const ready = status.availability === "ready" && !closesGame;
  const dialog = gameCloseDialog(prompt, status.game ?? null);
  return {
    available: true,
    value: closesGame ? "Close game" : ready ? "Ready" : "Try disconnect",
    reason: null,
    actionLabel: "Disconnect",
    confirmation: [
      closesGame
        ? `Re-Gear will close ${gameName(status.game)}, then detach the eGPU in software.`
        : ready
          ? "Re-Gear will detach the eGPU in software."
          : "Re-Gear will try to free the eGPU and detach it in software.",
      display ? "The external display will turn off." : null,
      SESSION_WARNING,
      KEEP_CABLE,
    ]
      .filter((line): line is string => line !== null)
      .join(" "),
    displayApprovalRequired: display,
    attention: false,
    game: status.game ?? null,
    dialog,
    closesGame,
  };
}

/** Whether a completed attempt left the system needing attention.
 *
 * Separate from success: a removal can fail harmlessly, and a removal can fail
 * having left the device somewhere it has never been. Only the second is an
 * alert.
 */
export function outcomeNeedsAttention(outcome: {
  device_disturbed: boolean;
} | null): boolean {
  return outcome !== null && outcome.device_disturbed === true;
}
