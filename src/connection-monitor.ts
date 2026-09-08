import { connectionLiveStatus, createLiveStatusStore } from "./connection-live-status";
import type { SnapshotPayload, AutomaticDockStatusPayload } from "./backend";

type Reading = {payload: SnapshotPayload; automatic: AutomaticDockStatusPayload; journal: string};
type Modal = {Close(): void};
type Dependencies = {
  read(): Promise<Reading>;
  show(store: ReturnType<typeof createLiveStatusStore>, switchTv: (() => void) | undefined, closed: () => void): Modal;
  schedule?: (callback: () => void, delay: number) => ReturnType<typeof setTimeout>;
  cancel?: (timer: ReturnType<typeof setTimeout>) => void;
};

// Owned by the plugin, never by the Quick Access content mount. The first
// successful sample establishes a baseline; an already attached GPU is not
// a new physical connection. Missing/stale reads cannot rearm the popup.
export function startConnectionMonitor(deps: Dependencies) {
  const store = createLiveStatusStore();
  const schedule = deps.schedule ?? setTimeout;
  const cancel = deps.cancel ?? clearTimeout;
  let previous: boolean | undefined;
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let modal: Modal | null = null;
  const close = () => { modal?.Close(); modal = null; };
  const open = (switchTv?: () => void) => {
    if (!stopped && !modal) modal = deps.show(store, switchTv, () => { modal = null; });
  };
  const poll = async () => {
    try {
      const {payload, automatic, journal} = await deps.read();
      if (stopped) return;
      const status = connectionLiveStatus(payload, automatic, journal);
      store.set(status);
      const age = Date.now() - Date.parse(payload.snapshot.observed_at);
      if (payload.connection_readiness && Number.isFinite(age) && age >= -5000 && age < 15000) {
        const attached = status.connected;
        const newConnection = previous === false && attached;
        previous = attached;
        if (!attached) close();
        else if (newConnection && payload.snapshot.game_state === "idle"
          && payload.inference.mode !== "docked_egpu") open();
      }
    } catch {
      if (!stopped) store.set({...store.get(), expiresAt: 0, canSwitch: false});
    } finally {
      // One in-flight read, no overlapping polling or new hardware mutation.
      if (!stopped) timer = schedule(() => void poll(), 1000);
    }
  };
  void poll();
  return {store, open, stop() { stopped = true; if (timer !== undefined) cancel(timer); close(); }};
}
