/** The seam between what the panel has and what the owning close flow needs.
 *
 * `game-close-flow.ts` already owns the dangerous part: close the game, wait
 * for the backend to say it is gone, remove the device, put the game back. It
 * has had no production caller, and the panel has been calling
 * `executeEgpuDisconnect` directly -- which removes the eGPU from underneath a
 * running game without closing it, asking about it, or reopening it. This
 * module exists so there is one place that turns a press into that flow's
 * request, and so the checks between the two cannot be skipped by forgetting
 * them at a call site.
 *
 * It orchestrates nothing itself. Every verdict below is read from something
 * that already owns it -- `disconnectPresentation` for whether the action may
 * be offered, the backend's `close_prompt` for whether a game may be closed
 * unasked, the flow for the close-and-remove sequence -- because a second
 * opinion about any of those is how the tile and the operation start
 * disagreeing. What this adds is the gates between the dialog and the device,
 * and each one is here because skipping it hurts someone:
 *
 * 1. **A cancel does nothing.** Not a stored preference, not a terminate, not
 *    a disconnect, not a suspend. The player's answer was no, and a "no" that
 *    still writes something down is a bug that outlives the press.
 * 2. **The status is read again at the press, not trusted from the dialog.**
 *    A dialog composed thirty seconds ago describes a device that may have
 *    moved. Unknown, busy, half-detached and no-longer-attemptable all stop
 *    here rather than being discovered halfway through a removal.
 * 3. **The game that closes is the game that was agreed to.** Consent is per
 *    game and per intent. If a different game is running at the press, or the
 *    running game can no longer be named exactly, nothing is closed: the
 *    player agreed to lose one specific game's progress, not whatever happens
 *    to be running.
 * 4. **Nothing visible happens without its own approval.** Turning the
 *    external display off is a separate yes from disconnecting, because
 *    whoever is watching the TV did not press anything.
 * 5. **No power action after a failed prerequisite.** A sleep whose
 *    prerequisite failed stays awake. This is the flow's own rule and this
 *    module does not route around it; what it adds is refusing to remove a
 *    GPU for a sleep that never needed one.
 *
 * Nothing here implies that unplugging is safe. Every message about a refusal
 * says what was not done; every message about a success comes from
 * `closeFlowMessage`, which keeps the cable sentence.
 */

import type {
  ClosePromptPayload,
  DisconnectGamePayload,
  DisconnectOutcomePayload,
  DisconnectStatusPayload,
  SleepReadinessPayload,
} from "../backend";
import type { DisconnectPresentation } from "../egpu-disconnect-tile";
import { disconnectPresentation } from "../egpu-disconnect-tile";
import type { CloseFlowResult, SleepFlowEffects } from "../game-close-flow";
import {
  claimPendingRelaunch,
  closeFlowMessage,
  runDisconnectWithGameClose,
  runSleepWithGameClose,
} from "../game-close-flow";

/** What the player pressed. Sleep and disconnect are separate journeys that
 * happen to share a prerequisite; they are never inferred from one another. */
export type CloseFlowIntent = "disconnect" | "sleep";

/** Everything this needs from outside itself.
 *
 * Extends the owning flow's own effects rather than restating them, so the
 * contract cannot drift: a change to what the flow needs is a type error here
 * instead of a silently missing effect at runtime.
 */
export interface GameCloseWiringPorts extends SleepFlowEffects {
  /** Sleep readiness, whose `close_prompt` is re-derived for the sleep intent.
   * Null when it could not be read, which is never read as "ready". */
  readSleepReadiness(): Promise<SleepReadinessPayload | null>;
}

/** A press, as the panel knows it at the moment the player commits. */
export interface GameClosePress {
  intent: CloseFlowIntent;
  /** The game the dialog was about, or null when it named none. Compared
   * against a fresh reading before anything closes. */
  appId: string | null;
  /** False for a dismissal. A dismissal is a no, not a retry. */
  confirmed: boolean;
  /** True only when the player answered the game-close dialog itself.
   *
   * Clearing the tile's own confirmation is not the same answer. The tile
   * confirmation is about removing a device; the game-close dialog is about
   * someone's unsaved progress, and a press that never showed the second one
   * carries no permission to end a game. They come apart for real: a panel can
   * render a tile whose prompt said `remembered`, and by the press the backend
   * can be asking again -- a forgotten preference, or a prompt re-derived for
   * the other intent. Then the dialog the player answered does not exist.
   */
  gameCloseAnswered: boolean;
  /** "Don't ask again", only ever true when that box was actually offered. */
  remember: boolean;
  /** "Reopen afterwards", as ticked in the dialog. */
  relaunch: boolean;
  /** Approval to turn the external display off. Never defaulted on. */
  releaseDisplay: boolean;
}

export interface GameCloseWiringResult {
  ok: boolean;
  /** `wiring.` for this module's own refusals, otherwise the flow's or the
   * backend's code passed through unchanged. */
  code: string;
  /** The flow's result, or null when this refused before the flow ran. */
  flow: CloseFlowResult | null;
  outcome: DisconnectOutcomePayload | null;
  gameClosed: boolean;
  relaunched: boolean;
  /** True when a person needs to look at the device. */
  attention: boolean;
  /** True when the refusal happened before anything was asked of the device,
   * the Steam session or the player's stored preferences. */
  refusedBeforeAction: boolean;
}

function refused(code: string): GameCloseWiringResult {
  return {
    ok: false,
    code,
    flow: null,
    outcome: null,
    gameClosed: false,
    relaunched: false,
    attention: false,
    refusedBeforeAction: true,
  };
}

function fromFlow(result: CloseFlowResult): GameCloseWiringResult {
  return {
    ok: result.ok,
    code: result.code,
    flow: result,
    outcome: result.outcome,
    gameClosed: result.gameClosed,
    relaunched: result.relaunched,
    attention: result.attention,
    refusedBeforeAction: false,
  };
}

/** The app id this flow may close and reopen, or null when there is none.
 *
 * Null for three different reasons -- nothing running, a game that could not
 * be named exactly, or a dialog that already said it cannot close it -- and
 * all three mean the same thing to a caller: do not promise a close.
 */
export function closableAppId(view: DisconnectPresentation): string | null {
  if (view.dialog !== null && !view.dialog.canCloseGame) {
    return null;
  }
  const game: DisconnectGamePayload | null = view.game;
  if (game === null || !game.identity_exact || !game.app_id) {
    return null;
  }
  return game.app_id;
}

/** What the player did with the dialog, as a panel knows it.
 *
 * `confirmed` has no default on purpose. A caller that forgets it is a type
 * error rather than a press that quietly counts as a yes.
 */
export interface GameCloseAnswers {
  confirmed: boolean;
  remember?: boolean;
  relaunch?: boolean;
  releaseDisplay?: boolean;
}

/** Build the press from the presentation the dialog was drawn from.
 *
 * The boxes are read through what was offered, not through what arrived: a
 * panel that sends `remember: true` for a dialog whose remember label was null
 * would store consent that was never asked for, and that label is null exactly
 * when the catalog says closing the game loses progress.
 */
export function pressFromDialog(
  view: DisconnectPresentation,
  intent: CloseFlowIntent,
  answers: GameCloseAnswers,
): GameClosePress {
  const dialog = view.dialog;
  // A dismissal carries no answers. Ticking "don't ask again" and then
  // cancelling is not consent to anything, and a press that still carried the
  // tick would store it the moment some later caller stopped checking
  // `confirmed` first. The boxes only survive a yes.
  const confirmed = answers.confirmed === true;
  return {
    intent,
    appId: closableAppId(view),
    confirmed,
    // There is an answer only where there was a question. A null dialog means
    // nothing was asked, which is not the same as having been answered.
    gameCloseAnswered: confirmed && dialog !== null,
    remember: confirmed && answers.remember === true && dialog?.rememberLabel != null,
    relaunch: confirmed && answers.relaunch === true && dialog?.relaunchLabel != null,
    releaseDisplay: confirmed && answers.releaseDisplay === true,
  };
}

/** Whether the player's consent covers closing a game right now.
 *
 * Branches on `decision`, which is the field the owning contract documents as
 * the one to branch on. A missing prompt is not permission: a backend that
 * sends no prompt has not said the game may be closed, and the only safe
 * reading of silence is to ask.
 *
 * `may_proceed` is cross-checked rather than trusted on its own. A prompt
 * claiming a standing answer while also saying further interaction is needed
 * is a prompt disagreeing with itself, and a disagreement about someone's
 * unsaved progress is resolved by asking, never by picking the convenient half.
 */
function consentSatisfied(
  prompt: ClosePromptPayload | null,
  press: GameClosePress,
): { ok: true } | { ok: false; code: string } {
  if (prompt === null) {
    return { ok: false, code: "wiring.close_prompt_unavailable" };
  }
  if (prompt.intent !== press.intent) {
    // Consent is per intent. An answer given for a disconnect does not
    // authorise closing the same game for a sleep, and a prompt derived for
    // the other action cannot be used to judge this one.
    return { ok: false, code: "wiring.intent_mismatch" };
  }
  if (prompt.decision === "confirm") {
    // The backend is asking. Only an answer to the question it is asking will
    // do -- and if the panel rendered before it started asking, there is none.
    return press.gameCloseAnswered
      ? { ok: true }
      : { ok: false, code: "wiring.consent_required" };
  }
  if (!prompt.may_proceed) {
    return { ok: false, code: "wiring.consent_contradictory" };
  }
  return { ok: true };
}

/** Run the press through the owning flow, or refuse before anything happens.
 *
 * The order matters and is the safety argument: cancel, then a fresh reading,
 * then consent, then identity, then the display approval, and only then the
 * flow. Every refusal before the flow leaves the device, the session and the
 * player's stored answers exactly as they were.
 */
export async function runGameClosePress(
  press: GameClosePress,
  ports: GameCloseWiringPorts,
): Promise<GameCloseWiringResult> {
  // A dismissal is an answer. Nothing is read, stored, closed or removed --
  // returning before the first port call is what makes that checkable.
  if (!press.confirmed) {
    return refused("wiring.cancelled");
  }

  let status: DisconnectStatusPayload | null = null;
  let prompt: ClosePromptPayload | null = null;

  if (press.intent === "sleep") {
    let readiness: SleepReadinessPayload | null;
    try {
      readiness = await ports.readSleepReadiness();
    } catch {
      readiness = null;
    }
    if (readiness === null) {
      return refused("wiring.sleep_readiness_unavailable");
    }
    if (readiness.code === "sleep.readiness_unknown") {
      // Not knowing what sleeping would take is not evidence that sleeping is
      // safe. Invariant 19: a missing preflight never stands in for a pass.
      return refused("wiring.sleep_readiness_unknown");
    }
    if (!readiness.requires_disconnect) {
      // This flow is *disconnect, then sleep*. A sleep that does not need the
      // eGPU released must not have it released as a side effect: removing a
      // device nobody asked about is not a smaller harm than a refusal. The
      // panel's ordinary sleep path owns this case.
      return refused("wiring.sleep_needs_no_disconnect");
    }
    prompt = readiness.close_prompt ?? null;
    // The readiness carries the disconnect reading behind it so one set of
    // facts is judged rather than two taken moments apart. Falling back to a
    // direct read keeps the availability gate rather than skipping it.
    status = readiness.disconnect ?? null;
    if (status === null) {
      try {
        status = await ports.readStatus();
      } catch {
        status = null;
      }
    }
  } else {
    try {
      status = await ports.readStatus();
    } catch {
      status = null;
    }
    prompt = status?.close_prompt ?? null;
  }

  if (status === null) {
    return refused("wiring.status_unavailable");
  }

  // Whether the action may be offered at all is the tile's judgement, not a
  // second one made here. A half-detached device outranks everything.
  const view = disconnectPresentation(status);
  if (view.attention) {
    return refused("wiring.needs_attention");
  }
  if (!view.available) {
    return refused(
      status.availability === "busy"
        ? "wiring.busy"
        : "wiring.not_attemptable",
    );
  }

  const consent = consentSatisfied(prompt, press);
  if (!consent.ok) {
    return refused(consent.code);
  }

  // The game that closes is the game that was agreed to. A different app id,
  // or an identity that is no longer exact, means the consent on hand does not
  // cover what is running -- so nothing is closed and nothing is removed.
  const liveAppId = closableAppId(view);
  if (liveAppId !== press.appId) {
    return refused("wiring.game_changed");
  }
  // A game that will end but cannot be named reaches here with both ids null.
  // It is allowed through deliberately: the dialog for that case promises no
  // close and offers no reopen, and the backend remains the authority on
  // whether the removal itself may proceed underneath a game it can see.

  // Visible to whoever is watching the TV, so it carries its own yes.
  if (view.displayApprovalRequired && !press.releaseDisplay) {
    return refused("wiring.display_approval_required");
  }

  // The stored wish is the backend's, not the dialog's: a `remembered`
  // decision carries a reopen the player asked for on an earlier press, and
  // the dialog that would have shown the tick box was never drawn.
  const relaunch =
    press.appId !== null &&
    (press.relaunch || prompt?.relaunch_requested === true);

  const request = {
    appId: press.appId,
    intent: press.intent,
    releaseDisplay: press.releaseDisplay,
    remember: press.remember,
    relaunch,
  };

  const result =
    press.intent === "sleep"
      ? await runSleepWithGameClose(request, ports)
      : await runDisconnectWithGameClose(request, ports);
  return fromFlow(result);
}

export interface MountRelaunchResult {
  /** The game reopened, or null when none was. */
  appId: string | null;
  /** Why. `wiring.mount_` for a deliberate refusal to claim. */
  code: string;
  /** True when the record was deliberately left unclaimed, so a later mount
   * may still honour it. False when there was simply nothing recorded. */
  deferred: boolean;
}

/** Claim and perform a relaunch a previous disconnect left pending.
 *
 * For a panel on load, and the reason the whole arrangement exists: freeing
 * the eGPU restarts the Steam session, which destroys the panel that asked for
 * the reopen. The record is consumed by claiming, so exactly one panel can
 * honour it -- which is also why *not* claiming is a real option here rather
 * than a lost reopen. A record left alone is still there for the next mount
 * and expires on the backend's own terms.
 *
 * Three readings decline to claim, all of them fail-closed:
 *
 * - **Half detached.** A device that needs a person is not somewhere to start
 *   a game; launching into it stacks a second problem on the first.
 * - **Busy.** A disconnect is running and will claim the record itself when it
 *   finishes. Claiming underneath it races for the same game.
 * - **Unknown.** A status that could not be read is not a status saying the
 *   device is fine. Not reopening a game is recoverable; reopening it onto a
 *   half-detached eGPU is what invariant 9 exists to prevent.
 */
export async function claimRelaunchOnMount(
  ports: Pick<
    GameCloseWiringPorts,
    "readStatus" | "takePendingRelaunch" | "relaunchGame"
  >,
): Promise<MountRelaunchResult> {
  let status: DisconnectStatusPayload | null;
  try {
    status = await ports.readStatus();
  } catch {
    status = null;
  }
  if (status === null) {
    return { appId: null, code: "wiring.mount_status_unknown", deferred: true };
  }
  if (status.availability === "recovery_required") {
    return {
      appId: null,
      code: "wiring.mount_device_disturbed",
      deferred: true,
    };
  }
  if (status.availability === "busy" || status.busy) {
    return { appId: null, code: "wiring.mount_busy", deferred: true };
  }

  const appId = await claimPendingRelaunch(ports);
  return appId === null
    ? { appId: null, code: "wiring.mount_nothing_claimed", deferred: false }
    : { appId, code: "wiring.mount_relaunched", deferred: false };
}

/** What to tell the player when this module refused.
 *
 * Codes absent here fall through to the flow's own message, which falls
 * through to quoting its code, so an unmapped state reads as something a bug
 * report can act on rather than a confident wrong sentence. Nothing here says
 * or implies that unplugging is safe; every line says what was not done.
 */
const WIRING_MESSAGE: Record<string, string> = {
  "wiring.cancelled": "Nothing was changed.",
  "wiring.status_unavailable":
    "Re-Gear could not read the eGPU state, so nothing was disconnected.",
  "wiring.sleep_readiness_unavailable":
    "Re-Gear could not check what sleeping would take, so the handheld was left awake.",
  "wiring.sleep_readiness_unknown":
    "Re-Gear cannot confirm what sleeping would take, so the handheld was left awake.",
  "wiring.sleep_needs_no_disconnect":
    "Sleeping does not need the eGPU released, so Re-Gear left it connected. Use the handheld's own Sleep.",
  "wiring.needs_attention":
    "A previous disconnect left the eGPU in an unexpected state. Check it before trying again.",
  "wiring.busy": "A disconnect is already running. Nothing else was started.",
  "wiring.not_attemptable":
    "Re-Gear cannot confirm the eGPU can be released right now, so nothing was disconnected.",
  "wiring.close_prompt_unavailable":
    "Re-Gear could not check what closing your game would cost, so nothing was closed.",
  "wiring.intent_mismatch":
    "Re-Gear re-checked this for the action you pressed and the answers did not match, so nothing was closed.",
  "wiring.consent_required":
    "Your game was not closed, because Re-Gear still needs your answer about it.",
  "wiring.consent_contradictory":
    "Re-Gear could not confirm you had already answered about closing this game, so nothing was closed.",
  "wiring.game_changed":
    "A different game is running now, so Re-Gear closed nothing. Check what is open and try again.",
  "wiring.display_approval_required":
    "The external display has to turn off for this, and that was not approved, so nothing was disconnected.",
};

export function gameCloseWiringMessage(result: GameCloseWiringResult): string {
  const own = WIRING_MESSAGE[result.code];
  if (own !== undefined) {
    return own;
  }
  return result.flow !== null
    ? closeFlowMessage(result.flow)
    : `The request did not finish (${result.code}).`;
}
