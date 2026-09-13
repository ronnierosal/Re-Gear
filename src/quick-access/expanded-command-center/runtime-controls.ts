import type { UtilityId, UtilityPlacement } from "./utility-layout";
import type { UtilityReading } from "./utility-rail";
import type { CommandCenterNavigationDispatch } from "./navigation-contract";

/**
 * Stable UI/runtime boundary for the Command Center shell.
 * Runtime code supplies observations and action dispatch; UI code owns layout,
 * labels, pending/error presentation and controller affordances.
 */
export type CommandCenterRuntimeControls = {
  utilityLayout?: readonly UtilityPlacement[];
  utilityReadings?: Partial<Record<UtilityId, UtilityReading>>;
  onUtilityRequest?: (id: UtilityId, percent?: number) => Promise<void>;
  dispatch?: CommandCenterNavigationDispatch;
};

/** Brightness/volume are the first live wiring target. Keep the same request
 * seam for right-rail buttons so the shell does not grow one-off callbacks. */
export const commandCenterUtilityContract = {
  sliders: ["brightness", "volume"],
  rightRail: ["mic", "wifi", "overlay", "recording"],
  rightRailSlots: 4,
} as const;
