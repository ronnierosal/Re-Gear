import type { PerformanceHandle } from "../use-performance";
import type { ControllerPresentation } from "../modules/controller-presentation";
import type { Tab } from "./model";

export type NonEgpuDetailState = {
  performance: PerformanceHandle;
  controller: ControllerPresentation;
};
export type NonEgpuDetailSource = {
  read(): NonEgpuDetailState | null;
  subscribe(listener: () => void): () => void;
};

/** Shares the existing owner's handles, never starts polling or creates a
 * second request controller. Clear when that owner unmounts. */
export function createNonEgpuDetailPublisher() {
  let current: NonEgpuDetailState | null = null;
  const listeners = new Set<() => void>();
  const source: NonEgpuDetailSource = {
    read: () => current,
    subscribe(listener) { listeners.add(listener); return () => { listeners.delete(listener); }; },
  };
  return {
    source,
    publish(next: NonEgpuDetailState | null) {
      if (current === next) return;
      current = next;
      for (const listener of listeners) listener();
    },
  };
}

/** Explicit allowlist: a matching ID on another tab must not expose controls. */
export function nonEgpuDetailKind(tab: Tab, id: string): "power" | "controller" | null {
  if ((tab === "quick" || tab === "performance") && (id === "manual" || id === "auto")) return "power";
  if ((tab === "quick" && id === "controller") ||
      (tab === "controllers" && (id === "controller" || id === "builtin" || id === "priority"))) return "controller";
  return null;
}
