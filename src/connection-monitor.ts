import { connectionLiveStatus, createLiveStatusStore } from "./connection-live-status";
import type { SnapshotPayload, AutomaticDockStatusPayload } from "./backend";

type Reading = {payload: SnapshotPayload; automatic: AutomaticDockStatusPayload; journal: string};
type Modal = {Close(): void};
type PresentationReceipt = {active(): boolean; begin(): void; clear(): void};
type Dependencies = {
  read(): Promise<Reading>;
  show(store: ReturnType<typeof createLiveStatusStore>, switchTv: (() => void) | undefined, closed: () => void): Modal;
  schedule?: (callback: () => void, delay: number) => ReturnType<typeof setTimeout>;
  cancel?: (timer: ReturnType<typeof setTimeout>) => void;
  presentation?: PresentationReceipt;
};

const PRESENTATION_KEY = "regear.connection-popup.v1";
const PRESENTATION_TTL_MS = 30_000;
export function createConnectionPresentationReceipt(
  storage: Pick<Storage, "getItem" | "setItem" | "removeItem"> | undefined,
  now: () => number = Date.now,
): PresentationReceipt {
  return {
    active() {
      try {
        const raw = storage?.getItem(PRESENTATION_KEY) ?? "";
        const match = /^v1:(\d+)$/.exec(raw);
        const expiresAt = match ? Number(match[1]) : 0;
        if (!Number.isSafeInteger(expiresAt) || expiresAt <= now()) {
          if (raw) storage?.removeItem(PRESENTATION_KEY);
          return false;
        }
        return true;
      } catch { return false; }
    },
    begin() {
      try { storage?.setItem(PRESENTATION_KEY, `v1:${now() + PRESENTATION_TTL_MS}`); }
      catch { /* Remount presentation is optional; connection remains active. */ }
    },
    clear() {
      try { storage?.removeItem(PRESENTATION_KEY); }
      catch { /* Remount presentation is optional; connection remains active. */ }
    },
  };
}

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
  const closeSurface = () => { modal?.Close(); modal = null; };
  const retire = () => { deps.presentation?.clear(); closeSurface(); };
  const open = (switchTv?: () => void) => {
    if (!stopped && !modal) modal = deps.show(store, switchTv, () => {
      modal = null;
      deps.presentation?.clear();
    });
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
        const restorePresentation = previous === undefined && attached
          && deps.presentation?.active() === true;
        previous = attached;
        if (!attached) retire();
        else if (restorePresentation && payload.snapshot.game_state === "idle") open();
        else if (newConnection && payload.snapshot.game_state === "idle"
          && payload.inference.mode !== "docked_egpu") {
          deps.presentation?.begin();
          open();
        }
      }
    } catch {
      if (!stopped) store.set({...store.get(), expiresAt: 0, canSwitch: false});
    } finally {
      // One in-flight read, no overlapping polling or new hardware mutation.
      if (!stopped) timer = schedule(() => void poll(), 1000);
    }
  };
  void poll();
  return {store, open, stop() { stopped = true; if (timer !== undefined) cancel(timer); closeSurface(); }};
}
