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
 * THE ANSWER TO "CAN I DISCONNECT IT" IS EARNED, NOT ASSERTED.
 *
 * Invariant 10 forbids a *live* unplug: pulling the cable while the eGPU is
 * bound, with a driver attached and transactions possible. A safe disconnect
 * is a different operation, and the difference is checkable rather than
 * argued: the functions are removed and the system is asked whether an eGPU is
 * still connected. This module never composes that answer itself; it delegates
 * to `unplugClearance`, which refuses unless every check passes and shows the
 * evidence beside its verdict.
 *
 * The clearance is scoped to the eGPU and always carries the caveat that the
 * USB branch behind the dock (#105) is a separate path this says nothing
 * about.
 */

import type { DisconnectOutcomePayload, DisconnectStatusPayload } from "../backend";
import { unplugClearance } from "./unplug-clearance";
import type { UnplugClearance } from "./unplug-clearance";

export type ResultTone = "done" | "attention" | "failed";

export type DisconnectResult = {
  /** False when there is nothing to report. */
  show: boolean;
  tone: ResultTone;
  headline: string;
  /** Precise statements about what happened. Never speculation. */
  detail: string[];
  /** The disconnect answer, earned from evidence. Present whenever anything is
   * shown, never omitted, and never composed here. */
  clearance: UnplugClearance;
  /** True when the device was left somewhere it has never been. */
  attention: boolean;
};

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
  status?: DisconnectStatusPayload | null,
): DisconnectResult {
  const clearance = unplugClearance(status, outcome);
  if (!outcome) {
    return { show: false, tone: "done", headline: "", detail: [], clearance, attention: false };
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
      clearance, attention: true,
    };
  }

  if (outcome.ok && outcome.released) {
    return {
      // The headline reflects the checked state, not the command's return code.
      show: true, tone: "done",
      headline: clearance.cleared ? "The eGPU is disconnected" : REMOVED_HEADLINE,
      detail: describe(outcome),
      clearance, attention: false,
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
    clearance, attention: false,
  };
}
