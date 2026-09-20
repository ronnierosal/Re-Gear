/** Unmounted power routing. Call only from separately verified fixed-action
 * Steam entry points; OnSuspendRequest's suppression flag is NOT an intent.
 * The backend owns teardown, original power intent, ordinary-power fallback,
 * and sleep observation. This module neither touches Steam nor replays requests.
 */
export type PowerAction = "whole_dock_shutdown" | "whole_dock_sleep_connected";
export type PowerIntent = "sleep" | "shutdown";
export type PowerPhase = "idle" | "choosing" | "dispatching" | "pending" | "requested"
  | "sleep_observed" | "refused" | "uncertain" | "disposed";
export type PowerView = Readonly<{
  phase: PowerPhase; intent: PowerIntent | null; action: PowerAction | null;
  requestId: string | null; code: string;
}>;
export interface PowerRequestPort {
  execute(action: PowerAction, attachmentToken: string, requestId: string): Promise<unknown>;
  readStatus(): Promise<unknown>;
}
type Ticket = {
  intent: PowerIntent; attachment: string; id: string; started: boolean;
  action: PowerAction | null; requested: boolean; executeSettled: boolean;
};

// These are the exact codes emitted by the power route, not a namespace grant.
// A false submission flag also accompanies unknown outcomes: only a known
// pre-submission refusal can release the active ticket for another user choice.
const refusalCodes = new Set([
  "dock_power.invalid_intent", "dock_power.preflight_changed",
  "dock_power.intent_not_recorded", "dock_power.disconnect_unverified",
  "dock_teardown.usb_peripherals_or_unknown", "dock_teardown.begin_preflight_refused",
  "dock_teardown.sleep_inhibition_required", "dock_teardown.approval_superseded",
  "dock_teardown.session_unknown", "dock_teardown.gpu_release_unverified",
  "dock_teardown.portable_return_refused", "dock_teardown.portable_return_unverified",
  "dock_teardown.portable_acknowledgement_unverified",
  "dock_mutation.inhibited", "dock_mutation.unavailable_or_busy",
]);
const otherCodes = new Set([
  "dock_power.request_pending", "dock_teardown.trial_running",
  "dock_power.request_accepted_unverified", "dock_power.request_unverified",
  "dock_power.unresolved", "dock_power.already_consumed", "dock_power.busy",
  "dock_teardown.trial_unresolved",
]);
const sleepRefusals = new Set([
  "dock_power.sleep_unverified", "dock_power.sleep_observer_unavailable",
  "dock_power.sleep_handoff_unavailable",
]);
const sleepOutcomes = new Set([
  "dock_power.sleep_requested_unverified", "dock_power.sleep_cycle_observed",
  "dock_power.sleep_cycle_failed", "dock_power.sleep_cycle_unresolved",
  "dock_power.sleep_protection_unverified",
]);
const shutdownRefusals = new Set([
  "safe_disconnect.root_required", "safe_disconnect.poweroff_failed",
]);
const shutdownOutcomes = new Set([
  "safe_disconnect.poweroff_request_accepted_unverified",
  "safe_disconnect.poweroff_timeout", "safe_disconnect.poweroff_unavailable",
]);

export function createPowerRequestCoordinator(port: PowerRequestPort, options: {
  requestId?: () => string; onChange?: () => void;
} = {}) {
  let active: Ticket | null = null;
  let disposed = false;
  let observationEpoch = 0;
  const usedIds = new Set<string>();
  let view: PowerView = Object.freeze({ phase: "idle", intent: null, action: null,
    requestId: null, code: "power.idle" });
  function publish(phase: PowerPhase, ticket: Ticket | null, code: string) {
    view = Object.freeze({ phase, intent: ticket?.intent ?? null, action: ticket?.action ?? null,
      requestId: ticket?.id ?? null, code });
    // A detached/throwing presentation subscriber must not alter dispatch.
    try { options.onChange?.(); } catch { /* Presentation is not operation ownership. */ }
  }
  function current(ticket: Ticket) { return !disposed && active === ticket; }
  function begin(intent: PowerIntent, attachment: string): Ticket | null {
    if (disposed || active || typeof attachment !== "string"
        || (attachment !== "" && !/^[a-f0-9]{64}:[a-f0-9]{64}$/.test(attachment))) return null;
    let id: string;
    try { id = (options.requestId ?? (() => crypto.randomUUID().replaceAll("-", "")))(); }
    catch { return null; }
    if (typeof id !== "string" || !/^[a-f0-9]{32}$/.test(id) || usedIds.has(id)) return null;
    usedIds.add(id);
    const ticket: Ticket = { intent, attachment, id, started: false, action: null,
      requested: false, executeSettled: false };
    active = ticket;
    observationEpoch++;
    publish("choosing", ticket, "power.choice_required");
    return ticket;
  }
  function cancel(ticket: Ticket) {
    if (!current(ticket) || ticket.started) return;
    active = null;
    observationEpoch++;
    publish("idle", null, "power.cancelled");
  }
  function accept(ticket: Ticket, payload: unknown, direct: boolean) {
    if (!current(ticket)) return;
    const p = payload && typeof payload === "object" ? payload as Record<string, unknown> : null;
    if (!p || p.schema_version !== 1 || p.request_id !== ticket.id) {
      // A global or previous power status cannot complete this request.
      if (direct) publish("uncertain", ticket, "power.reply_unverified");
      return;
    }
    if (p.route_action !== ticket.action || p.power_action !== ticket.intent) {
      publish("uncertain", ticket, "power.reply_unverified"); return;
    }
    // Once submission is observed, an older refusal or a transport error must
    // never reopen dispatch. This fact survives changes in presentation phase.
    if (p.power_requested === true) ticket.requested = true;
    const refusals = ticket.intent === "sleep" ? sleepRefusals : shutdownRefusals;
    const outcomes = ticket.intent === "sleep" ? sleepOutcomes : shutdownOutcomes;
    if (typeof p.code !== "string" || !(refusalCodes.has(p.code) || otherCodes.has(p.code)
        || refusals.has(p.code) || outcomes.has(p.code))
        || typeof p.busy !== "boolean") {
      publish("uncertain", ticket, "power.reply_unverified"); return;
    }
    if (p.busy) {
      // Do not downgrade accepted submission to an older pending read.
      if (view.phase !== "requested") publish("pending", ticket, p.code);
      return;
    }
    if (p.power_requested === true) {
      if (ticket.intent === "sleep" && p.power_action === "sleep" && p.ok === true
          && p.sleep_cycle_observed === true && p.code === "dock_power.sleep_cycle_observed") {
        active = null;
        observationEpoch++;
        publish("sleep_observed", ticket, p.code);
      } else {
        publish("requested", ticket, p.code);
      }
    } else if (p.power_requested === false && p.ok === false) {
      if (ticket.requested) {
        publish("uncertain", ticket, "power.outcome_conflict"); return;
      }
      if (!refusalCodes.has(p.code) && !refusals.has(p.code)) {
        publish("uncertain", ticket, p.code); return;
      }
      if (!direct && !ticket.executeSettled) {
        publish("pending", ticket, "power.awaiting_direct_reply"); return;
      }
      active = null;
      observationEpoch++;
      publish("refused", ticket, p.code);
    } else {
      publish("uncertain", ticket, "power.reply_unverified");
    }
  }
  async function submit(ticket: Ticket, action: PowerAction) {
    if (!current(ticket) || ticket.started) return;
    if ((ticket.intent === "shutdown") !== (action === "whole_dock_shutdown")) return;
    ticket.started = true;
    ticket.action = action;
    publish("dispatching", ticket, "power.dispatching");
    // onChange can dispose the owner before dispatch; do not start new work.
    if (!current(ticket)) return;
    try {
      const result = await port.execute(action, ticket.attachment, ticket.id);
      if (!current(ticket)) return;
      ticket.executeSettled = true;
      observationEpoch++; // Invalidate status reads started before the direct reply.
      accept(ticket, result, true);
    } catch {
      if (current(ticket)) {
        ticket.executeSettled = true;
        observationEpoch++;
        publish("uncertain", ticket, "power.reply_interrupted");
      }
    }
  }
  return {
    read: () => view,
    captureSleep(attachment = "") {
      const ticket = begin("sleep", attachment);
      return ticket ? Object.freeze({
        keepConnectedAndSleep: () => submit(ticket, "whole_dock_sleep_connected"),
        cancel: () => cancel(ticket),
      }) : null;
    },
    captureShutdown(attachment = "") {
      const ticket = begin("shutdown", attachment);
      return ticket ? Object.freeze({ confirm: () => submit(ticket, "whole_dock_shutdown"),
        cancel: () => cancel(ticket) }) : null;
    },
    async refresh() {
      const ticket = active;
      if (disposed || !ticket?.started) return;
      const epoch = ++observationEpoch;
      try {
        const result = await port.readStatus();
        if (current(ticket) && epoch === observationEpoch) accept(ticket, result, false);
      } catch { /* Keep existing uncertainty; never resubmit to obtain a reply. */ }
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      active = null;
      observationEpoch++;
      publish("disposed", null, "power.owner_disposed");
    },
  };
}
