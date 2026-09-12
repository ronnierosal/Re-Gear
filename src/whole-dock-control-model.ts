export type DockAction = "whole_dock_disconnect" | "whole_dock_reconnect" | "whole_dock_shutdown";
export type DockIntent = "disconnect" | "shutdown";

const shutdownRefusals: Record<string, string> = {
  "dock_power.preflight_changed": "Readiness changed before shutdown could be requested.",
  "dock_power.intent_not_recorded": "The shutdown request could not be recorded.",
  "dock_power.request_unverified": "Shutdown submission could not be verified.",
  "dock_power.unresolved": "The shutdown result is unresolved.",
  "dock_power.already_consumed": "The original shutdown request has already been used.",
  "dock_power.disconnect_unverified": "Dock disconnect could not be verified; shutdown was not requested.",
  "dock_power.invalid_intent": "The shutdown request was not accepted.",
  "dock_power.boot_unverified": "The current system session could not be verified.",
  "dock_power.busy": "Another power request is still in progress.",
  "dock_power.sleep_unverified": "Sleep with the dock connected is not available.",
};
const shutdownTeardownRefusals = new Set([
  "dock_teardown.usb_peripherals_or_unknown", "dock_teardown.begin_preflight_refused",
  "dock_teardown.sleep_inhibition_required", "dock_teardown.approval_superseded",
  "dock_teardown.session_unknown", "dock_mutation.inhibited", "dock_mutation.unavailable_or_busy",
  "dock_teardown.gpu_release_unverified", "dock_teardown.portable_return_refused",
  "dock_teardown.portable_return_unverified", "dock_teardown.portable_acknowledgement_unverified",
  "dock_teardown.trial_unresolved",
]);
export function shutdownRequested(status: any): boolean {
  return status?.schema_version === 1 && status.busy === false && status.safe_to_unplug === false
    && status.code === "dock_power.request_accepted_unverified" && status.power_action === "shutdown"
    && status.power_requested === true && status.ok === true;
}
/** A malformed/ambiguous response must not release the persistent retry guard. */
export function dockRequestSettled(status: any, request: string, intent: DockIntent): boolean {
  if (intent !== "disconnect" && intent !== "shutdown") return false;
  if (status?.request_id !== request || status.schema_version !== 1 || status.busy !== false || status.safe_to_unplug !== false) return false;
  if (intent === "disconnect") return true;
  if (shutdownRequested(status)) return true;
  return status.ok === false && (status.power_requested === undefined || status.power_requested === false)
    && (status.power_action === undefined || status.power_action === "shutdown")
    && (Object.hasOwn(shutdownRefusals, status.code) || shutdownTeardownRefusals.has(status.code));
}
/** Explicit intent selects the existing guarded route; capability metadata is
 * not an input and cannot authorize a write. Shutdown never becomes reconnect. */
export function dockIntentControl(status: any, snapshot: any, intent: DockIntent, now = Date.now()): ReturnType<typeof dockControl> {
  if (intent === "disconnect") return dockControl(status, snapshot, now);
  if (intent !== "shutdown") return { action: null, label: "Action unavailable", message: "This action is not supported." };
  if (shutdownRequested(status)) return { action: null, label: "Shutdown requested", message: "Shutdown was requested. Completion is not confirmed. Keep the cable connected." };
  if (snapshot?.schema_version !== 3) return { action: null, label: "Shutdown unavailable", message: "Current system status is unavailable. Refresh before continuing." };
  const view = dockControl(status, snapshot, now);
  return {
    action: view.action === "whole_dock_disconnect" ? "whole_dock_shutdown" : null,
    label: view.action === "whole_dock_disconnect" ? "Disconnect and shut down" : view.action === "whole_dock_reconnect" ? "Shutdown unavailable" : view.label,
    message: view.action === "whole_dock_disconnect"
      ? "Disconnect the dock in software, then request shutdown after verification."
      : view.action === "whole_dock_reconnect"
        ? "The dock is already disconnected in software. Shutdown continuation is unavailable; do not repeat the operation."
        : (shutdownRefusals[status?.code] ? shutdownRefusals[status.code] + " Keep the cable connected; do not repeat the operation." : view.message),
  };
}
export function dockControl(status: any, snapshot: any, now = Date.now()): { action: DockAction | null; label: string; message: string } {
  const unavailable = { action: null, label: "Safely disconnect", message: "Disconnect status unavailable. Refresh before continuing." };
  if (status?.schema_version !== 1 || status.safe_to_unplug !== false || typeof status.busy !== "boolean") return unavailable;
  if (status.busy) return { action: null, label: "Working…", message: "Keep the cable connected. Re-Gear is checking the dock." };
  const observed = typeof snapshot?.observed_at === "string" ? Date.parse(snapshot.observed_at) : NaN;
  if (!Number.isFinite(observed) || observed > now || now - observed > 10000) return unavailable;
  if (status.code === "dock_teardown.software_down" && status.software_down === true) {
    return { action: snapshot?.game_state === "idle" ? "whole_dock_reconnect" : null,
      label: "Reconnect eGPU", message: "Software disconnect verified. Keep the cable connected for this trial." };
  }
  const fresh = status.code === "dock_teardown.no_trial";
  const restored = status.code === "dock_reconnect.software_reconnected" && status.software_reconnected === true && status.ok === true;
  if (!fresh && !restored) {
    const reasons: Record<string, string> = {
      "dock_teardown.usb_peripherals_or_unknown": "USB accessories or incomplete hub information prevented disconnect.",
      "dock_teardown.begin_preflight_refused": "The dock did not pass the readiness checks.",
      "dock_teardown.sleep_inhibition_required": "Re-Gear could not prevent sleep during disconnect.",
      "dock_teardown.approval_superseded": "The dock connection changed after confirmation.",
      "dock_teardown.session_unknown": "Re-Gear could not identify the Gaming Mode session.",
      "dock_mutation.inhibited": "A previous disconnect attempt still needs recovery.",
      "dock_mutation.unavailable_or_busy": "Re-Gear could not acquire the dock operation lock.",
      "dock_teardown.gpu_release_unverified": "The GPU release could not be verified.",
      "dock_teardown.portable_return_refused": "Re-Gear could not start the return to the handheld screen.",
      "dock_teardown.portable_return_unverified": "The return to the handheld screen could not be verified.",
      "dock_teardown.portable_acknowledgement_unverified": "The handheld display transition still needs recovery.",
    };
    const reason = status.arm_code === "arm_sequence.unapproved_holder" && status.release_stage === "release_refused"
      ? "A system service is still using the eGPU. Device removal did not start."
      : status.release_stage === "removed" && status.phase === "dock_teardown"
        ? "GPU release completed, but the dock disconnect could not be verified."
        : reasons[status.code] ?? "The last attempt is unresolved.";
    return { action: null, label: "Needs attention", message: reason + " Keep the cable connected; do not repeat the operation." };
  }
  if (snapshot?.game_state !== "idle") return { action: null, label: "Safely disconnect", message: "Close your game and wait for an idle reading before disconnecting." };
  if (snapshot?.egpu_link?.state !== "up") return { action: null, label: "Safely disconnect", message: "Waiting for the eGPU to be detected." };
  if (typeof status.attachment_token !== "string" || !/^[a-f0-9]{64}:[a-f0-9]{64}$/.test(status.attachment_token)) return unavailable;
  return { action: "whole_dock_disconnect", label: "Safely disconnect", message: restored
    ? "Software reconnect verified. Check picture, audio and controls."
    : "Return to the handheld and disconnect the dock in software." };
}
