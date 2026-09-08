/** Which Quick Access section the panel is showing: pure, no React, no I/O.
 *
 * The panel already gates six surfaces — journey, sleep protection, disconnect
 * readiness, support bundle, troubleshooting details and navigation — behind a
 * single `showDiagnostics` boolean driven by the Troubleshooting control. That
 * boolean is load-bearing beyond visibility: it also gates the optional
 * diagnostics refresh and is restored from persisted compact state.
 *
 * So the chooser does not replace it. The System section *is* that boolean, and
 * this module is the one place that says so. Keeping a single source of truth
 * means the row and the existing control can never disagree about whether the
 * System surfaces are open, which is the failure a second piece of state would
 * eventually produce.
 *
 * Only System is wired here. The other four targets change the selection and
 * nothing else yet; their content moves behind them one section at a time.
 */

import type { QuickAccessSectionId } from "./quick-access-sections";

export type SectionSelection = {
  /** The existing panel boolean. True exactly when the System section is open. */
  showDiagnostics: boolean;
  /** The row target to fall back to when System is closed. */
  chosen: QuickAccessSectionId;
};

/** The section the chooser should resolve against. */
export function requestedSectionId(selection: SectionSelection): QuickAccessSectionId {
  return selection.showDiagnostics ? "system" : selection.chosen;
}

export type SectionSelectionResult = {
  next: SectionSelection;
  /** True when the caller must kick a diagnostics refresh, matching the
   * existing Troubleshooting control: opening System is what asks for fresh
   * evidence, and only a transition into System does. */
  refresh: boolean;
};

/** Move the selection to `id`, preserving the existing open/close semantics. */
export function applySectionSelection(
  selection: SectionSelection, id: QuickAccessSectionId,
): SectionSelectionResult {
  if (id === "system") {
    return {
      next: { showDiagnostics: true, chosen: selection.chosen },
      // Re-selecting System while it is already open must not re-request; the
      // existing control refreshes on the closed -> open edge only.
      refresh: !selection.showDiagnostics,
    };
  }
  // Choosing any other target closes System. Leaving it open underneath would
  // put two sections on screen at once, which is the problem being fixed.
  return { next: { showDiagnostics: false, chosen: id }, refresh: false };
}
