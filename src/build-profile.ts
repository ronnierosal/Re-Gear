import type { Tab, Tile } from "./quick-access/expanded-command-center/model";

export type BuildProfile = "development" | "production";

/** An explicit projection, never saved customization or synthetic sample tiles. */
export function productionEgpuTiles(readings?: Partial<Record<Tab, readonly Tile[]>>): Partial<Record<Tab, readonly Tile[]>> {
  const displayTarget = readings?.egpu?.find(tile => tile.id === "display-target");
  const egpu = readings?.egpu?.find(tile => tile.id === "egpu")
    ?? readings?.quick?.find(tile => tile.id === "egpu");
  const disconnect = readings?.egpu?.find(tile => tile.id === "disconnect")
    ?? readings?.quick?.find(tile => tile.id === "disconnect");
  const sleep = readings?.egpu?.find(tile => tile.id === "disconnect-sleep");
  const shutdown = readings?.egpu?.find(tile => tile.id === "disconnect-shutdown");
  return { egpu: [
    displayTarget ?? { id: "display-target", title: "Display Target", value: "Unavailable", detail: "Current display status unavailable", tone: "unavailable" },
    egpu ?? { id: "egpu", title: "eGPU", value: "Unknown", detail: "Connection status unavailable" },
    disconnect ?? { id: "disconnect", title: "Safe Disconnect", value: "Unavailable", detail: "Current readiness unavailable" },
    sleep ?? { id: "disconnect-sleep", title: "Disconnect + Sleep", value: "Unavailable", detail: "Current readiness unavailable" },
    shutdown ?? { id: "disconnect-shutdown", title: "Safe Disconnect + Shutdown", value: "Unavailable", detail: "Current readiness unavailable" },
  ] };
}

export function buildAllowsDockIntent(profile: string, intent: string): boolean {
  return profile === "development"
    || (profile === "production" && (intent === "disconnect_only" || intent === "sleep" || intent === "shutdown"));
}
