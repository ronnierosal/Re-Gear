export type SleepRecoveryCheckpointKind =
  | "none"
  | "portable_verified"
  | "action_required"
  | "unavailable";

export interface SleepRecoveryCheckpointPayload {
  schema_version: number;
  kind: SleepRecoveryCheckpointKind;
  code: string;
  acknowledgement_required: boolean;
}

export interface SleepRecoveryNotification {
  title: string;
  body: string;
  critical: boolean;
}

export interface SleepRecoveryNotificationDecision {
  memory: Pick<SleepRecoveryCheckpointPayload, "kind" | "code"> | null;
  notification: SleepRecoveryNotification | null;
}

/**
 * Emit exactly one player notice for each durable, acknowledged restart result.
 * The checkpoint itself is owned by the canonical journal; this ref-sized
 * memory only suppresses repeated refreshes in the current UI process.
 */
export function decideSleepRecoveryNotification(
  previous: Pick<SleepRecoveryCheckpointPayload, "kind" | "code"> | null,
  checkpoint: SleepRecoveryCheckpointPayload,
): SleepRecoveryNotificationDecision {
  if (checkpoint.kind === "none" || !checkpoint.acknowledgement_required) {
    return { memory: null, notification: null };
  }
  const current = { kind: checkpoint.kind, code: checkpoint.code };
  if (previous?.kind === current.kind && previous.code === current.code) {
    return { memory: current, notification: null };
  }
  if (checkpoint.kind === "portable_verified") {
    return {
      memory: current,
      notification: {
        title: "Interrupted sleep request closed",
        body: "Re-Gear verified the handheld path after restart. Sleep was not continued. Game/session outcome was not verified.",
        critical: false,
      },
    };
  }
  if (checkpoint.kind === "action_required") {
    return {
      memory: current,
      notification: {
        title: "Interrupted sleep request needs attention",
        body: "Re-Gear did not continue sleep or claim handheld recovery. Review the current status before trying again.",
        critical: false,
      },
    };
  }
  return {
    memory: current,
    notification: {
      title: "Sleep recovery status unavailable",
      body: "Re-Gear did not continue sleep. Review the current status before trying again.",
      critical: false,
    },
  };
}
