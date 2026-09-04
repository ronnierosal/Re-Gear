import type { SnapshotPayload } from "./backend";

export interface LinkHealthNotificationMemory {
  state: "up" | "down" | "unknown";
  reason: string;
  /** A changed unhealthy sample already opened this read-only episode. */
  instabilityNotified?: boolean;
}

export interface LinkHealthNotification {
  title: string;
  body: string;
  critical: boolean;
}

export interface LinkHealthNotificationDecision {
  memory: LinkHealthNotificationMemory | null;
  notification: LinkHealthNotification | null;
}

function isEgpuRelevantPlacement(mode: string): boolean {
  return ["boosted_handheld", "docked_igpu", "docked_egpu", "tv_docked"].includes(mode);
}

function reasonFor(payload: SnapshotPayload): string {
  const link = payload.snapshot.egpu_link;
  return link.reason || link.error || "link_unverified";
}

/**
 * Turn read-only link observations into sparse player notifications. A link
 * sample has no removal, recovery, or cable-fault authority; it can only ask
 * the player to review the current observation.
 */
export function decideLinkHealthNotification(
  previous: LinkHealthNotificationMemory | null,
  payload: SnapshotPayload,
): LinkHealthNotificationDecision {
  const link = payload.snapshot.egpu_link;
  if (!link.applicable) {
    return { memory: null, notification: null };
  }
  if (!isEgpuRelevantPlacement(payload.inference.mode)) {
    return { memory: previous, notification: null };
  }
  const current = {
    state: link.state,
    reason: reasonFor(payload),
    instabilityNotified: previous?.instabilityNotified ?? false,
  };
  if (previous === null) {
    return { memory: current, notification: null };
  }
  if (previous.state === current.state && previous.reason === current.reason) {
    return { memory: current, notification: null };
  }
  if (current.state === "up") {
    const wasUnstable = previous.state !== "up" && previous.instabilityNotified === true;
    return {
      memory: { ...current, instabilityNotified: false },
      notification: wasUnstable
        ? {
            title: "eGPU link observed again",
            body: "Re-Gear is preserving the current setup. Verify the display and controls before changing it.",
            critical: false,
          }
        : null,
    };
  }
  if (previous.instabilityNotified === true) {
    return { memory: { ...current, instabilityNotified: true }, notification: null };
  }
  return {
    memory: { ...current, instabilityNotified: true },
    notification: {
      title: current.state === "down" ? "eGPU link is down" : "eGPU link needs verification",
      body: "Re-Gear is preserving the current setup. Avoid disconnecting until the link is stable.",
      critical: false,
    },
  };
}
