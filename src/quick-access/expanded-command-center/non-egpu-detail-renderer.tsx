import { useSyncExternalStore, type ReactNode } from "react";
import { AutoTdpModule } from "../modules/auto-tdp";
import { ControllerModule } from "../modules/controller";
import { nonEgpuDetailKind, type NonEgpuDetailSource } from "./non-egpu-detail-source";
import type { Tab, Tile } from "./model";

export type NonEgpuDetailRenderer = (tab: Tab, tile: Tile) => ReactNode;

/** Reuse the existing configuration UI and its busy/availability/request gates.
 * Manual and Auto TDP share the same power module; controller facts remain
 * read-only. Neither tile tone nor its display text grants action authority. */
function LiveDetail({ source, kind }: { source: NonEgpuDetailSource; kind: "power" | "controller" }) {
  const state = useSyncExternalStore(source.subscribe, source.read, source.read);
  if (!state) return null;
  return kind === "power" ? <AutoTdpModule controller={state.performance} />
    : <ControllerModule presentation={state.controller} />;
}

/** The owner composes this with its eGPU renderer using a null fallback. */
export function createNonEgpuDetailRenderer(source: NonEgpuDetailSource): NonEgpuDetailRenderer {
  return (tab, tile) => {
    const kind = nonEgpuDetailKind(tab, tile.id);
    return kind ? <LiveDetail source={source} kind={kind} /> : null;
  };
}
