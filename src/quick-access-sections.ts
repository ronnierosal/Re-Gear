/** Quick Access section taxonomy: pure, no React, no I/O, no requests.
 *
 * The panel grew one flat scroll of surfaces, and Auto TDP made it longer. This
 * splits the same controls into named sections so one area renders at a time.
 *
 * A section is never silently dropped. When its feature is unavailable the
 * section still appears with the reason, because a control that vanishes reads
 * as a bug and a missing signal must never be presented as a working one.
 * Unknown evidence fails closed to unavailable, per the repository's rule that
 * unknown state is not a capability claim.
 */

export type QuickAccessSectionId = "egpu" | "controller" | "tdp" | "display" | "system";

export type QuickAccessSection = {
  id: QuickAccessSectionId;
  /** Panel heading. Kept short: the Decky Quick Access panel is ~310px wide. */
  title: string;
  /** One line under the title in the section list. */
  summary: string;
  available: boolean;
  /** Why the section cannot be used yet. Null exactly when available. */
  reason: string | null;
};

/** Evidence the taxonomy reads. Every field is optional: absent means unknown. */
export type QuickAccessSectionInput = {
  /** snapshot.inference.mode, or undefined before the first snapshot. */
  mode?: string;
  /** True once a fresh snapshot has been observed. */
  fresh?: boolean;
  /** Controller shortcut runtime reports a usable input source. */
  shortcutAvailable?: boolean;
  /** TdpStatusPayload.auto_tdp_available; the host proved a TDP writer exists. */
  autoTdpAvailable?: boolean;
  /** TdpStatusPayload.can_enable; the writer is currently permitted. */
  tdpCanEnable?: boolean;
  /** A health payload has been observed. */
  healthKnown?: boolean;
};

const WAITING = "Waiting for a fresh status update.";

export function quickAccessSections(input: QuickAccessSectionInput = {}): QuickAccessSection[] {
  const fresh = input.fresh === true;
  // eGPU stays reachable without fresh evidence: it owns the recovery and
  // troubleshooting controls a player needs precisely when readings are stale.
  const egpu: QuickAccessSection = {
    id: "egpu", title: "eGPU", summary: "Connection, display target, safe disconnect",
    available: true, reason: null,
  };
  const controller: QuickAccessSection = {
    id: "controller", title: "Controller", summary: "Shortcuts and button routing",
    available: input.shortcutAvailable === true,
    reason: input.shortcutAvailable === true ? null
      : input.shortcutAvailable === false ? "No verified controller input source. Shortcuts stay unavailable."
      : "Controller input source not yet observed.",
  };
  // Auto TDP requires both a proven writer and current permission to use it.
  const tdpBlocked = input.autoTdpAvailable !== true ? "This device has no verified TDP control."
    : input.tdpCanEnable === false ? "TDP control is not available in the current state."
    : input.tdpCanEnable !== true ? "TDP readiness not yet observed."
    : null;
  const tdp: QuickAccessSection = {
    id: "tdp", title: "Auto TDP", summary: "Power limit and automatic tuning",
    available: tdpBlocked === null, reason: tdpBlocked,
  };
  const display: QuickAccessSection = {
    id: "display", title: "Display & Audio", summary: "Output target and audio handoff",
    available: fresh && input.healthKnown === true,
    reason: fresh ? (input.healthKnown === true ? null : "Display and audio health not yet observed.") : WAITING,
  };
  // System owns diagnostics and support export, which must stay reachable when
  // everything else is unknown; that is when a player needs them most.
  const system: QuickAccessSection = {
    id: "system", title: "System", summary: "Diagnostics, readiness, support",
    available: true, reason: null,
  };
  return [egpu, controller, tdp, display, system];
}

/** The section a fresh panel opens on: the first available one.
 *
 * When none is available the first listed section is used rather than a fixed
 * id, so this never names a section the caller was not given and a nav row can
 * always resolve its selection to a target it actually draws.
 */
export function defaultSectionId(sections: QuickAccessSection[]): QuickAccessSectionId {
  return sections.find((section) => section.available)?.id ?? sections[0]?.id ?? "egpu";
}

/** Resolve a remembered selection, falling back when it is gone or unusable. */
export function resolveSectionId(
  sections: QuickAccessSection[], requested: string | undefined,
): QuickAccessSectionId {
  const match = sections.find((section) => section.id === requested);
  return match && match.available ? match.id : defaultSectionId(sections);
}
