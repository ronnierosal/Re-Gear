import type { AutoTdpStatusPayload, TdpStatusPayload } from "./backend";

const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const watts = (value: unknown): value is number => typeof value === "number" && Number.isInteger(value) && value > 0 && value <= 0xFFFFFFFF;
const fps = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value > 2 && value <= 1000;
const code = (value: unknown): value is string => typeof value === "string" && /^(auto_tdp|tdp|telemetry)\.[a-z0-9_]{1,80}$/.test(value);

export function sanitizeAutoTdpStatus(value: unknown): AutoTdpStatusPayload | null {
  if (!object(value) || value.schema_version !== 1 || !code(value.code)) return null;
  for (const name of ["can_start", "enabled", "running", "stopping"]) if (typeof value[name] !== "boolean") return null;
  if (value.activity_code !== null && !code(value.activity_code)) return null;
  if ((value.enabled && (!value.running || value.stopping)) || (value.stopping && !value.running)
      || (value.can_start && (value.running || value.code !== "auto_tdp.ready"))) return null;
  const empty = [value.target_fps, value.minimum_watts, value.maximum_watts].every((item) => item === null);
  if (!empty && (!fps(value.target_fps) || !watts(value.minimum_watts) || !watts(value.maximum_watts)
      || value.minimum_watts > value.maximum_watts)) return null;
  if (value.enabled && empty) return null;
  return value as unknown as AutoTdpStatusPayload;
}

export function validAutoTdpRange(manual: TdpStatusPayload | null, minimum: number | null, maximum: number | null, target: number): boolean {
  return !!(manual?.ready && !manual.recovery_required && fps(target) && watts(minimum) && watts(maximum)
    && manual.minimum_watts !== null && manual.maximum_watts !== null && manual.current_watts !== null
    && manual.minimum_watts <= minimum && minimum <= manual.current_watts
    && manual.current_watts <= maximum && maximum <= manual.maximum_watts);
}

export function autoTdpMessage(status: AutoTdpStatusPayload | null, manualMessage: string): string {
  if (!status) return "Auto TDP status is unavailable. Refresh or stop Auto TDP.";
  if (status.stopping) return "Stopping Auto TDP…";
  if (status.enabled && ["auto_tdp.configuration_missing", "auto_tdp.configuration_invalid", "auto_tdp.configuration_context_changed"].includes(status.code)) {
    return "Auto TDP is still on. Stop and revalidate the device configuration before starting again.";
  }
  if (status.enabled && status.code === "auto_tdp.game_or_render_unverified") return "Auto TDP is waiting for a running game in Portable mode.";
  if (status.code.startsWith("tdp.")) return manualMessage;
  const reasons: Record<string, string> = {
    "auto_tdp.configuration_missing": "Auto TDP needs a device configuration before it can start.",
    "auto_tdp.configuration_invalid": "The Auto TDP device configuration needs correction.",
    "auto_tdp.configuration_context_changed": "The device or power provider changed. Revalidate its Auto TDP configuration.",
    "auto_tdp.game_or_render_unverified": "Run a game in Portable mode before starting Auto TDP.",
    "telemetry.collection_cost_unbenchmarked": "Auto TDP needs a collection benchmark on this device.",
    "telemetry.auto_tdp_cost_exceeds_budget": "Collection exceeds the gameplay budget. Auto TDP cannot start.",
    "telemetry.collection_cost_exceeds_budget": "Collection exceeds the gameplay budget. Auto TDP cannot start.",
    "auto_tdp.request_invalid": "Choose a valid FPS target and power range.",
    "auto_tdp.start_unavailable": "Auto TDP could not start. Refresh and check the power range.",
    "auto_tdp.stopped": "Auto TDP is stopped. The current power limit is retained.",
    "auto_tdp.closing": "Power control is closing.",
    "auto_tdp.runtime_unavailable": "Auto TDP needs a fresh check. Refresh to try again.",
  };
  if (status.code === "auto_tdp.ready") return status.enabled ? "Auto TDP is running." : "Ready to start Auto TDP.";
  return Object.hasOwn(reasons, status.code) ? reasons[status.code] : "Auto TDP needs a fresh readiness check.";
}

export function autoTdpActivity(status: AutoTdpStatusPayload | null): string | null {
  if (status && ["auto_tdp.worker_unavailable", "auto_tdp.session_unavailable"].includes(status.activity_code ?? "")) return "Auto TDP stopped because the session became unavailable. Refresh before restarting.";
  if (!status?.enabled) return null;
  switch (status.activity_code) {
    case "auto_tdp.sample_unavailable": return "Waiting for fresh game performance and sensor evidence.";
    case "auto_tdp.context_settling": case "auto_tdp.settling": return "Collecting performance at the current power limit.";
    case "tdp.readback_verified": return "The latest power adjustment was verified.";
    default: return "Status updates when you refresh.";
  }
}

export class AutoTdpRequestGate {
  private generation = 0;
  private active = false;
  get busy() { return this.active; }
  begin(priority = false): number | null {
    if (this.active && !priority) return null;
    this.active = true;
    return ++this.generation;
  }
  current(generation: number) { return generation === this.generation; }
  finish(generation: number) { if (this.current(generation)) this.active = false; }
  invalidate() { this.generation++; this.active = false; }
}
