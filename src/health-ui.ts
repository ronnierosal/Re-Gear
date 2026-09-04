import type { SnapshotPayload } from "./backend";

type HealthState = NonNullable<SnapshotPayload["health"]>["state"];

const HEALTH_BLOCKER_MESSAGES: Record<string, string> = {
  "health.placement_degraded": "Current mode needs attention.",
  "health.placement_unknown": "Current mode needs verification.",
  "health.workflow_unknown": "Re-Gear recovery status needs review.",
  "health.session_degraded": "Steam session is not usable.",
  "health.session_unknown": "Steam session status needs verification.",
  "health.display_degraded": "Active display is not usable.",
  "health.display_unknown": "Active display needs verification.",
  "health.egpu_link_degraded": "eGPU link is down.",
  "health.egpu_link_unknown": "eGPU link needs verification.",
  "health.storage_degraded": "eGPU storage needs attention.",
  "health.storage_unknown": "eGPU storage status needs verification.",
  "health.controller_degraded": "Built-in controls are unavailable.",
  "health.controller_unknown": "Built-in controls need verification.",
  "health.audio_degraded": "Current audio output is not usable.",
  "health.audio_unknown": "Current audio output needs verification.",
  "health.no_observations": "Re-Gear health evidence is unavailable.",
  "health.duplicate_component": "Re-Gear health evidence is inconsistent.",
};

export function healthStatusLabel(
  health: { state: HealthState } | undefined,
  loading = false,
): string {
  if (loading) {
    return "Checking…";
  }
  switch (health?.state) {
    case "ready":
      return "Ready";
    case "recovering":
      return "Recovering";
    case "degraded":
      return "Degraded";
    case "attention_required":
      return "Needs attention";
    default:
      return "Unavailable";
  }
}

/**
 * Present only recognized public health blockers. Raw or future codes collapse
 * to one generic message, and no message is shown for a healthy payload.
 */
export function healthAttentionMessages(
  health: SnapshotPayload["health"] | undefined,
): string[] {
  if (!health || health.state === "ready" || !Array.isArray(health.blockers)) {
    return [];
  }
  const messages = health.blockers.map((blocker) =>
    HEALTH_BLOCKER_MESSAGES[blocker] ?? "Re-Gear health evidence needs review.",
  );
  return [...new Set(messages)].slice(0, 3);
}
