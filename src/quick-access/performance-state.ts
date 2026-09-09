/** Shared performance state for the Command Center tiles and the Auto TDP
 * module: pure, no React, no I/O, no requests.
 *
 * Two consumers now read the same TDP status: the compact tiles on the first
 * screen and the module page behind Modules. Deriving what each shows from the
 * raw payload twice is how they end up disagreeing -- one offering Start while
 * the other says unavailable, from the same bytes. This module is the single
 * derivation, so a disagreement has nowhere to come from.
 *
 * What it deliberately does NOT do:
 *
 * - It never implies enablement and loop start are the same operation. The
 *   approved design is explicit: Stop when active, Start only with an already
 *   valid explicitly configured range and existing permission, otherwise Open
 *   Auto TDP. A single toggle would conflate a power-writer capability with
 *   running a control loop.
 * - It never fabricates a value. Absent watts render as unknown, never as a
 *   plausible default, and never as a number carried over from a stale read.
 * - It never starts anything from guessed defaults.
 *
 * FPS is not modelled here. The approved FPS tile is a proposed new capability,
 * not Auto TDP's target FPS, and no backend provides it; see fpsTile.
 */

import type { TdpStatusPayload } from "../backend";

/** The one action the compact tile offers, chosen by state rather than by a
 * toggle. `open` means send the player to the module instead of acting. */
export type PerformanceAction = "stop" | "start" | "open" | "none";

export type PerformanceState = {
  /** Auto TDP is running now. */
  active: boolean;
  /** The device has a proven TDP writer at all. */
  supported: boolean;
  /** Configured power limit in watts, or null when not known. Never guessed. */
  configuredWatts: number | null;
  /** True when the value shown is a configured limit rather than telemetry. */
  configuredIsLimit: boolean;
  action: PerformanceAction;
  /** Why the tile cannot act, or null when it can. */
  reason: string | null;
  /** A request is in flight; the tile must not issue another. */
  busy: boolean;
};

export type PerformanceInput = {
  status: TdpStatusPayload | null;
  busy?: boolean;
  /** True once the player has an explicitly configured, valid range. Start is
   * never offered without it: starting from guessed defaults writes power
   * limits nobody chose. */
  configured?: boolean;
};

export function performanceState(input: PerformanceInput): PerformanceState {
  const { status } = input;
  const busy = input.busy === true;
  if (!status) {
    return {
      active: false, supported: false, configuredWatts: null, configuredIsLimit: false,
      action: "none", reason: "Performance status not yet observed.", busy,
    };
  }
  const supported = status.auto_tdp_available === true;
  const active = status.enabled === true;
  // Stop stays reachable whenever the loop is running, even if permission to
  // start again has since been withdrawn: a player must always be able to stop
  // something that is currently changing their device.
  if (active) {
    return {
      active: true, supported, configuredWatts: status.current_watts,
      configuredIsLimit: true, action: busy ? "none" : "stop",
      reason: busy ? "Working…" : null, busy,
    };
  }
  if (!supported) {
    return {
      active: false, supported: false, configuredWatts: null, configuredIsLimit: false,
      action: "none", reason: "This device has no verified TDP control.", busy,
    };
  }
  if (busy) {
    return { active: false, supported, configuredWatts: status.current_watts,
      configuredIsLimit: true, action: "none", reason: "Working…", busy };
  }
  if (status.recovery_required === true) {
    // Recovery outranks starting: begin a loop over an unrestored limit and the
    // player keeps whatever the interrupted session left behind.
    return { active: false, supported, configuredWatts: status.current_watts,
      configuredIsLimit: true, action: "open", reason: "Needs recovery in Auto TDP.", busy };
  }
  const startable = status.can_enable === true && input.configured === true;
  return {
    active: false, supported, configuredWatts: status.current_watts, configuredIsLimit: true,
    action: startable ? "start" : "open",
    reason: startable ? null
      : status.can_enable !== true ? "Not available in the current state."
      : "Set a power range in Auto TDP first.",
    busy,
  };
}

/** Late responses must not overwrite newer state. A request is only allowed to
 * apply while it is still the newest one issued; otherwise a slow reply lands
 * on top of a fresh read and the tile shows the past. */
export function acceptResponse(issued: number, current: number): boolean {
  return issued === current;
}

export type TileValue = { text: string; known: boolean };

/** Format watts for a tile. Unknown stays unknown rather than becoming 0 W. */
export function wattsValue(watts: number | null): TileValue {
  return typeof watts === "number" && Number.isFinite(watts)
    ? { text: `${Math.round(watts)} W`, known: true }
    : { text: "Unknown", known: false };
}

/** The FPS tile.
 *
 * FPS limiting is a proposed capability with no backend provider, and it is not
 * Auto TDP's target FPS. The tile keeps a fixed position in the grid and reads
 * unavailable: removing it would make the grid's shape depend on live evidence,
 * which moves a target under a player's thumb, and showing a number would be
 * fabricating one.
 */
export function fpsTile(): { available: false; value: TileValue; reason: string } {
  return {
    available: false,
    value: { text: "Unavailable", known: false },
    reason: "No verified frame-rate provider on this device.",
  };
}
