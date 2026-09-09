/** The Command Center quick-tile grid: pure, no React, no I/O, no requests.
 *
 * Approved layout (LAYOUT_APPROVAL.md, baseline df6a36c): two columns of
 * FPS target, TDP limit, Auto TDP and Display target, plus a fifth Safe
 * Disconnect tile marked In development.
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

import type { PerformanceState, TileValue } from "./performance-state";
import { fpsTile, wattsValue } from "./performance-state";

export type TileId = "fps" | "tdp" | "auto-tdp" | "display" | "safe-disconnect";

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
};

/** Fixed order and fixed length. Two columns; the fifth tile sits alone on the
 * last row, which stepGrid already resolves from either cell above it. */
export const TILE_ORDER: TileId[] = ["fps", "tdp", "auto-tdp", "display", "safe-disconnect"];
export const TILE_COLUMNS = 2;

export type CommandCenterInput = {
  performance: PerformanceState;
  /** Display target as already observed by the panel, e.g. a mode label.
   * Absent means unknown; it is never inferred from anything else. */
  displayTarget?: string;
  /** True only when the owning backend reports a usable safe-disconnect path.
   * Absent or false keeps the tile In development. Never inferred from
   * topology, connection state, or the fact that two devices are online. */
  safeDisconnectSupported?: boolean;
};

const ACTION_LABEL: Record<PerformanceState["action"], string | null> = {
  stop: "Stop", start: "Start", open: "Open Auto TDP", none: null,
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
      actionLabel: performance.supported ? "Open Auto TDP" : null,
      developmental: false,
    },
    // One context-sensitive action, never a toggle: Stop while running, Start
    // only when explicitly configured and permitted, otherwise open the module.
    "auto-tdp": {
      id: "auto-tdp", title: "Auto TDP",
      value: { text: performance.active ? "Running" : performance.supported ? "Off" : "Unavailable",
        known: performance.supported },
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
      id: "display", title: "Display target",
      value: input.displayTarget
        ? { text: input.displayTarget, known: true }
        : { text: "Unknown", known: false },
      available: true, reason: null, activation: "open", actionLabel: "Open eGPU",
      developmental: false,
    },
    // Prepared, not functional. Opens an informational notice and performs no
    // disconnect. Enablement waits on the owning backend's verified capability
    // and its confirmation contract; it is never inferred here.
    "safe-disconnect": {
      id: "safe-disconnect", title: "Safe Disconnect",
      value: { text: input.safeDisconnectSupported === true ? "Ready" : "In development",
        known: false },
      available: false,
      reason: "Not yet available. Re-Gear cannot confirm a safe disconnect.",
      activation: "notice", actionLabel: null,
      developmental: input.safeDisconnectSupported !== true,
    },
  };

  return TILE_ORDER.map((id) => tiles[id]);
}

/** Grid position of a tile, for focus restoration after returning to the grid. */
export function tileIndex(id: TileId): number {
  const index = TILE_ORDER.indexOf(id);
  return index < 0 ? 0 : index;
}
