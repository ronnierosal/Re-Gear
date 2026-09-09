/** Command Center routing and module registry: pure, no React, no I/O.
 *
 * The approved layout (docs/design/command-center/LAYOUT_APPROVAL.md, baseline
 * df6a36c) replaces the flat panel with a small navigation stack:
 *
 *     Command Center -> Modules -> module
 *     Command Center -> status detail
 *
 * The horizontal five-icon chooser is superseded. Measured evidence puts the
 * information column at 268px, where five 44px targets do not fit and do not
 * scale as modules are added; a labelled list costs one step and does not.
 *
 * Availability is derived from the existing `quickAccessSections` taxonomy
 * rather than recomputed, so a module and its section can never disagree about
 * whether a feature is usable. Unavailable destinations stay listed and stay
 * reachable: selecting one is how a player reads why it cannot be used. That
 * rule is load-bearing -- it is the defect this stack already shipped once.
 *
 * Nothing here asserts backend capability. A route is a place to render, never
 * a claim that an operation is supported.
 */

import type { QuickAccessSection, QuickAccessSectionId } from "../quick-access-sections";

/** Modules that own configuration and actions. Initial set per the plan. */
export type ModuleId = "egpu" | "auto-tdp" | "controller";

/** Read-only hardware status destinations, deliberately separate from modules.
 * The approved design keeps "eGPU status" and "Controller status" opening
 * detail, not configuration; routing them to a module would hand a player
 * controls when they asked to look. */
export type StatusId = "egpu" | "controller";

export type Route =
  | { kind: "command-center" }
  | { kind: "modules" }
  | { kind: "module"; id: ModuleId }
  | { kind: "status"; id: StatusId }
  | { kind: "troubleshoot" };

/** Stable identity for a route, used as the focus-restoration key. */
export function routeKey(route: Route): string {
  return route.kind === "module" || route.kind === "status" ? `${route.kind}:${route.id}` : route.kind;
}

export type ModuleEntry = {
  id: ModuleId;
  title: string;
  /** One line under the title in the Modules list. */
  summary: string;
  available: boolean;
  /** Why the module cannot be used yet. Null exactly when available. */
  reason: string | null;
};

/** Taxonomy section that owns each module's availability evidence. */
const SECTION_OF: Record<ModuleId, QuickAccessSectionId> = {
  egpu: "egpu", "auto-tdp": "tdp", controller: "controller",
};

const TITLE: Record<ModuleId, string> = {
  egpu: "eGPU", "auto-tdp": "Auto TDP", controller: "Controller",
};

/** Panel order. Stable through refresh: a row must not move under a thumb. */
export const MODULE_ORDER: ModuleId[] = ["egpu", "auto-tdp", "controller"];

/** Build the Modules list from the existing taxonomy.
 *
 * A module whose section is missing reads unavailable rather than being
 * dropped, because a destination that vanishes reads as a bug and unknown
 * state is never a capability claim.
 */
export function quickAccessModules(sections: QuickAccessSection[]): ModuleEntry[] {
  return MODULE_ORDER.map((id) => {
    const section = sections.find((candidate) => candidate.id === SECTION_OF[id]);
    if (!section) {
      return { id, title: TITLE[id], summary: "", available: false,
        reason: "Status not yet observed." };
    }
    return {
      id, title: TITLE[id], summary: section.summary,
      available: section.available, reason: section.available ? null : section.reason,
    };
  });
}

/** Look up one module, for rendering a module route's header and reason. */
export function moduleEntry(modules: ModuleEntry[], id: ModuleId): ModuleEntry | undefined {
  return modules.find((entry) => entry.id === id);
}

// ---------------------------------------------------------------- navigation

/** The stack always has Command Center at the bottom; it is never popped. */
export type NavStack = [Route, ...Route[]];

export const INITIAL_STACK: NavStack = [{ kind: "command-center" }];

export function currentRoute(stack: NavStack): Route {
  return stack[stack.length - 1];
}

/** Open a destination one level deeper.
 *
 * Re-opening the destination already on top is a no-op rather than a second
 * copy, so a repeated press cannot build a stack that needs two Backs to
 * leave. Depth is capped at Command Center plus two levels, matching the
 * approved shape; anything deeper would be a route this design does not have.
 */
export function pushRoute(stack: NavStack, route: Route): NavStack {
  if (routeKey(currentRoute(stack)) === routeKey(route)) return stack;
  const next = stack.length >= 3 ? ([stack[0], route] as NavStack) : ([...stack, route] as NavStack);
  return next;
}

export type BackResult = {
  stack: NavStack;
  /** True when there was no internal level left and the caller must let Steam's
   * own QAM Back handle the press. Swallowing it would trap the player. */
  delegate: boolean;
};

export function backRoute(stack: NavStack): BackResult {
  if (stack.length <= 1) return { stack, delegate: true };
  return { stack: stack.slice(0, -1) as NavStack, delegate: false };
}

/** The control to restore focus to when returning to a route: the one that
 * opened the level being left. Returning a player to the top of a list they
 * navigated into is the thing that makes a stack feel broken. */
export function focusKeyAfterBack(stack: NavStack): string {
  return routeKey(currentRoute(stack));
}

// ------------------------------------------------------------ grid traversal

/** Move within the two-column quick-tile grid.
 *
 * The approved layout requires left/right column and up/down row traversal.
 * Movement is clamped rather than wrapped: on a grid a wrap teleports the
 * thumb across the panel, which is disorienting in a way a single row is not.
 * An incomplete final row is handled by clamping to the last real tile, so a
 * fifth tile in a two-column grid never focuses an empty cell.
 */
export type GridDirection = "up" | "down" | "left" | "right";

export function stepGrid(
  index: number, count: number, columns: number, direction: GridDirection,
): number {
  if (count <= 0 || columns <= 0) return 0;
  const clamped = Math.min(Math.max(index, 0), count - 1);
  const row = Math.floor(clamped / columns);
  const column = clamped % columns;
  if (direction === "left") return column === 0 ? clamped : clamped - 1;
  if (direction === "right") return column === columns - 1 ? clamped : Math.min(clamped + 1, count - 1);
  if (direction === "up") return row === 0 ? clamped : clamped - columns;
  const below = clamped + columns;
  if (below < count) return below;
  // Down from the last full row lands on the incomplete row's last real tile,
  // so a fifth tile in a two-column grid is reachable from either cell above.
  const lastRow = Math.floor((count - 1) / columns);
  return row < lastRow ? count - 1 : clamped;
}

// ------------------------------------------------- what the route implies

/** True when Back has an internal level to pop.
 *
 * The caller uses this to decide whether to attach a cancel handler at all.
 * Deciding inside a React state updater does not work: an updater may be
 * deferred or replayed, so a value assigned from inside one and read straight
 * afterwards is not a reliable answer, and a handler that is attached but
 * declines to act has already swallowed the press.
 */
export function hasInternalLevel(stack: NavStack): boolean {
  return stack.length > 1;
}

/** Whether the diagnostics surfaces are actually on screen.
 *
 * `showDiagnostics` says the player opened them; it does not say they are
 * visible. On any pushed route the Command Center body is not rendered, so
 * collecting for surfaces nobody can see is work the player did not ask for.
 */
export function diagnosticsVisible(stack: NavStack, showDiagnostics: boolean): boolean {
  return showDiagnostics && currentRoute(stack).kind === "command-center";
}

/** A fresh Quick Access entry starts at Command Center.
 *
 * Steam may keep the plugin mounted between openings, so the stack survives a
 * close unless it is reset. Reopening into a pushed route would make the panel
 * resume somewhere the player did not choose this time.
 */
export function stackOnPanelOpen(): NavStack {
  return INITIAL_STACK;
}

/** The Troubleshooting control's open/close rule.
 *
 * This is the surviving owner of the open-edge behaviour that the deleted
 * quick-access-section-state helper used to hold: opening asks for fresh
 * evidence, closing does not, and re-opening an already-open surface must not
 * request again.
 */
export function troubleshootingToggle(open: boolean): { next: boolean; refresh: boolean } {
  return { next: !open, refresh: !open };
}
