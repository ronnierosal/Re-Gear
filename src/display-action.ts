/** Decide whether a display switch is offered, and what it says.
 *
 * Extracted because there is now more than one place a player can reach it --
 * the dashboard action and the Command Center's display tile -- and the two
 * must not disagree about whether a return to the handheld is available. One
 * owner of that decision; callers render what it returns.
 *
 * The defect this fixes: `tv_docked` offered no return control at all. The
 * dashboard only recognised `docked_egpu`, so a player on the TV in the other
 * docked mode had no way back to the handheld from the panel. Both modes mean
 * the same thing to a player looking at a television, and both now offer it.
 *
 * Presentation only. Producing an enabled action is not permission to switch:
 * execution still goes through the backend's approval token, and a caller that
 * treats `disabled: false` as authorisation has skipped the gate that matters.
 *
 * Arguments are named rather than positional on purpose. Four booleans in a row
 * are four chances to transpose two of them, and a caller cannot see which is
 * which at the call site.
 */

export interface DisplayActionState {
  /** The observed presentation mode, or undefined when not read yet. */
  mode: string | undefined;
  /** A display request is already running. */
  busy: boolean;
  /** A prior transition's result is waiting to be acknowledged. */
  acknowledgementRequired: boolean;
  /** The transition journal is not idle. */
  journalBlocked: boolean;
  /** The controller chord is available, which only changes the wording. */
  shortcutAvailable: boolean;
}

export interface DisplayActionView {
  /** Where a switch would go, or null when no switch is available. */
  target: "ally" | "tv" | null;
  title: string;
  /** True when the control must not act. Never a claim that acting is safe. */
  disabled: boolean;
  /** Why it is disabled, or what pressing it does. Never a raw code. */
  description: string;
}

export function displayAction(state: DisplayActionState): DisplayActionView {
  const { mode, busy, acknowledgementRequired, journalBlocked } = state;
  // Both docked modes put the player in front of a television, so both offer
  // the way back. Treating them differently was the bug.
  const target: DisplayActionView["target"] =
    mode === "tv_docked" || mode === "docked_egpu"
      ? "ally"
      : mode === "portable"
        ? "tv"
        : null;
  const reason = busy
    ? "Wait for the current display request to finish."
    : acknowledgementRequired
      ? "Acknowledge the prior display transition result below to continue."
      : journalBlocked
        ? "Resolve the prior operation shown below before switching."
        : !target
          ? "Current display mode is unverified. Open Troubleshoot to inspect readiness."
          : null;
  return {
    target,
    title: busy
      ? "Switching…"
      : target === "ally"
        ? "Switch to handheld"
        : target === "tv"
          ? "Switch to TV"
          : "Display switch unavailable",
    disabled: reason !== null,
    description:
      reason ??
      (state.shortcutAvailable
        ? "Hold Back/View + Y for 3 seconds to switch."
        : "Checks readiness before switching. Controller shortcut unavailable."),
  };
}
