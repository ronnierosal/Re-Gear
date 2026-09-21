/** The Command Center quick-tile grid: pure, no React, no I/O, no requests.
 *
 * Production layout: stable two-column quick controls plus the requested
 * display, dock-power and read-only eGPU destinations. Unavailable controls
 * keep their cells so controller targets never move as evidence changes.
 *
 * The grid's shape is fixed. Every tile keeps its position whatever the live
 * evidence says, and an unusable tile reads unavailable with a reason instead
 * of disappearing. A tile that vanishes moves every tile after it under the
 * player's thumb as a snapshot arrives, and on a controller that is worse than
 * a target that politely declines. This is the same rule the section row
 * already learned the hard way.
 *
 * No tile fabricates a value. Unknown is rendered as unknown, never as a
 * plausible default and never as a number carried from a stale read.
 *
 * Nothing here performs an operation. Tiles describe what a player may do; the
 * caller owns every request, and every guard stays where it already lives.
 */

import type { DisplayActionView } from "../display-action";
import type { PerformanceState, TileValue } from "./performance-state";
import { fpsTile, wattsValue } from "./performance-state";

export type TileId = "fps" | "tdp" | "auto-tdp" | "display" | "safe-disconnect"
  | "sleep-connected" | "shutdown" | "resolution" | "egpu-status";

/** What activating a tile does. `open` navigates; `act` runs the caller's
 * guarded request; `notice` shows read-only information and changes nothing. */
export type TileActivation = "open" | "act" | "notice" | "none";

export type CommandCenterTile = {
  id: TileId;
  title: string;
  value: TileValue;
  available: boolean;
  /** Why it cannot be used, or null when it can. */
  reason: string | null;
  activation: TileActivation;
  /** Label for the activation, e.g. "Stop". Null when there is nothing to press. */
  actionLabel: string | null;
  /** Shown as In development: present on purpose, not yet functional. */
  developmental: boolean;
  /** Confirmation the player must accept before this tile acts, or null.
   * Owned by the surface that owns the operation; never rewritten here. */
  confirmation?: string | null;
  /** True when acting also turns the external display off. A separate approval
   * from the action itself, because it is visible to whoever is watching. */
  displayApprovalRequired?: boolean;
  /** True when this is a system state needing attention, not a failed press. */
  attention?: boolean;
};

/** Fixed order and fixed length. Two columns; the final odd tile remains
 * reachable from either cell above through the existing grid navigator. */
export const TILE_ORDER: TileId[] = [
  "fps", "tdp", "auto-tdp", "display", "safe-disconnect", "sleep-connected",
  "shutdown", "resolution", "egpu-status",
];
export const TILE_COLUMNS = 2;

export type CommandCenterInput = {
  performance: PerformanceState;
  /** Display target as already observed by the panel, e.g. a mode label.
   * Absent means unknown; it is never inferred from anything else. */
  displayTarget?: string;
  /** The single owner of dynamic TV/handheld wording and admission. */
  displayAction?: DisplayActionView;
};

const ACTION_LABEL: Record<PerformanceState["action"], string | null> = {
  stop: "Stop", start: "Start", open: "Configure", none: null,
};

export function commandCenterTiles(input: CommandCenterInput): CommandCenterTile[] {
  const performance = input.performance;
  const fps = fpsTile();

  const tiles: Record<TileId, CommandCenterTile> = {
    // Proposed capability with no provider. Keeps its slot, states why.
    fps: {
      id: "fps", title: "FPS target", value: fps.value, available: false,
      reason: fps.reason, activation: "none", actionLabel: null, developmental: false,
    },
    // The configured power limit, which is not telemetry of current draw.
    tdp: {
      id: "tdp", title: "TDP limit",
      value: performance.supported ? wattsValue(performance.configuredWatts)
        : { text: "Unavailable", known: false },
      available: performance.supported,
      reason: performance.supported ? null : "This device has no verified TDP control.",
      activation: performance.supported ? "open" : "none",
      actionLabel: performance.supported ? "Choose limit" : null,
      developmental: false,
    },
    // Stop a running loop; configure all other states in the module.
    "auto-tdp": {
      id: "auto-tdp", title: "Auto TDP",
      value: { text: performance.stopping ? "Stopping…" : performance.active ? "Running" : performance.autoKnown ? "Off" : "Unknown",
        known: performance.autoKnown },
      available: performance.action !== "none",
      reason: performance.reason,
      activation: performance.action === "open" ? "open"
        : performance.action === "none" ? "none" : "act",
      actionLabel: ACTION_LABEL[performance.action],
      developmental: false,
    },
    // Reading plus a route. Requesting a display change stays with the surface
    // that already owns its guards; this tile does not run a transition.
    display: {
      id: "display", title: input.displayAction?.title ?? "Display switch unavailable",
      value: input.displayTarget
        ? { text: input.displayTarget, known: true }
        : { text: "Unknown", known: false },
      available: input.displayAction?.disabled === false,
      reason: input.displayAction?.disabled === false ? null
        : input.displayAction?.description ?? "Current display mode is unverified.",
      activation: input.displayAction?.disabled === false ? "act" : "notice",
      actionLabel: input.displayAction?.disabled === false ? input.displayAction.title : null,
      developmental: false,
    },
    // This tile only opens the guarded WholeDockControl owner. It intentionally
    // makes no readiness judgement; that owner rereads the exact status,
    // snapshot and attachment token before offering its confirmation. Software
    // removal remains distinct from physical unplug clearance.
    "safe-disconnect": {
      id: "safe-disconnect", title: "Safe Disconnect",
      value: { text: "Guarded", known: true }, available: true, reason: null,
      activation: "act", actionLabel: "Review and disconnect", developmental: false,
    },
    "sleep-connected": {
      id: "sleep-connected", title: "Sleep — Keep eGPU Connected",
      value: { text: "Available", known: true }, available: true, reason: null,
      activation: "act", actionLabel: "Sleep connected", developmental: false,
    },
    shutdown: {
      id: "shutdown", title: "Disconnect then Shut Down",
      value: { text: "Guarded", known: true }, available: true, reason: null,
      activation: "act", actionLabel: "Review and shut down", developmental: false,
    },
    resolution: {
      id: "resolution", title: "Resolution",
      value: { text: "Unavailable", known: false }, available: false,
      reason: "No verified resolution provider is available.", activation: "notice",
      actionLabel: null, developmental: false,
    },
    "egpu-status": {
      id: "egpu-status", title: "eGPU Status",
      value: { text: "View", known: true }, available: true, reason: null,
      activation: "open", actionLabel: "Open status", developmental: false,
    },
  };

  return TILE_ORDER.map((id) => tiles[id]);
}

/** Grid position of a tile, for focus restoration after returning to the grid. */
export function tileIndex(id: TileId): number {
  const index = TILE_ORDER.indexOf(id);
  return index < 0 ? 0 : index;
}
