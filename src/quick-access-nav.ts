/** Quick Access navigation view model: pure, no React, no I/O, no requests.
 *
 * The panel is roughly 310px wide and is driven by a controller, so the section
 * chooser is a single row of icon targets rather than a labelled tab strip:
 * five targets fit across that width, D-pad left/right moves between them, and
 * no drill-in level stands between the player and a control.
 *
 * Unavailable sections stay in the row and stay selectable. Hiding them would
 * make the row's shape depend on live evidence, so a target would move under a
 * player's thumb as a snapshot arrived. Selecting one shows why it cannot be
 * used, which is the answer the player actually needs.
 */

import type { QuickAccessSection, QuickAccessSectionId } from "./quick-access-sections";
import { resolveSectionId } from "./quick-access-sections";

/** Icon kinds this row draws. The renderer owns the paths. */
export type QuickAccessNavIcon = "connection" | "controller" | "gauge" | "monitor" | "tools";

const ICONS: Record<QuickAccessSectionId, QuickAccessNavIcon> = {
  egpu: "connection", controller: "controller", tdp: "gauge", display: "monitor", system: "tools",
};

export type QuickAccessNavItem = {
  id: QuickAccessSectionId;
  /** Accessible name for an icon-only target. */
  label: string;
  icon: QuickAccessNavIcon;
  active: boolean;
  /** Drawn dimmed. Still focusable, still selectable. */
  available: boolean;
};

export type QuickAccessNavView = {
  items: QuickAccessNavItem[];
  activeId: QuickAccessSectionId;
  /** Heading under the row. */
  heading: string;
  /** The section summary, or the reason when it cannot be used. */
  detail: string;
  /** True when the active section's controls must not be rendered. */
  blocked: boolean;
};

export function quickAccessNavView(
  sections: QuickAccessSection[], requested?: string,
): QuickAccessNavView {
  // resolveSectionId honours any section the row draws, including unavailable
  // ones: `blocked` and `detail` below are how such a selection explains
  // itself. It falls back only for a section that no longer exists.
  const activeId = resolveSectionId(sections, requested);
  const active = sections.find((section) => section.id === activeId);
  return {
    items: sections.map((section) => ({
      id: section.id, label: section.title, icon: ICONS[section.id],
      active: section.id === activeId, available: section.available,
    })),
    activeId,
    heading: active?.title ?? "",
    // A blocked section shows its reason in place of the summary: the summary
    // would describe controls the player cannot reach.
    detail: active ? (active.available ? active.summary : active.reason ?? "") : "",
    blocked: active ? !active.available : true,
  };
}

/** Move the selection along the row. Wraps, so the row has no dead ends. */
export function stepSection(
  view: QuickAccessNavView, direction: 1 | -1,
): QuickAccessSectionId {
  const index = view.items.findIndex((item) => item.id === view.activeId);
  if (index < 0 || view.items.length === 0) return view.activeId;
  const next = (index + direction + view.items.length) % view.items.length;
  // Stepping reaches unavailable sections deliberately: skipping them would
  // make the row's traversal order depend on live evidence.
  return view.items[next].id;
}
