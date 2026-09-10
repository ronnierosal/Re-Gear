/** Controller module presentation: pure, no React, no I/O, no requests.
 *
 * Every field here is an observation the backend actually reported. The
 * temptation in a controller page is to fill gaps with plausible detail -- a
 * device name, a Player 1 badge, "connected" inferred from a working shortcut.
 * All of those are inventions, and a player reading an invented fact while
 * hunting a controller problem is worse served than one reading "Unknown".
 *
 * Three separations this file exists to keep:
 *
 * 1. Presence is not shortcut availability. A usable shortcut input source says
 *    Re-Gear can read a button combination. It does not say which controller is
 *    attached, whether the built-in pad is alive, or who is Player 1. They are
 *    reported as different facts because they can disagree.
 *
 * 2. Incomplete is not absent. `complete` and `exact` describe how much of the
 *    reading is trustworthy; a partial reading still shows what it knows and
 *    says the rest is unverified, rather than collapsing to "no controller".
 *
 * 3. Planned is not available. Player order, shortcut customization and
 *    priority handoff are named in the plan and have no implementation. They
 *    are listed as not yet available, never rendered as controls that appear to
 *    work.
 */

import type { PeripheralStatusPayload } from "../../backend";

export type ControllerFact = {
  /** Player-facing text. "Unknown" whenever the backend did not say. */
  text: string;
  /** False when this is an absence of evidence rather than a reading. */
  known: boolean;
};

/** How much of the reading can be trusted, straight from the payload. */
export type ControllerPrecision = "exact" | "partial" | "unknown";

export type ControllerPresentation = {
  /** True when any usable controller fact was reported. */
  available: boolean;
  /** Why nothing can be shown, or null when something can. */
  reason: string | null;
  builtin: ControllerFact;
  external: ControllerFact;
  precision: ControllerPrecision;
  /** Only present when the reading is not exact; explains the caveat. */
  precisionNote: string | null;
  /** Deliberately separate from presence: this is Re-Gear's input source. */
  shortcut: ControllerFact;
  /** Named in the plan, not implemented. Never rendered as working controls. */
  planned: string[];
};

const UNKNOWN: ControllerFact = { text: "Unknown", known: false };

/** Planned capabilities, listed so their absence is explicit rather than a gap
 * a player has to notice. Each is stated as not yet available. */
export const PLANNED_CONTROLLER_FEATURES = [
  "Player order",
  "Shortcut customization",
  "Priority handoff",
];

function fact(value: boolean | null | undefined, yes: string, no: string): ControllerFact {
  if (value === true) return { text: yes, known: true };
  if (value === false) return { text: no, known: true };
  // null or absent: the backend did not establish this, so neither do we.
  return UNKNOWN;
}

export type ControllerInput = {
  peripheral: PeripheralStatusPayload | null;
  /** Re-Gear's shortcut input source. Not controller presence. */
  shortcutAvailable?: boolean;
};

export function controllerPresentation(input: ControllerInput): ControllerPresentation {
  const controller = input.peripheral?.controller;
  const shortcut = fact(input.shortcutAvailable, "Available", "Unavailable");

  if (!controller) {
    return {
      available: false,
      reason: "Controller status unavailable. No peripheral reading has been received.",
      builtin: UNKNOWN, external: UNKNOWN, precision: "unknown", precisionNote: null,
      // The shortcut source is observed separately, so it can still be reported
      // even when no peripheral reading exists.
      shortcut, planned: PLANNED_CONTROLLER_FEATURES,
    };
  }

  const exact = controller.exact === true && controller.complete === true;
  const precision: ControllerPrecision = exact ? "exact"
    : controller.complete === true || controller.exact === true ? "partial" : "unknown";

  const builtin = fact(controller.builtin_available, "Available", "Not available");
  const external = fact(controller.external_connected, "Connected", "Not connected");
  const anyFact = builtin.known || external.known;

  return {
    available: anyFact,
    reason: anyFact ? null
      : "Controller status unavailable. The reading contained no usable facts.",
    builtin, external, precision,
    precisionNote: precision === "exact" ? null
      : "This reading is incomplete; some controller details are unverified.",
    shortcut,
    planned: PLANNED_CONTROLLER_FEATURES,
  };
}
