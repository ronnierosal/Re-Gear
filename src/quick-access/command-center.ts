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

import type { DisconnectStatusPayload } from "../backend";
import { disconnectPresentation } from "../egpu-disconnect-tile";
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
  /** Confirmation the player must accept before this tile acts, or null.
   * Owned by the surface that owns the operation; never rewritten here. */
  confirmation?: string | null;
  /** True when acting also turns the external display off. A separate approval
   * from the action itself, because it is visible to whoever is watching. */
  displayApprovalRequired?: boolean;
  /** True when this is a system state needing attention, not a failed press. */
  attention?: boolean;
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
  /** The owning backend's disconnect status, rendered through its own
   * presentation. Availability is a state the backend computes; it is never
   * derived here from topology, connection state, holders, or the fact that
   * two devices are online. Absent means not yet read, which is not "no". */
  disconnectStatus?: DisconnectStatusPayload | null;
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
      id: "display", title: "Display target",
      value: input.displayTarget
        ? { text: input.displayTarget, known: true }
        : { text: "Unknown", known: false },
      available: true, reason: null, activation: "open", actionLabel: "Choose target",
      developmental: false,
    },
    // Wired to the owning backend's contract. Every judgement below comes from
    // disconnectPresentation: whether the action may be offered, what it says,
    // whether the display approval is needed, and whether this is a system
    // needing attention rather than a failed press. Re-deriving any of that
    // here is how the tile and the operation start disagreeing.
    //
    // Software removal is not unplug clearance. The confirmation copy lives in
    // egpu-disconnect-tile.ts with the tests that pin it, and is passed through
    // untouched rather than restated here.
    "safe-disconnect": (() => {
      const view = disconnectPresentation(input.disconnectStatus ?? null);
      return {
        id: "safe-disconnect" as const, title: "Safe Disconnect",
        value: { text: view.value, known: view.available },
        available: view.available,
        reason: view.reason,
        activation: view.available ? "act" as const : "notice" as const,
        actionLabel: view.actionLabel,
        developmental: false,
        confirmation: view.confirmation,
        displayApprovalRequired: view.displayApprovalRequired,
        attention: view.attention,
      };
    })(),
  };

  return TILE_ORDER.map((id) => tiles[id]);
}

/** Grid position of a tile, for focus restoration after returning to the grid. */
export function tileIndex(id: TileId): number {
  const index = TILE_ORDER.indexOf(id);
  return index < 0 ? 0 : index;
}
