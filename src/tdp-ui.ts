import type { TdpStatusPayload } from "./backend";

const reasons: Record<string, string> = {
  "tdp.disabled": "Power control is off.",
  "tdp.ready": "Ready to adjust handheld power.",
  "tdp.conflict": "Another power controller is present. Resolve the overlap before enabling.",
  "tdp.portable_required": "Use Portable mode before adjusting handheld power.",
  "tdp.placement_unverified": "Verify the active display and render GPU before adjusting power.",
  "tdp.egpu_presence_unverified": "The eGPU connection state needs verification.",
  "tdp.egpu_attached": "Power control is paused while an eGPU is attached. Follow the disconnect workflow before returning to handheld power control.",
  "tdp.egpu_power_profile_unavailable": "Power control for Boosted Handheld and Docked-eGPU is not validated yet.",
  "tdp.docked_power_profile_unavailable": "Power control for internal-GPU docked play is not validated yet.",
  "tdp.game_unknown": "Game activity needs verification.",
  "tdp.transition_active": "Wait for the current mode change to finish.",
  "tdp.ownership_unverified": "Power control ownership needs verification.",
  "tdp.enable_required": "Enable power control to make changes.",
  "tdp.readback_verified": "Power settings were verified.",
  "tdp.already_observed": "The requested power setting is already active.",
  "tdp.nothing_to_restore": "There are no saved power settings to restore.",
  "tdp.baseline_not_restorable": "The original power settings cannot yet be restored by this control.",
  "tdp.dispatch_rejected": "The automatic request was stopped before changing power.",
};

for (const code of ["busy", "closing", "writer_busy"]) reasons[`tdp.${code}`] = "Power control is busy. Refresh in a moment.";
for (const code of ["runtime_unavailable", "conflict_scan_unavailable", "host_unverified", "user_unverified", "boot_unverified", "owner_unavailable", "read_unavailable", "source_ambiguous", "firmware_unverified", "source_disagreement", "owner_changed", "observation_invalid", "observation_failed", "context_changed", "limit_invalid", "request_invalid", "request_out_of_range", "journal_unavailable", "revalidation_failed"]) reasons[`tdp.${code}`] = "Power settings need verification. Refresh to check again.";
for (const code of ["previous_write_uncertain", "external_change", "write_outcome_unknown", "readback_unverified", "write_unverified"]) reasons[`tdp.${code}`] = "Power settings need recovery before further changes.";

const known = (code: unknown): code is string => typeof code === "string" && Object.hasOwn(reasons, code);
const watts = (value: unknown): value is number => typeof value === "number" && Number.isInteger(value) && value > 0 && value <= 0xFFFFFFFF;
const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);

export function sanitizeTdpStatus(value: unknown): TdpStatusPayload | null {
  if (!object(value) || value.schema_version !== 1 || typeof value.auto_tdp_available !== "boolean" || !known(value.code)) return null;
  for (const field of ["enabled", "can_enable", "ready", "restore_available", "recovery_required"]) if (typeof value[field] !== "boolean") return null;
  const fields = [value.current_watts, value.minimum_watts, value.maximum_watts];
  const empty = fields.every((field) => field === null);
  if (!empty && (!fields.every(watts) || (value.minimum_watts as number) > (value.current_watts as number) || (value.current_watts as number) > (value.maximum_watts as number))) return null;
  // Bound option allocation without making a device capability claim.
  if (!empty && (value.maximum_watts as number) - (value.minimum_watts as number) > 255) return null;
  if ((value.ready && (!value.enabled || !value.can_enable || value.code !== "tdp.ready")) || (empty && (value.ready || value.can_enable || value.restore_available))) return null;
  const last = value.last_result;
  if (last !== null && (!object(last) || !["blocked", "unchanged", "applied", "restored", "recovery_required"].includes(last.state as string) || !known(last.code) || ![last.requested_watts, last.observed_watts].every((field) => field === null || watts(field)))) return null;
  return value as unknown as TdpStatusPayload;
}

export function tdpControls(status: TdpStatusPayload | null) {
  const usable = status !== null && status.current_watts !== null && !status.recovery_required;
  return {
    canToggle: status?.enabled === true || (usable && status.can_enable),
    canApply: usable && status.enabled && status.ready,
    canRestore: usable && status.restore_available,
  };
}

export function tdpMessage(status: TdpStatusPayload | null): string {
  if (!status) return "Power settings are unavailable. Refresh to try again.";
  if (status.recovery_required) return "Power settings need recovery before further changes.";
  return reasons[status.code] ?? "Power settings need verification.";
}

export function tdpResultMessage(status: TdpStatusPayload | null): string | null {
  return status?.last_result ? reasons[status.last_result.code] ?? "Power settings need verification." : null;
}

export class TdpRequestGate {
  private active = false;
  async run<T>(action: () => Promise<T>): Promise<T | undefined> {
    if (this.active) return undefined;
    this.active = true;
    try { return await action(); } finally { this.active = false; }
  }
}
