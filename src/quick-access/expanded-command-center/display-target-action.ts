import type { Tile } from "./model";

export type DisplayTargetActionState = {
  target: "ally" | "tv" | null;
  available: boolean;
  reason: string;
  egpuConnected?: boolean | null;
};

/** Project the existing guarded display owner into one stable Command Center action. */
export function displayTargetActionTile(state?: DisplayTargetActionState): Tile {
  const target = state?.target ?? null;
  const available = state?.available === true && target !== null;
  const connection = state ? Object.getOwnPropertyDescriptor(state, "egpuConnected") : undefined;
  const connected = (target === "ally" || target === "tv")
    && connection !== undefined && "value" in connection && connection.value === true;
  return {
    id: "display-target",
    title: target === "ally" ? "Switch to Handheld" : target === "tv" ? "Switch to TV" : "Switch Display",
    value: `${available ? "Ready" : "Unavailable"}${connected ? " · eGPU connected" : ""}`,
    detail: state?.reason || "Current display status unavailable",
    tone: available ? "quiet" : "unavailable",
    artworkControlId: target === "ally" ? "handheld" : "display-target",
  };
}
