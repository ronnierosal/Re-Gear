import { useEffect, useRef, useState } from "react";
import { applyTdpLimit, getAutoTdpStatus, getTdpStatus, restoreTdpLimit, setTdpEnabled, startAutoTdp, stopAutoTdp, type AutoTdpStatusPayload, type TdpStatusPayload } from "../backend";
import { sanitizeTdpStatus, tdpControls } from "../tdp-ui";
import { sanitizeAutoTdpStatus, validAutoTdpRange } from "../auto-tdp-ui";

export type PerformanceSnapshot = {
  manual: TdpStatusPayload | null;
  auto: AutoTdpStatusPayload | null;
  busy: boolean;
  stopping: boolean;
};
export type PerformancePort = {
  getTdpStatus: () => Promise<unknown>;
  getAutoTdpStatus: () => Promise<unknown>;
  applyTdpLimit: (watts: number) => Promise<unknown>;
  restoreTdpLimit: () => Promise<unknown>;
  setTdpEnabled: (enabled: boolean) => Promise<unknown>;
  startAutoTdp: (target: number, minimum: number, maximum: number) => Promise<unknown>;
  stopAutoTdp: () => Promise<unknown>;
};
const backend: PerformancePort = { getTdpStatus, getAutoTdpStatus, applyTdpLimit, restoreTdpLimit, setTdpEnabled, startAutoTdp, stopAutoTdp };

/** One owner for reads and writes across routes. Stop can preempt a read/start;
 * other requests remain locked until every superseded transport has settled. */
export class PerformanceController {
  snapshot: PerformanceSnapshot = { manual: null, auto: null, busy: false, stopping: false };
  private visible = false;
  private generation = 0;
  private pending = 0;
  private refreshPending = false;
  private listeners = new Set<(value: PerformanceSnapshot) => void>();
  constructor(private port: PerformancePort = backend) {}
  subscribe(listener: (value: PerformanceSnapshot) => void) {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }
  private publish(value: Partial<PerformanceSnapshot>) {
    this.snapshot = { ...this.snapshot, ...value };
    for (const listener of this.listeners) listener(this.snapshot);
  }
  setVisible(visible: boolean) {
    if (visible === this.visible) return;
    this.visible = visible;
    ++this.generation;
    this.publish({ manual: null, auto: null });
    this.refreshPending = visible;
    if (visible && !this.pending) void this.refresh();
  }
  private async request(action: () => Promise<Partial<PerformanceSnapshot>>, priority = false) {
    if (!this.visible || (this.pending > 0 && !priority) || (priority && (this.snapshot.stopping || this.snapshot.auto?.stopping))) return;
    const generation = ++this.generation;
    this.pending++;
    this.publish({ busy: true, stopping: priority || this.snapshot.stopping });
    try {
      const next = await action();
      if (this.visible && generation === this.generation) this.publish(next);
    } catch {
      if (this.visible && generation === this.generation) this.publish({ manual: null, auto: null });
    } finally {
      this.pending--;
      if (!this.pending) {
        this.publish({ busy: false, stopping: false });
        if (this.visible && this.refreshPending) void this.refresh();
      }
    }
  }
  refresh = async () => {
    if (!this.visible) return;
    if (this.pending) { this.refreshPending = true; return; }
    this.refreshPending = false;
    await this.request(async () => {
      const [manual, auto] = await Promise.allSettled([this.port.getTdpStatus(), this.port.getAutoTdpStatus()]);
      return {
        manual: manual.status === "fulfilled" ? sanitizeTdpStatus(manual.value) : null,
        auto: auto.status === "fulfilled" ? sanitizeAutoTdpStatus(auto.value) : null,
      };
    });
  };
  private manualRequest(action: () => Promise<unknown>) {
    return this.request(async () => {
      const manual = sanitizeTdpStatus(await action());
      // A manual write can stop Auto TDP; re-read, never infer its state.
      let auto = null;
      try { auto = sanitizeAutoTdpStatus(await this.port.getAutoTdpStatus()); } catch { /* unknown */ }
      return { manual, auto };
    });
  }
  apply = async (watts: number) => {
    const manual = this.snapshot.manual;
    if (!tdpControls(manual).canApply || !Number.isInteger(watts) || manual?.minimum_watts == null || manual.maximum_watts == null
      || watts < manual.minimum_watts || watts > manual.maximum_watts) return;
    await this.manualRequest(() => this.port.applyTdpLimit(watts));
  };
  restore = async () => {
    if (tdpControls(this.snapshot.manual).canRestore) await this.manualRequest(this.port.restoreTdpLimit);
  };
  setEnabled = async (enabled: boolean) => {
    if (tdpControls(this.snapshot.manual).canToggle && (!enabled || this.snapshot.manual?.can_enable)) await this.manualRequest(() => this.port.setTdpEnabled(enabled));
  };
  start = async (target: number, minimum: number, maximum: number) => {
    if (!this.snapshot.auto?.can_start || !validAutoTdpRange(this.snapshot.manual, minimum, maximum, target)) return;
    await this.request(async () => {
      const auto = sanitizeAutoTdpStatus(await this.port.startAutoTdp(target, minimum, maximum));
      let manual = null;
      try { manual = sanitizeTdpStatus(await this.port.getTdpStatus()); } catch { /* unknown */ }
      return { auto, manual };
    });
  };
  stop = async () => {
    await this.request(async () => {
      const auto = sanitizeAutoTdpStatus(await this.port.stopAutoTdp());
      let manual = null;
      try { manual = sanitizeTdpStatus(await this.port.getTdpStatus()); } catch { /* unknown */ }
      return { auto, manual };
    }, true);
  };
}
export type PerformanceHandle = PerformanceSnapshot & Pick<PerformanceController, "refresh" | "apply" | "restore" | "setEnabled" | "start" | "stop">;

/** Mount once in the panel owner, then pass this handle to tiles and modules. */
export function usePerformance(visible: boolean): PerformanceHandle {
  const ref = useRef<PerformanceController | null>(null);
  if (!ref.current) ref.current = new PerformanceController();
  const controller = ref.current;
  const [snapshot, setSnapshot] = useState(controller.snapshot);
  useEffect(() => controller.subscribe(setSnapshot), [controller]);
  useEffect(() => {
    controller.setVisible(visible);
    return () => controller.setVisible(false);
  }, [controller, visible]);
  return { ...snapshot, refresh: controller.refresh, apply: controller.apply, restore: controller.restore,
    setEnabled: controller.setEnabled, start: controller.start, stop: controller.stop };
}
