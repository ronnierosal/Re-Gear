/** Turn the backend's disconnect status into what a player is shown.
 *
 * The backend reports facts. This decides what they mean on screen, and it
 * exists so the things a caller must not infer are enforced in one place
 * instead of described in a document nobody rereads.
 *
 * Four of those, because each one has already gone wrong somewhere:
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
 * 4. **Nothing here may imply that unplugging is safe.** Re-Gear detaches the
 *    eGPU in software; the cable stays connected. That distinction is the
 *    whole safety position and no string below softens it.
 *
 * The confirmation also states that the Steam session will restart, because
 * today it does -- that is what releases the device -- and a player must be
 * told before rather than surprised after.
 */

import type { DisconnectStatusPayload } from "./backend";

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
    };
  }

  if (!status.attemptable) {
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
    };
  }

  const display = status.display_release_required;
  const ready = status.availability === "ready";
  return {
    available: true,
    value: ready ? "Ready" : "Try disconnect",
    reason: null,
    actionLabel: "Disconnect",
    confirmation: [
      ready
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
