export type DockAction = "whole_dock_disconnect" | "whole_dock_shutdown" | "whole_dock_sleep";
export type DockIntent = "disconnect" | "disconnect_only" | "shutdown" | "sleep";

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
  "dock_power.request_action_changed": "A different power action was already recorded for this request.",
  "dock_teardown.trial_unresolved": "The previous request stopped without reporting a result.",
};
/** The sleep route is the shutdown route with a different continuation, so
 * it shares the power refusals above and adds the outcomes only a sleep
 * handoff can have. Every one of these settles the request; none claims the
 * handheld slept unless the backend observed the cycle. */
const sleepRefusals: Record<string, string> = {
  ...shutdownRefusals,
  "dock_power.preflight_changed": "Readiness changed before sleep could be requested.",
  "dock_power.intent_not_recorded": "The sleep request could not be recorded.",
  "dock_power.disconnect_unverified": "Dock disconnect could not be verified; sleep was not requested.",
  "dock_power.sleep_observer_unavailable": "Re-Gear could not watch for the sleep cycle, so it did not request one.",
  "dock_power.sleep_protection_unverified": "Sleep protection could not be handed off and restored, so the handheld was left awake.",
  "dock_power.sleep_requested_unverified": "Sleep was requested; the result has not been observed yet.",
  "dock_power.sleep_cycle_failed": "Sleep was requested but the handheld did not complete a sleep cycle.",
  "dock_power.sleep_cycle_unresolved": "Sleep was requested; whether the handheld slept could not be determined.",
};
export function sleepObserved(status: any): boolean {
  return status?.schema_version === 1 && status.busy === false && status.safe_to_unplug === false
    && status.code === "dock_power.sleep_cycle_observed" && status.power_action === "sleep"
    && status.power_requested === true && status.sleep_cycle_observed === true && status.ok === true;
}
/** Every outcome that settles a request without a software disconnect.
 *
 * Two different backend mechanisms produce these and BOTH have to be covered.
 * `main.py` maps RAISED exceptions onto a fixed category set, and those were
 * the only ones listed here. But `WholeDockTeardown` and the dock-teardown
 * domain also RETURN codes, and a returned code is not filtered -- it reaches
 * `payload["code"]` verbatim with `ok=false`. Every one of those was missing.
 *
 * The cost of missing one is not cosmetic. An unsettled response leaves the
 * persistent retry guard armed, so the control keeps showing "Waiting to
 * verify the previous request." with the button disabled, across reopens,
 * forever. A USB drive mounted on the dock returns `mounted_storage` on a
 * first press and did exactly that. It also suppressed the message written
 * for the partial case -- "GPU release completed, but the dock disconnect
 * could not be verified" -- which is the one a player most needs when the GPU
 * is gone and the dock is still up.
 *
 * `whole-dock-refusal-coverage.test.mjs` derives the returned half of this set
 * from the backend source, so adding a code there fails the test rather than
 * silently bricking the control. Do not hand-maintain this against the
 * backend; let the test tell you. */
const shutdownTeardownRefusals = new Set([
  // Raised, then categorised by main.py.
  "dock_teardown.usb_peripherals_or_unknown", "dock_teardown.begin_preflight_refused",
  "dock_teardown.sleep_inhibition_required", "dock_teardown.approval_superseded",
  "dock_teardown.session_unknown", "dock_mutation.inhibited", "dock_mutation.unavailable_or_busy",
  "dock_teardown.gpu_release_unverified", "dock_teardown.portable_return_refused",
  "dock_teardown.portable_return_unverified", "dock_teardown.portable_acknowledgement_unverified",
  "dock_teardown.trial_unresolved",
  // Returned by the teardown application layer, reaching the payload verbatim.
  "dock_teardown.operation_required", "dock_teardown.busy", "dock_teardown.unresolved",
  "dock_teardown.identity_or_idle_unknown", "dock_teardown.transaction_owned",
  "dock_teardown.preflight_changed", "dock_teardown.usb_preflight_changed",
  "dock_teardown.usb_removal_unverified", "dock_teardown.tunnel_preflight_changed",
  "dock_teardown.final_state_unverified",
  // Returned by the dock-teardown domain preflight.
  "dock_teardown.gpu_scan_incomplete", "dock_teardown.gpu_still_attached",
  "dock_teardown.tunnel_scan_incomplete", "dock_teardown.tunnel_unidentified",
  "dock_teardown.tunnel_state_unknown", "dock_teardown.tunnel_capability_unsupported",
  "dock_teardown.tunnel_capability_unknown", "dock_teardown.tunnel_write_permission_denied",
  "dock_teardown.tunnel_write_permission_unknown", "dock_teardown.usb_scan_incomplete",
  "dock_teardown.storage_scan_incomplete", "dock_teardown.mounted_storage",
  "dock_teardown.storage_in_use", "dock_teardown.approval_required",
  "dock_teardown.already_down",
]);

/** Refusals decided BEFORE the request was ever correlated.
 *
 * `main.py` rejects a malformed or busy trial before it mints anything, so
 * these payloads carry no `request_id` and no `busy` key at all -- they are
 * `{schema_version, ok: false, code, safe_to_unplug}` and nothing else. The
 * settle predicate below tests both of those fields, so it could never match
 * them, and the pending record written at dispatch was orphaned forever.
 *
 * Nothing started, so there is nothing to keep waiting for. This is
 * deliberately a CLOSED set of exactly the two pre-correlation refusals rather
 * than a general "no request id means settled" rule: a missing correlation on
 * any other code still refuses to settle, because that could be a stale or
 * foreign status and releasing the guard on one would be the unsafe
 * direction. */
const preCorrelationRefusals = new Set([
  // Trial route, refused before a request is minted.
  "dock_teardown.trial_confirmation_required", "dock_teardown.busy",
  // Power route, same shape and same orphaning. Latent while nothing mounts
  // intent="shutdown", but live the moment one does -- and two of these
  // already carry player-facing copy in `shutdownRefusals`, which is evidence
  // they were always meant to be handled refusals rather than dead ends.
  "dock_power.request_action_changed", "dock_power.boot_unverified",
  "dock_power.invalid_intent", "dock_power.sleep_unverified",
]);

function refusedBeforeCorrelation(status: any): boolean {
  return status?.schema_version === 1 && status.ok === false
    && status.safe_to_unplug === false
    && status.request_id === undefined && status.busy === undefined
    && preCorrelationRefusals.has(status.code);
}
export function shutdownRequested(status: any): boolean {
  return status?.schema_version === 1 && status.busy === false && status.safe_to_unplug === false
    && status.code === "dock_power.request_accepted_unverified" && status.power_action === "shutdown"
    && status.power_requested === true && status.ok === true;
}
/** A malformed/ambiguous response must not release the persistent retry guard. */
/** One pending request, as the panel that dispatched it wrote it down. */
export interface PendingRecord {
  intent: DockIntent;
  request: string;
  /** Which panel wrote it. "" for a record written before panels carried an
   * identity, which by definition is not this one. */
  panel: string;
}

/** Stored form. The panel segment is what makes an abandoned record
 * recognisable; older two-part and bare forms still parse, with no panel. */
export function formatPendingRecord(intent: DockIntent, panel: string, request: string): string {
  return `v2:${intent}:${panel}:${request}`;
}
export function parsePendingRecord(raw: string | null | undefined): PendingRecord | null {
  if (!raw) return null;
  const parts = raw.split(":");
  if (parts[0] === "v2" && parts.length === 4) {
    const [, intent, panel, request] = parts;
    if (!request) return null;
    return { intent: intent as DockIntent, request, panel };
  }
  // Written by a build that had no panel identity, so it cannot be this
  // panel's: exactly the record a restart leaves behind.
  if (parts.length === 2 && (parts[0] === "shutdown" || parts[0] === "disconnect_only")) {
    return parts[1] ? { intent: parts[0] as DockIntent, request: parts[1], panel: "" } : null;
  }
  return parts.length === 1 && parts[0] ? { intent: "disconnect", request: parts[0], panel: "" } : null;
}

/** True when a record no live panel is waiting on can be retired.
 *
 * Freeing the dock restarts Gaming Mode, which destroys the panel waiting on
 * the reply, so the record it left behind outlives the answer. Correlation
 * alone can never retire that: a backend restarted with it reports no_trial
 * carrying no request id, so every later poll compares against nothing and
 * the control stays disabled for good.
 *
 * Two conditions, and both matter. The record must come from a panel that is
 * not this one -- a record this panel just wrote is one whose reply is still
 * coming, and retiring it on an idle reading taken before the backend marked
 * itself busy would drop the guard on a live request. And `in_flight` must be
 * the backend asserting, about its own process, that no worker is running: a
 * request it is not running and does not know is not outstanding.
 *
 * This retires the record. It never says the disconnect happened -- what the
 * device is in comes from the fresh status beside it, and the caller says the
 * result could not be confirmed rather than letting the control quietly go
 * usable. A backend too old to report `in_flight` settles nothing. */
export function dockRequestAbandoned(status: any, record: PendingRecord | null, panel: string): boolean {
  if (record === null || record.panel === panel) return false;
  return status?.schema_version === 1 && status.in_flight === false
    && status.busy === false && status.safe_to_unplug === false
    && status.request_id !== record.request;
}
export function dockRequestSettled(status: any, request: string, intent: DockIntent): boolean {
  if (intent !== "disconnect" && intent !== "disconnect_only" && intent !== "shutdown" && intent !== "sleep") return false;
  // A pre-correlation refusal settles: the backend rejected it before minting
  // a request, so no operation is outstanding and holding the guard would
  // disable the control permanently over something that never ran.
  if (refusedBeforeCorrelation(status)) return true;
  if (status?.request_id !== request || status.schema_version !== 1 || status.busy !== false || status.safe_to_unplug !== false) return false;
  if (intent === "disconnect") return true;
  if (intent === "disconnect_only") return softwareDisconnected(status) ||
    (status.ok === false && shutdownTeardownRefusals.has(status.code));
  if (intent === "sleep") {
    if (sleepObserved(status)) return true;
    return status.ok === false
      && (status.power_action === undefined || status.power_action === "sleep")
      && (Object.hasOwn(sleepRefusals, status.code) || shutdownTeardownRefusals.has(status.code));
  }
  if (shutdownRequested(status)) return true;
  return status.ok === false && (status.power_requested === undefined || status.power_requested === false)
    && (status.power_action === undefined || status.power_action === "shutdown")
    && (Object.hasOwn(shutdownRefusals, status.code) || shutdownTeardownRefusals.has(status.code));
}
function softwareDisconnected(status: any): boolean {
  return status?.schema_version === 1 && status.busy === false && status.safe_to_unplug === false
    && status.code === "dock_teardown.software_down" && status.software_down === true && status.ok === true;
}
/** Explicit intent selects the existing guarded route; capability metadata is
 * not an input and cannot authorize a write. Shutdown never becomes reconnect. */
export function dockIntentControl(status: any, snapshot: any, intent: DockIntent, now = Date.now()): ReturnType<typeof dockControl> {
  if (intent === "disconnect") return dockControl(status, snapshot, now);
  if (intent === "disconnect_only") {
    if (softwareDisconnected(status)) return { action: null, label: "Software disconnect verified",
      message: "The dock is disconnected in software. Keep the cable connected; this is not permission to unplug." };
    const view = dockControl(status, snapshot, now);
    return view.action === "whole_dock_disconnect" ? view : { action: null, label: "Disconnect unavailable",
      message: view.message };
  }
  if (intent === "sleep") {
    if (sleepObserved(status)) return { action: null, label: "Sleep completed",
      message: "The handheld slept and woke with the dock disconnected in software. Keep the cable connected; this is not permission to unplug." };
    if (snapshot?.schema_version !== 3) return { action: null, label: "Sleep unavailable", message: "Current system status is unavailable. Refresh before continuing." };
    const view = dockControl(status, snapshot, now);
    return {
      action: view.action === "whole_dock_disconnect" ? "whole_dock_sleep" : null,
      label: view.action === "whole_dock_disconnect" ? "Disconnect and sleep" : softwareDisconnected(status) ? "Sleep unavailable" : view.label,
      message: view.action === "whole_dock_disconnect"
        ? "Disconnect the dock in software, then ask the system to sleep after verification."
        : softwareDisconnected(status)
          ? "The dock is already disconnected in software. Sleep continuation is unavailable; do not repeat the operation."
          : (sleepRefusals[status?.code] ? sleepRefusals[status.code] + " Keep the cable connected; do not repeat the operation." : view.message),
    };
  }
  if (intent !== "shutdown") return { action: null, label: "Action unavailable", message: "This action is not supported." };
  if (shutdownRequested(status)) return { action: null, label: "Shutdown requested", message: "Shutdown was requested. Completion is not confirmed. Keep the cable connected." };
  if (snapshot?.schema_version !== 3) return { action: null, label: "Shutdown unavailable", message: "Current system status is unavailable. Refresh before continuing." };
  const view = dockControl(status, snapshot, now);
  return {
    action: view.action === "whole_dock_disconnect" ? "whole_dock_shutdown" : null,
    label: view.action === "whole_dock_disconnect" ? "Disconnect and shut down" : softwareDisconnected(status) ? "Shutdown unavailable" : view.label,
    message: view.action === "whole_dock_disconnect"
      ? "Disconnect the dock in software, then request shutdown after verification."
      : softwareDisconnected(status)
        ? "The dock is already disconnected in software. Shutdown continuation is unavailable; do not repeat the operation."
        : (shutdownRefusals[status?.code] ? shutdownRefusals[status.code] + " Keep the cable connected; do not repeat the operation." : view.message),
  };
}
export function dockControl(status: any, snapshot: any, now = Date.now()): { action: DockAction | null; label: string; message: string } {
  const unavailable = { action: null, label: "Safely disconnect", message: "Disconnect status unavailable. Refresh before continuing." };
  if (status?.schema_version !== 1 || status.safe_to_unplug !== false || typeof status.busy !== "boolean") return unavailable;
  if (status.busy) return { action: null, label: "Working…", message: "Keep the cable connected. Re-Gear is checking the dock." };
  const observed = typeof snapshot?.observed_at === "string" ? Date.parse(snapshot.observed_at) : NaN;
  if (snapshot?.schema_version !== 3 || !Number.isFinite(observed) || observed > now || now - observed >= 10000) return unavailable;
  if (status.code === "dock_teardown.software_down" && status.software_down === true) {
    return softwareDisconnected(status)
      ? { action: null, label: "Software disconnect verified",
        message: "The dock is disconnected in software. Keep the cable connected; this is not permission to unplug." }
      : { action: null, label: "Needs attention",
        message: "The last disconnect could not be verified. Keep the cable connected; do not repeat the operation." };
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
