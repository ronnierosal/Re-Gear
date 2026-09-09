/** What to tell a player after a disconnect attempt: pure, no React, no I/O.
 *
 * The problem this solves is specific. A disconnect restarts the Steam session,
 * the panel remounts, and the player is left looking at a panel that has
 * forgotten what just happened to their hardware. The one question they have --
 * "can I unplug it now?" -- goes unanswered, which is the worst possible time
 * for silence.
 *
 * `status.last` survives that restart, so the answer is available. This turns
 * it into something a player can act on.
 *
 * THE ANSWER TO "CAN I UNPLUG IT" IS ALWAYS NO, AND THAT IS NOT A HEDGE.
 *
 * Safety invariant 10: the tested Ally X / GPD G1 combination does not support
 * physical live unplug; restore internal operation and shut down before
 * disconnecting. Issue #147 asks whether that invariant should be *scoped* to
 * separate unplug-while-bound from unplug-after-verified-removal, and it is
 * open and undecided. Until it is decided, a successful software removal is
 * not clearance to pull the cable, and this module states that every single
 * time rather than only when something went wrong. A reassurance that appears
 * conditionally teaches a player that its absence means "go ahead".
 *
 * Even under the optimistic reading of #147, the residual risk it names is the
 * USB branch behind the dock and its xhci recovery failure (#105) -- so "the
 * GPU path is clean" would still not be "the dock is safe to unplug".
 */

import type { DisconnectOutcomePayload } from "../backend";

export type ResultTone = "done" | "attention" | "failed";

export type DisconnectResult = {
  /** False when there is nothing to report. */
  show: boolean;
  tone: ResultTone;
  headline: string;
  /** Precise statements about what happened. Never speculation. */
  detail: string[];
  /** The unplug answer. Present whenever anything is shown, never omitted. */
  unplug: string;
  /** True when the device was left somewhere it has never been. */
  attention: boolean;
};

/** The sentence that does not vary. Invariant 10 with the action a player
 * needs, not just a refusal: telling someone "no" without telling them how is
 * how they end up guessing. */
const UNPLUG_ANSWER =
  "Do not unplug the eGPU. Shut the handheld down first, then disconnect it.";

const ATTENTION_HEADLINE = "The eGPU needs attention";
const REMOVED_HEADLINE = "The eGPU is detached in software";
const FAILED_HEADLINE = "The disconnect did not complete";

function describe(outcome: DisconnectOutcomePayload): string[] {
  const detail: string[] = [];
  if (outcome.removed.length > 0) {
    detail.push(outcome.removed.length === 1
      ? "One eGPU function was removed."
      : `${outcome.removed.length} eGPU functions were removed.`);
  }
  if (outcome.restored.length > 0) {
    // Restoration after a failure is the difference between a tidy no-op and a
    // device left half detached, so it is worth saying explicitly.
    detail.push(outcome.restored.length === 1
      ? "One function was restored."
      : `${outcome.restored.length} functions were restored.`);
  }
  if (outcome.display_released.length > 0) {
    detail.push("The external display was turned off.");
  }
  if (outcome.session_disturbed) {
    detail.push("Your Steam session was restarted to free the device.");
  }
  if (outcome.filter_disarmed) {
    detail.push("Re-Gear's device filter was disarmed.");
  }
  return detail;
}

export function disconnectResult(
  outcome: DisconnectOutcomePayload | null | undefined,
): DisconnectResult {
  if (!outcome) {
    return { show: false, tone: "done", headline: "", detail: [], unplug: "", attention: false };
  }

  // Attention outranks success and failure alike. A device left somewhere it
  // has never been is not a failed button press, and reporting it as one would
  // invite the player to simply try again.
  if (outcome.device_disturbed) {
    return {
      show: true, tone: "attention", headline: ATTENTION_HEADLINE,
      detail: [
        "A disconnect stopped partway and the eGPU is half detached.",
        ...describe(outcome),
        "Restore it before trying again or shutting down.",
      ],
      unplug: UNPLUG_ANSWER, attention: true,
    };
  }

  if (outcome.ok && outcome.released) {
    return {
      show: true, tone: "done", headline: REMOVED_HEADLINE,
      detail: describe(outcome),
      unplug: UNPLUG_ANSWER, attention: false,
    };
  }

  return {
    show: true, tone: "failed", headline: FAILED_HEADLINE,
    detail: [
      // A failure that restored cleanly left the device where it started, which
      // is materially different from one that did not.
      outcome.restored.length > 0
        ? "The eGPU was left as it was."
        : "The eGPU was not detached.",
      ...describe(outcome),
    ],
    unplug: UNPLUG_ANSWER, attention: false,
  };
}
