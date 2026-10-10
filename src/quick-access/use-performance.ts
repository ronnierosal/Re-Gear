import { useEffect, useRef, useState } from "react";
import { applyTdpLimit, getAutoTdpStatus, getTdpStatus, restoreTdpLimit, setTdpEnabled, startAutoTdp, stopAutoTdp, type AutoTdpStatusPayload, type TdpStatusPayload } from "../backend";
import { sanitizeTdpStatus, tdpControls, manualPresetOptions, type ManualPresetIntent, type CustomTdpDraft, validCustomTdpDraft, retireCustomTdpDraft, createCustomTdpDraft, TDP_CYCLE_MODES, tdpCyclePresentation, tdpMessage, type TdpCycleMode, type TdpCycleIntent } from "../tdp-ui";
import { sanitizeAutoTdpStatus, validAutoTdpRange } from "../auto-tdp-ui";

export type PerformanceSnapshot = {
  manual: TdpStatusPayload | null;
  auto: AutoTdpStatusPayload | null;
  busy: boolean;
  stopping: boolean;
  cycleSelected?: TdpCycleMode | null;
  cyclePending?: TdpCycleMode | null;
  cycleReason?: string | null;
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

export type PerformanceClock = {
  now(): number;
  schedule(callback: () => void, milliseconds: number): () => void;
};
const clock: PerformanceClock = {
  now: () => performance.now(),
  schedule(callback, milliseconds) {
    const timer = setTimeout(callback, milliseconds);
    return () => clearTimeout(timer);
  },
};
const REFRESH_MS = 3_000;
const LIFETIME_MS = 10_000;

/** One owner for reads and writes across routes. Stop can preempt a read/start;
 * other requests remain locked until every superseded transport has settled. */
export class PerformanceController {
  snapshot: PerformanceSnapshot = { manual: null, auto: null, busy: false, stopping: false };
  private visible = false;
  private cycleVisible = false;
  private cycleIntents = new WeakSet<TdpCycleIntent>();
  private cycleDrafts = new WeakMap<CustomTdpDraft, TdpCycleIntent>();
  private generation = 0;
  private pending = 0;
  private refreshPending = false;
  private listeners = new Set<(value: PerformanceSnapshot) => void>();
  private expiresAt = 0;
  private cancelRefresh?: () => void;
  private cancelExpiry?: () => void;
  constructor(private port: PerformancePort = backend, private time: PerformanceClock = clock) {}
  subscribe(listener: (value: PerformanceSnapshot) => void) {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }
  private publish(value: Partial<PerformanceSnapshot>) {
    if ("manual" in value || "auto" in value || value.busy === true || value.stopping === true) this.cycleIntents = new WeakSet();
    this.snapshot = { ...this.snapshot, ...value };
    for (const listener of this.listeners) listener(this.snapshot);
  }
  private expire() {
    if (this.time.now() >= this.expiresAt && (this.snapshot.manual || this.snapshot.auto)) {
      this.publish({ manual: null, auto: null });
    }
  }
  private scheduleRefresh() {
    this.cancelRefresh?.();
    this.cancelRefresh = undefined;
    if (this.visible) this.cancelRefresh = this.time.schedule(() => void this.refresh(), REFRESH_MS);
  }
  setVisible(visible: boolean) {
    if (visible === this.visible) return;
    this.visible = visible;
    if (!visible) this.setCycleVisible(false);
    this.cancelRefresh?.();
    this.cancelExpiry?.();
    this.expiresAt = 0;
    ++this.generation;
    this.publish({ manual: null, auto: null });
    this.refreshPending = visible;
    if (visible && !this.pending) void this.refresh();
  }
  private async request(action: () => Promise<Partial<PerformanceSnapshot>>, priority = false) {
    if (!this.visible || (this.pending > 0 && !priority) || (priority && (this.snapshot.stopping || this.snapshot.auto?.stopping))) return;
    const generation = ++this.generation;
    // These schema-1 responses have no device observation timestamp. Bound
    // their client lifetime from request START, never an unrelated GPU sample
    // or the receipt of a delayed response. This is not hardware verification.
    const startedAt = this.time.now();
    this.cancelRefresh?.();
    this.pending++;
    this.publish({ busy: true, stopping: priority || this.snapshot.stopping });
    try {
      const next = await action();
      if (this.visible && generation === this.generation) {
        this.cancelExpiry?.();
        this.expiresAt = startedAt + LIFETIME_MS;
        if (this.time.now() >= this.expiresAt) this.publish({ manual: null, auto: null });
        else {
          this.publish(next);
          this.cancelExpiry = this.time.schedule(() => this.expire(), this.expiresAt - this.time.now());
        }
      }
    } catch {
      if (this.visible && generation === this.generation) this.publish({ manual: null, auto: null });
    } finally {
      this.pending--;
      if (!this.pending) {
        this.publish({ busy: false, stopping: false });
        if (this.visible && this.refreshPending) void this.refresh();
        else this.scheduleRefresh();
      }
    }
  }
  setCycleVisible = (visible: boolean) => {
    if (this.cycleVisible === visible) return;
    this.cycleVisible = visible;
    this.cycleIntents = new WeakSet();
    this.cycleDrafts = new WeakMap();
    this.publish({ cycleSelected: null, cyclePending: null, cycleReason: null });
  };
  createCycleIntent = (): TdpCycleIntent | null => {
    this.expire();
    if (!this.visible || !this.cycleVisible || this.pending || this.snapshot.busy || this.snapshot.stopping) return null;
    const intent = Object.freeze({ manual: this.snapshot.manual, auto: this.snapshot.auto });
    this.cycleIntents.add(intent);
    return intent;
  };
  private currentCycleIntent(intent: TdpCycleIntent | null) {
    this.expire();
    return !!intent && this.visible && this.cycleVisible && !this.pending && !this.snapshot.busy && !this.snapshot.stopping
      && this.cycleIntents.has(intent) && intent.manual === this.snapshot.manual && intent.auto === this.snapshot.auto;
  }
  private cycleUnavailable(mode: TdpCycleMode): string | null {
    const { manual, auto } = this.snapshot;
    if (!manual || !auto) return "Power status unavailable. Refresh to check admission.";
    if (this.snapshot.stopping || auto.running || auto.stopping || auto.enabled) return "Stop Auto TDP separately and wait for confirmed stopped status.";
    if (!tdpControls(manual).canApply) return tdpMessage(manual);
    if (mode === "Auto") {
      if (auto.target_fps == null || auto.minimum_watts == null || auto.maximum_watts == null) return "Auto needs configuration. Open Auto TDP to configure it.";
      if (!auto.can_start || !validAutoTdpRange(manual, auto.minimum_watts, auto.maximum_watts, auto.target_fps)) return "Auto unavailable: current readiness or configuration needs verification.";
    } else if (mode !== "Custom" && !manualPresetOptions(manual).find(option => option.label === mode)?.admitted) return `${mode} unavailable: preset admission needs verification.`;
    return null;
  }
  /** Activation consumes only the exact intent issued to this visible render. */
  cycle = (intent: TdpCycleIntent | null): boolean => {
    if (!this.currentCycleIntent(intent)) return false;
    const current = this.snapshot.cycleSelected ?? tdpCyclePresentation(this.snapshot).applied;
    const next = TDP_CYCLE_MODES[(current ? TDP_CYCLE_MODES.indexOf(current) + 1 : 0) % TDP_CYCLE_MODES.length];
    this.cycleIntents = new WeakSet();
    this.cycleDrafts = new WeakMap();
    const reason = this.cycleUnavailable(next);
    this.publish({ cycleSelected: next, cycleReason: reason });
    if (reason) return false;
    if (next === "Custom") return true;
    this.publish({ cyclePending: next });
    const task = next === "Auto" ? this.start(this.snapshot.auto!.target_fps!, this.snapshot.auto!.minimum_watts!, this.snapshot.auto!.maximum_watts!)
      : this.apply(manualPresetOptions(this.snapshot.manual).find(option => option.label === next)!.watts,
        { id: manualPresetOptions(this.snapshot.manual).find(option => option.label === next)!.id, status: this.snapshot.manual! });
    void task.finally(() => this.publish({ cyclePending: null }));
    return false;
  };
  createCycleDraft = (intent: TdpCycleIntent | null, watts = this.snapshot.manual?.current_watts): CustomTdpDraft | null => {
    if (!this.currentCycleIntent(intent) || this.snapshot.cycleSelected !== "Custom" || this.cycleUnavailable("Custom")) return null;
    const draft = createCustomTdpDraft(this.snapshot.manual, watts);
    if (draft) this.cycleDrafts.set(draft, intent!);
    return draft;
  };
  applyCycleDraft = async (draft: CustomTdpDraft) => {
    const intent = this.cycleDrafts.get(draft);
    if (!intent || !this.currentCycleIntent(intent) || this.snapshot.cycleSelected !== "Custom" || this.cycleUnavailable("Custom")) return;
    this.cycleDrafts.delete(draft);
    this.cycleIntents = new WeakSet();
    this.publish({ cyclePending: "Custom" });
    try { await this.apply(draft.watts, draft); }
    finally { this.publish({ cyclePending: null }); }
  };
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
      // Observe Auto independently after a manual result; never infer its state.
      let auto = null;
      try { auto = sanitizeAutoTdpStatus(await this.port.getAutoTdpStatus()); } catch { /* unknown */ }
      return { manual, auto };
    });
  }
  private manualLocked() {
    return this.snapshot.stopping || this.snapshot.auto?.running === true || this.snapshot.auto?.stopping === true;
  }
  apply = async (watts: number, preset?: ManualPresetIntent | CustomTdpDraft) => {
    this.expire();
    const manual = this.snapshot.manual;
    if (this.manualLocked()) return;
    const custom = preset && "kind" in preset;
    if (custom && !validCustomTdpDraft(preset as CustomTdpDraft, manual, watts)) return;
    if (preset && !custom && (preset.status !== manual || !manualPresetOptions(manual).some(option =>
      option.id === (preset as ManualPresetIntent).id && option.watts === watts && option.admitted))) return;
    if (!tdpControls(manual).canApply || !Number.isInteger(watts) || manual?.minimum_watts == null || manual.maximum_watts == null
      || watts < manual.minimum_watts || watts > manual.maximum_watts) return;
    if (custom) retireCustomTdpDraft(preset as CustomTdpDraft);
    await this.manualRequest(() => this.port.applyTdpLimit(watts));
  };
  restore = async () => {
    this.expire();
    if (!this.manualLocked() && tdpControls(this.snapshot.manual).canRestore) await this.manualRequest(this.port.restoreTdpLimit);
  };
  setEnabled = async (enabled: boolean) => {
    this.expire();
    if (!this.manualLocked() && tdpControls(this.snapshot.manual).canToggle && (!enabled || this.snapshot.manual?.can_enable)) await this.manualRequest(() => this.port.setTdpEnabled(enabled));
  };
  start = async (target: number, minimum: number, maximum: number) => {
    this.expire();
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
export type PerformanceHandle = PerformanceSnapshot & Pick<PerformanceController, "refresh" | "apply" | "restore" | "setEnabled" | "start" | "stop" | "setCycleVisible" | "createCycleIntent" | "cycle" | "createCycleDraft" | "applyCycleDraft">;

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
    setEnabled: controller.setEnabled, start: controller.start, stop: controller.stop,
    setCycleVisible: controller.setCycleVisible, createCycleIntent: controller.createCycleIntent, cycle: controller.cycle,
    createCycleDraft: controller.createCycleDraft, applyCycleDraft: controller.applyCycleDraft };
}
