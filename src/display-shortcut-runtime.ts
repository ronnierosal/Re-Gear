import { startControllerSafeDisconnect } from "./controller-safe-disconnect";

type Target = "tv" | "ally";
type ListenerDeps = Parameters<typeof startControllerSafeDisconnect>[0];
export function createDisplayShortcutRuntime(deps: {
  input: ListenerDeps["input"];
  readContext: ListenerDeps["readContext"];
  show(target: Target, confirm: () => void, closed: () => void): { Close(): void };
  approve(target: Target): Promise<{ approval_token: string; blockers: string[] }>;
  execute(target: Target, token: string): Promise<{ accepted: boolean; code: string; acknowledgement_required?: boolean; acknowledgement_id?: string }>;
  report(message: string): void;
}) {
  const state = {
    modal: { current: null as { Close(): void } | null },
    portableBusy: { current: false }, tvBusy: { current: false },
  };
  let stopped = false;
  let acknowledgement = "";
  const acknowledgementListeners = new Set<(id: string) => void>();
  const busy = () => stopped || state.portableBusy.current || state.tvBusy.current || state.modal.current !== null;
  const execute = async (target: Target) => {
    if (busy()) return;
    const lock = target === "tv" ? state.tvBusy : state.portableBusy;
    lock.current = true;
    try {
      const approval = await deps.approve(target);
      if (stopped) return;
      if (!approval.approval_token || approval.blockers.length) {
        deps.report("Display switch blocked. Open Re-Gear to inspect readiness.");
        return;
      }
      const result = await deps.execute(target, approval.approval_token);
      if (!stopped) {
        acknowledgement = result.acknowledgement_required ? result.acknowledgement_id ?? "" : "";
        for (const notify of acknowledgementListeners) notify(acknowledgement);
      }
      if (!stopped) deps.report(result.accepted
        ? "Display request accepted. Keep the eGPU connected and verify the display."
        : "Display switch did not complete. Open Re-Gear for details.");
    } catch {
      if (!stopped) deps.report("Display switch could not be verified. Keep the eGPU connected.");
    } finally { lock.current = false; }
  };
  const request = (target: Target) => {
      if (busy()) return;
      let confirmed = false;
      state.modal.current = deps.show(target, () => {
        if (confirmed) return;
        confirmed = true;
        state.modal.current = null;
        void execute(target);
      }, () => { state.modal.current = null; });
    };
  const listener = startControllerSafeDisconnect({
    input: deps.input, readContext: deps.readContext, isBusy: busy,
    confirm: request,
  });
  return { ...state, request, available: listener.available,
    subscribeAcknowledgement(notify: (id: string) => void) {
      acknowledgementListeners.add(notify);
      notify(acknowledgement);
      return () => { acknowledgementListeners.delete(notify); };
    },
    clearAcknowledgement() { acknowledgement = ""; },
    stop() {
    stopped = true;
    listener.stop();
    acknowledgementListeners.clear();
    state.modal.current?.Close();
    state.modal.current = null;
  } };
}
