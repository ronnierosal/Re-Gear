import type { JourneyStatusPayload } from "./quick-access-ui";
import { sanitizeOfflineReasonCodes } from "./offline-readiness-detail.ts";

type UnknownRecord = Record<string, unknown>;

const STATES = {
  deferred_dock: new Set(["deferred", "eligible", "cancelled", "expired", "invalidated", "rejected"]),
  prepared_docked_idle: new Set(["not_yet_stable", "prepared", "invalidated"]),
  safe_undock: new Set(["ready_for_revalidation", "not_ready", "evidence_insufficient", "invalidated"]),
  unexpected_removal_recovery: new Set(["portable_fallback_verified", "recovery_incomplete", "needs_supervised_diagnosis"]),
  link_instability: new Set(["stable_observed", "instability_observed", "evidence_insufficient"]),
  offline_readiness: new Set(["ready_to_try_offline", "needs_attention", "online_check_needed", "unknown"]),
} as const;

function record(value: unknown): UnknownRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as UnknownRecord
    : null;
}

function state(value: unknown, allowed: ReadonlySet<string>): string | null {
  const candidate = record(value)?.state;
  return typeof candidate === "string" && allowed.has(candidate) ? candidate : null;
}

/**
 * Accept only known public journey states. Raw codes, unknown reasons, and all
 * unknown fields are intentionally discarded before Quick Access presentation.
 */
export function sanitizeJourneyStatus(value: unknown): JourneyStatusPayload | undefined {
  const source = record(value);
  if (!source) return undefined;
  const result: JourneyStatusPayload = {};
  for (const key of [
    "deferred_dock",
    "prepared_docked_idle",
    "safe_undock",
    "unexpected_removal_recovery",
  ] as const) {
    const valueState = state(source[key], STATES[key]);
    if (valueState) result[key] = { state: valueState, code: "" };
  }
  const link = record(source.link_instability);
  if (
    link?.schema_version === 1
    && typeof link.status === "string"
    && STATES.link_instability.has(link.status)
    && (
      (typeof link.current_state === "string" && ["up", "down"].includes(link.current_state))
      || (link.current_state === null && link.status === "evidence_insufficient")
    )
  ) {
    result.link_instability = {
      schema_version: 1,
      status: link.status as "stable_observed" | "instability_observed" | "evidence_insufficient",
      code: "",
      current_state: link.current_state as "up" | "down" | null,
    };
  }
  const offline = record(source.offline_readiness);
  if (
    offline?.schema_version === 1
    && typeof offline.status === "string"
    && STATES.offline_readiness.has(offline.status)
  ) {
    result.offline_readiness = {
      schema_version: 1,
      status: offline.status as "ready_to_try_offline" | "needs_attention" | "online_check_needed" | "unknown",
      reason_codes: sanitizeOfflineReasonCodes(offline.reason_codes),
    };
  }
  return Object.keys(result).length ? result : undefined;
}
