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
 */

import type {
  DisconnectOutcomePayload,
  DisconnectStatusPayload,
} from "./backend";

export interface CloseFlowRequest {
  /** The game to close, or null when there is nothing Re-Gear can close. */
  appId: string | null;
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
  disconnect(releaseDisplay: boolean): Promise<DisconnectOutcomePayload>;
  relaunchGame(appId: string): Promise<void>;
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

  let outcome: DisconnectOutcomePayload;
  try {
    outcome = await effects.disconnect(request.releaseDisplay);
  } catch {
    // The game is already closed, so put it back before reporting.
    const relaunched = await restore(request, effects, gameClosed, false);
    return failed("flow.disconnect_failed", { gameClosed, relaunched });
  }

  const disturbed = outcome.device_disturbed === true;
  const relaunched = await restore(request, effects, gameClosed, disturbed);
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
 * A half-detached eGPU is not somewhere to start a game. That state needs a
 * person, and launching into it would stack a second problem on the one that
 * already needs attention.
 */
async function restore(
  request: CloseFlowRequest,
  effects: CloseFlowEffects,
  gameClosed: boolean,
  disturbed: boolean,
): Promise<boolean> {
  if (!request.relaunch || !gameClosed || request.appId === null || disturbed) {
    return false;
  }
  try {
    await effects.relaunchGame(request.appId);
    return true;
  } catch {
    return false;
  }
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
};

export function closeFlowMessage(result: CloseFlowResult): string {
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
