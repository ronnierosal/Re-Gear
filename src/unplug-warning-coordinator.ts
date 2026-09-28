export type UnplugWarningPhase = "idle" | "prompt" | "alarm" | "cleared";

export type UnplugWarningObservation = {
  requestId?: string;
  deauthorized?: boolean;
  physicalAbsenceVerified?: boolean;
};

export type UnplugWarningState = {
  phase: UnplugWarningPhase;
  requestId: string | null;
};

export type UnplugWarningPorts = {
  schedule?: (run: () => void, delayMs: number) => ReturnType<typeof setTimeout>;
  cancel?: (timer: ReturnType<typeof setTimeout>) => void;
  repeat?: (run: () => void, delayMs: number) => ReturnType<typeof setInterval>;
  cancelRepeat?: (timer: ReturnType<typeof setInterval>) => void;
  playWarning: () => void;
};

const REQUEST_ID = /^[0-9a-f]{32}$/;
const ESCALATE_AFTER_MS = 5000;
const REPEAT_EVERY_MS = 2000;

export function createUnplugWarningCoordinator(ports: UnplugWarningPorts) {
  const schedule = ports.schedule ?? setTimeout;
  const cancel = ports.cancel ?? clearTimeout;
  const repeat = ports.repeat ?? setInterval;
  const cancelRepeat = ports.cancelRepeat ?? clearInterval;
  let state: UnplugWarningState = { phase: "idle", requestId: null };
  let escalation: ReturnType<typeof setTimeout> | undefined;
  let alarm: ReturnType<typeof setInterval> | undefined;
  const listeners = new Set<(next: UnplugWarningState) => void>();

  const publish = (next: UnplugWarningState) => {
    if (next.phase === state.phase && next.requestId === state.requestId) return;
    state = next;
    for (const listener of [...listeners]) {
      try { listener(state); } catch { /* one consumer cannot starve another */ }
    }
  };

  const clearTimers = () => {
    if (escalation !== undefined) cancel(escalation);
    if (alarm !== undefined) cancelRepeat(alarm);
    escalation = undefined;
    alarm = undefined;
  };

  const begin = (requestId: string) => {
    clearTimers();
    publish({ phase: "prompt", requestId });
    escalation = schedule(() => {
      escalation = undefined;
      if (state.requestId !== requestId || state.phase !== "prompt") return;
      publish({ phase: "alarm", requestId });
      ports.playWarning();
      alarm = repeat(() => {
        if (state.requestId === requestId && state.phase === "alarm") {
          ports.playWarning();
        }
      }, REPEAT_EVERY_MS);
    }, ESCALATE_AFTER_MS);
  };

  return {
    observe(observation: UnplugWarningObservation) {
      const requestId = observation.requestId;
      if (typeof requestId !== "string" || !REQUEST_ID.test(requestId)) return;
      if (observation.physicalAbsenceVerified === true) {
        if (requestId !== state.requestId) return;
        clearTimers();
        publish({ phase: "cleared", requestId });
        return;
      }
      if (observation.deauthorized !== true) return;
      if (requestId === state.requestId
          && (state.phase === "prompt" || state.phase === "alarm")) return;
      begin(requestId);
    },
    read: () => state,
    subscribe(listener: (next: UnplugWarningState) => void) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    stop() {
      clearTimers();
      publish({ phase: "idle", requestId: null });
      listeners.clear();
    },
  };
}
