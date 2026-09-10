/** Close a running game, disconnect the eGPU, and put the game back.
 *
 * The close happens here rather than in the backend, and that is a decision
 * worth stating. The graceful way to end a game on SteamOS is Steam's own
 * terminate: it is what the player's own Exit button does, so Steam runs its
 * shutdown, its cloud sync and its own bookkeeping. A backend signalling a
 * Proton process would skip all of that to save a round trip, and what it
 * would be skipping is the part that saves the player's game.
 *
 * So the backend's job in this flow is not to kill anything. It is to say,
 * over a fresh observation, whether the game is gone -- and to refuse the
 * removal if it is not. This orchestrates; it never overrides that refusal.
 *
 * Four rules, each of which is a way this could hurt someone:
 *
 * 1. **Nothing is removed until the backend says the game is gone.** Not a
 *    timer, not the terminate call returning: the status saying
 *    `nothing_to_close` over a scan that finished. If that never comes, the
 *    flow stops and says so. It never escalates to a harder kill.
 * 2. **A game that was closed is put back when asked**, including when the
 *    disconnect then failed. Having closed someone's game and left them with
 *    neither the game nor the disconnect is the worst outcome available here.
 * 3. **Except onto a disturbed device.** A half-detached eGPU is not somewhere
 *    to relaunch a game; that state needs a person, and the flow says so
 *    instead of stacking a second problem on it.
 * 4. **The player's answer is stored before anything is done with it**, so a
 *    flow that fails halfway does not also lose the box they ticked.
 *
 * The relaunch itself is claimed from the backend rather than remembered here,
 * and that is the point of the whole arrangement: the session restart that
 * frees the eGPU destroys this panel, and a running game is precisely the case
 * that makes the restart necessary. So this asks for the reopen by recording
 * it with the disconnect, then claims it -- and if this panel is gone by then,
 * the next one claims it instead. The record is consumed by claiming, so
 * exactly one of them can.
 */

import type {
  DisconnectOutcomePayload,
  DisconnectStatusPayload,
} from "./backend";

/** The intents that may reopen the game once the flow finishes.
 *
 * An allow-list, and the reason is the shape of the mistake it prevents. This
 * was written as `intent !== "sleep"`, which is only correct while the union has
 * exactly two members: it asks "is this the one intent that must not reopen",
 * so every intent added afterwards inherits a relaunch by default. A shutdown
 * would have reopened a game seconds before the machine powered off -- worse
 * than the sleep case it was written for, because nothing comes back afterwards
 * to finish the job, and the player returns to a machine that killed their game
 * and then launched it again to be killed by the power cut.
 *
 * Compared as strings rather than against the narrow union on purpose. An
 * intent that is not yet part of the contract still has to resolve to "do not
 * reopen" rather than being unrepresentable, so the rule can be tested before
 * the journey that needs it exists. Adding a journey means adding it here
 * deliberately, with its own reason for reopening.
 */
const REOPEN_AFTER: readonly string[] = ["disconnect"];

export interface CloseFlowRequest {
  /** The game to close, or null when there is nothing Re-Gear can close. */
  appId: string | null;
  /** What the player asked for. Sleep does not reopen the game before the
   * machine suspends -- the record waits and is claimed after waking. */
  intent?: "disconnect" | "sleep";
  /** Approval to turn the external display off, from the tile confirmation. */
  releaseDisplay: boolean;
  /** The player ticked "don't ask again for this game". */
  remember: boolean;
  /** The player wants the game reopened afterwards. */
  relaunch: boolean;
}

export interface CloseFlowEffects {
  /** Steam's own graceful terminate for one app. */
  terminateGame(appId: string): Promise<void>;
  /** A fresh read of the disconnect status. */
  readStatus(): Promise<DisconnectStatusPayload | null>;
  disconnect(
    releaseDisplay: boolean,
    relaunchAppId: string,
    relaunchIntent: string,
  ): Promise<DisconnectOutcomePayload>;
  relaunchGame(appId: string): Promise<void>;
  /** Claim the game the backend recorded for reopening, or "" for none. */
  takePendingRelaunch(): Promise<{ steam_app_id: string; code: string }>;
  rememberChoice(
    appId: string,
    skipConfirmation: boolean,
    relaunchAfter: boolean,
  ): Promise<{ ok: boolean; code: string }>;
  wait(ms: number): Promise<void>;
  /** Monotonic-ish milliseconds, for the close deadline. */
  now(): number;
}

export type CloseFlowResult = {
  ok: boolean;
  /** Stable code. `flow.` for this module's own verdicts, otherwise the
   * backend's own code passed through unchanged. */
  code: string;
  /** The disconnect's outcome, or null when it was never attempted. */
  outcome: DisconnectOutcomePayload | null;
  /** Whether a game was closed by this flow. */
  gameClosed: boolean;
  /** Whether it was reopened afterwards. */
  relaunched: boolean;
  /** True when a person needs to look at the device. */
  attention: boolean;
};

/** How long to wait for a game to finish closing.
 *
 * Generous on purpose: a game saving on exit is exactly the case worth
 * waiting for, and the cost of waiting is a slow button, while the cost of
 * giving up early is a disconnect attempted underneath a game that was about
 * to close cleanly. Timing out is not an escalation -- the flow stops.
 */
const CLOSE_DEADLINE_MS = 30_000;
const POLL_INTERVAL_MS = 500;

function failed(
  code: string,
  over: Partial<CloseFlowResult> = {},
): CloseFlowResult {
  return {
    ok: false,
    code,
    outcome: null,
    gameClosed: false,
    relaunched: false,
    attention: false,
    ...over,
  };
}

/** Whether the backend now reports that there is nothing left to close.
 *
 * Deliberately strict. A missing prompt, an unfinished scan and a game still
 * running all read the same way here: not yet. The one thing that clears the
 * way is the backend saying so over a scan that finished.
 */
function nothingLeftToClose(status: DisconnectStatusPayload | null): boolean {
  return status?.close_prompt?.decision === "nothing_to_close";
}

export async function runDisconnectWithGameClose(
  request: CloseFlowRequest,
  effects: CloseFlowEffects,
): Promise<CloseFlowResult> {
  const { appId } = request;

  // Their answer, stored before it is acted on. A flow that fails halfway
  // should not also lose the box they ticked.
  if (appId !== null && (request.remember || request.relaunch)) {
    try {
      await effects.rememberChoice(appId, request.remember, request.relaunch);
    } catch {
      // Not fatal: the disconnect is what they pressed for, and being asked
      // again next time is the harmless failure.
    }
  }

  let gameClosed = false;
  if (appId !== null) {
    try {
      await effects.terminateGame(appId);
    } catch {
      return failed("flow.close_request_failed");
    }

    const deadline = effects.now() + CLOSE_DEADLINE_MS;
    for (;;) {
      let status: DisconnectStatusPayload | null;
      try {
        status = await effects.readStatus();
      } catch {
        status = null;
      }
      if (nothingLeftToClose(status)) {
        gameClosed = true;
        break;
      }
      if (effects.now() >= deadline) {
        // The game did not close. Nothing is removed, and no harder kill is
        // attempted: a game that will not exit gracefully is a game with
        // something to lose.
        return failed("flow.game_did_not_close");
      }
      await effects.wait(POLL_INTERVAL_MS);
    }
  }

  // Asked for with the removal, so the wish survives this panel being torn
  // down by the session restart the removal performs.
  const wanted = request.relaunch && gameClosed && appId !== null ? appId : "";
  const intent = request.intent ?? "disconnect";
  // Sleeping means the machine is about to be off. Reopening the game now
  // would launch it seconds before a suspend, so the record is left for the
  // panel that comes up after waking. Anything not named in REOPEN_AFTER is
  // treated the same way, which is the point of naming them.
  const reopenNow = REOPEN_AFTER.includes(intent);

  let outcome: DisconnectOutcomePayload;
  try {
    outcome = await effects.disconnect(request.releaseDisplay, wanted, intent);
  } catch {
    // The game is already closed, so put it back before reporting. The call
    // may have failed before the backend recorded anything, so this is the one
    // place a fallback is needed -- and it is safe, because claiming already
    // consumed any record that did get written. A sleep that never happened
    // leaves the player awake with a closed game, so this reopens either way.
    const relaunched = await restore(effects, false, wanted);
    return failed("flow.disconnect_failed", { gameClosed, relaunched });
  }

  const disturbed = outcome.device_disturbed === true;
  const relaunched = reopenNow ? await restore(effects, disturbed) : false;
  return {
    ok: outcome.ok === true,
    code: outcome.code,
    outcome,
    gameClosed,
    relaunched,
    attention: disturbed,
  };
}

/** Put the game back, unless doing so would make things worse.
 *
 * The game to reopen comes from the backend's record rather than from this
 * function's caller, so that this panel and a panel that replaced it cannot
 * both launch it. Claiming consumes the record, which is what makes that true.
 *
 * A half-detached eGPU is not somewhere to start a game. That state needs a
 * person, and launching into it would stack a second problem on the one that
 * already needs attention -- so this does not even claim the record, leaving
 * it to expire rather than firing later.
 */
async function restore(
  effects: CloseFlowEffects,
  disturbed: boolean,
  fallbackAppId = "",
): Promise<boolean> {
  if (disturbed) {
    return false;
  }
  let appId: string;
  try {
    appId = (await effects.takePendingRelaunch()).steam_app_id;
  } catch {
    appId = "";
  }
  if (!appId) {
    appId = fallbackAppId;
  }
  if (!appId) {
    return false;
  }
  try {
    await effects.relaunchGame(appId);
    return true;
  } catch {
    return false;
  }
}

/** Claim and perform any relaunch a previous disconnect left pending.
 *
 * For a panel on load. The session restart that frees the eGPU destroys the
 * panel that asked for the reopen, so the one that comes up afterwards is
 * usually the one that has to do it. Safe to call unconditionally: with
 * nothing recorded it does nothing.
 */
export async function claimPendingRelaunch(
  effects: Pick<CloseFlowEffects, "takePendingRelaunch" | "relaunchGame">,
): Promise<string | null> {
  let appId: string;
  try {
    appId = (await effects.takePendingRelaunch()).steam_app_id;
  } catch {
    return null;
  }
  if (!appId) {
    return null;
  }
  try {
    await effects.relaunchGame(appId);
    return appId;
  } catch {
    return null;
  }
}

export interface SleepFlowEffects extends CloseFlowEffects {
  /** Steam's own suspend. Re-Gear never suspends the machine itself. */
  suspend(): Promise<void>;
}

/** Close the game, disconnect the eGPU, then let Steam sleep the handheld.
 *
 * Sleeping while the eGPU is attached is refused outright on this hardware --
 * the dock wakes the handheld immediately -- so the only honest offer is
 * *disconnect, then sleep*. That makes this the disconnect flow plus one step,
 * and the ordering of that step is the whole safety argument:
 *
 * **Nothing suspends unless the disconnect succeeded.** A machine put to sleep
 * with the eGPU still attached is the state the sleep guard exists to prevent,
 * and it wakes seconds later having closed the player's game for nothing.
 *
 * **The game is not reopened before the suspend.** Launching it seconds before
 * the machine goes off would be worse than not reopening it at all. The wish
 * is recorded and waits; the panel that comes up after waking claims it.
 */
export async function runSleepWithGameClose(
  request: CloseFlowRequest,
  effects: SleepFlowEffects,
): Promise<CloseFlowResult> {
  const result = await runDisconnectWithGameClose(
    { ...request, intent: "sleep" },
    effects,
  );
  if (!result.ok) {
    // Whatever went wrong, the eGPU is still attached and sleeping would wake
    // the handheld straight back up.
    return result;
  }
  try {
    await effects.suspend();
  } catch {
    return { ...result, ok: false, code: "flow.suspend_failed" };
  }
  return { ...result, code: "flow.slept" };
}

/** What to tell the player when the flow ends.
 *
 * Codes absent here quote themselves, so an unmapped outcome reads as
 * something a bug report can act on rather than a confident wrong sentence.
 */
const FLOW_MESSAGE: Record<string, string> = {
  "flow.close_request_failed":
    "Re-Gear could not ask Steam to close the game. Nothing was disconnected.",
  "flow.game_did_not_close":
    "The game did not close, so the eGPU was left connected. Close it yourself and try again.",
  "flow.disconnect_failed":
    "The game closed, but the eGPU could not be disconnected.",
  "flow.suspend_failed":
    "The eGPU is detached in software, but Steam did not sleep the handheld. Try sleeping again.",
};

export function closeFlowMessage(result: CloseFlowResult): string {
  if (result.code === "flow.slept") {
    // Read after waking, so it is written in the past tense.
    return result.gameClosed
      ? "Your game was closed and the eGPU detached in software before sleeping. Keep the cable connected: this does not make unplugging safe."
      : "The eGPU was detached in software before sleeping. Keep the cable connected: this does not make unplugging safe.";
  }
  if (result.attention) {
    return "The disconnect stopped partway and the eGPU is in an unexpected state. Check it before using it again.";
  }
  if (result.ok) {
    return result.gameClosed
      ? result.relaunched
        ? "The eGPU is detached in software and your game is reopening. Keep the cable connected: this does not make unplugging safe."
        : "Your game is closed and the eGPU is detached in software. Keep the cable connected: this does not make unplugging safe."
      : "The eGPU is detached in software. Keep the cable connected: this does not make unplugging safe.";
  }
  return FLOW_MESSAGE[result.code] ?? `The disconnect did not finish (${result.code}).`;
}
