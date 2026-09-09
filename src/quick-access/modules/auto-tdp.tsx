import { TdpControls } from "../../tdp-controls";
import type { PerformanceHandle } from "../use-performance";

/** Shares the panel owner's status and requests; opening this page adds no collector. */
export function AutoTdpModule({ controller }: { controller: PerformanceHandle }) {
  return <TdpControls visible controller={controller} expanded />;
}
