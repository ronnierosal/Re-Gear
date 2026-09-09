/** Shared tile presentation. Writer enablement and the Auto TDP loop are separate contracts. */
import type { AutoTdpStatusPayload, TdpStatusPayload } from "../backend";
export type PerformanceAction = "stop" | "start" | "open" | "none";
export type PerformanceState = {
  active: boolean; autoKnown: boolean; stopping: boolean; supported: boolean; configuredWatts: number | null;
  configuredIsLimit: boolean; action: PerformanceAction; reason: string | null; busy: boolean;
};
export type PerformanceInput = {
  status: TdpStatusPayload | null;
  autoStatus?: AutoTdpStatusPayload | null;
  busy?: boolean;
  stopping?: boolean;
  /** Retained for callers; compact tiles never start a loop from configuration. */
  configured?: boolean;
};
export function performanceState(input: PerformanceInput): PerformanceState {
  const { status, autoStatus } = input;
  const busy = input.busy === true;
  const active = autoStatus?.running === true;
  const state = {
    active, autoKnown: autoStatus != null, stopping: input.stopping === true || autoStatus?.stopping === true, supported: status?.auto_tdp_available === true,
    configuredWatts: status?.current_watts ?? null,
    configuredIsLimit: status?.current_watts != null, busy,
  };
  // Stop preempts ordinary requests and remains available if manual evidence fails.
  if (active) return { ...state, action: input.stopping || autoStatus?.stopping ? "none" : "stop",
    reason: input.stopping || autoStatus?.stopping ? "Stopping Auto TDP…" : null };
  if (!status) return { ...state, action: "open", reason: "Performance status not yet observed." };
  if (busy) return { ...state, action: "none", reason: "Working…" };
  if (status.recovery_required) return { ...state, action: "open", reason: "Needs recovery in Auto TDP." };
  if (!state.supported) return { ...state, action: "open", reason: "This device has no verified TDP control." };
  if (!autoStatus) return { ...state, action: "open", reason: "Auto TDP status not yet observed." };
  return { ...state, action: "open", reason: autoStatus.can_start ? "Configure Auto TDP." : "Not available in the current state." };
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
