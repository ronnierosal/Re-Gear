/** One offline preparation sync for one explicitly chosen game.
 *
 * The same workflow serves the player's "Sync now" and an opted-in cadence:
 * refresh what the game needs, request the available content once, watch what
 * Steam actually does, then recheck readiness. Manual and scheduled runs differ
 * only in what started them.
 *
 * Deliberate boundaries:
 * - One chosen game, never the library. Nothing here enumerates games.
 * - Disposing detaches observation. It never cancels a native download — a
 *   player who closes the tab keeps their update.
 * - A recheck is a real new check. Neither a schedule tick nor a finished
 *   download ever renews readiness that was not actually re-measured.
 * - Gameplay rules come from the existing check path through `isIdle`; this
 *   adds no new teardown prerequisite.
 * - Completing a download never asserts the game launches offline.
 */

import {
  PreparationUnavailableError,
  isExactAppId,
  startOfflinePreparation,
  type PreparationPorts,
  type PreparationReport,
  type PreparationState,
} from "./offline-preparation-native.ts";
import {
  type OfflineSyncPreferences,
  type SyncPreferences,
} from "./offline-sync-preferences.ts";

export type SyncTrigger = "manual" | "scheduled";

export type SyncPhase =
  | "idle"
  | "checking"
  | "preparing"
  | "rechecking"
  | "done"
  | "failed";

/** Identity is app plus account plus installed build: a rebuilt or re-owned
 * game is a different subject and old evidence must not survive it. */
export type GameIdentity = {
  appId: number;
  account?: string | null;
  buildId?: number | null;
};

export type ReadinessResult = {
  status: string;
  label: string;
  reasons?: readonly string[];
  checkedAt: number;
  expiresAt: number;
};

export type SyncState = {
  phase: SyncPhase;
  trigger: SyncTrigger | null;
  game: GameIdentity | null;
  readiness: ReadinessResult | null;
  preparation: PreparationReport | null;
  /** Our own code, never a Steam string. */
  failure: string | null;
  scheduled: SyncPreferences;
  running: boolean;
};

export type SyncControllerPorts = {
  preparation: PreparationPorts;
  /** The existing evidence path, for one game. Returns null when it cannot say. */
  refreshReadiness(appId: number): Promise<ReadinessResult | null>;
  /** False while a game runs or the running state is unknown — the same rule
   * the passive check path already applies. */
  isIdle(): boolean;
  now(): number;
  setTimer(run: () => void, ms: number): unknown;
  clearTimer(handle: unknown): void;
};

const TERMINAL: PreparationState[] = ["completed", "error", "unconfirmed"];
const MINUTE_MS = 60000;

function sameGame(a: GameIdentity | null, b: GameIdentity | null): boolean {
  return a?.appId === b?.appId
    && (a?.account ?? null) === (b?.account ?? null)
    && (a?.buildId ?? null) === (b?.buildId ?? null);
}

export function createOfflineSyncController(
  ports: SyncControllerPorts,
  preferences: OfflineSyncPreferences,
) {
  let disposed = false;
  let generation = 0;
  let game: GameIdentity | null = null;
  let phase: SyncPhase = "idle";
  let trigger: SyncTrigger | null = null;
  let readiness: ReadinessResult | null = null;
  let preparation: PreparationReport | null = null;
  let failure: string | null = null;
  let running = false;
  let active: { stop(): void } | undefined;
  let timer: unknown;

  const listeners = new Set<(state: SyncState) => void>();
  let lastKey = "";

  const snapshot = (): SyncState => ({
    phase, trigger,
    game: game ? { ...game } : null,
    readiness: readiness ? { ...readiness } : null,
    preparation: preparation ? { ...preparation, content: preparation.content.map((c) => ({ ...c })) } : null,
    failure,
    scheduled: preferences.get(),
    running,
  });

  // Compare the whole state, never a phase name: a content entry completing
  // under an unchanged phase is a real change subscribers need.
  const emit = () => {
    if (disposed) return;
    const next = snapshot();
    const key = JSON.stringify(next);
    if (key === lastKey) return;
    lastKey = key;
    for (const listener of [...listeners]) {
      try { listener(next); } catch { /* one bad subscriber must not stop the rest */ }
    }
  };

  /** Detach observation only. The native download is deliberately left alone. */
  const detach = () => {
    try { active?.stop(); } catch { /* nothing to salvage */ }
    active = undefined;
  };

  const cancelTimer = () => {
    if (timer !== undefined) {
      try { ports.clearTimer(timer); } catch { /* already gone */ }
      timer = undefined;
    }
  };

  const schedule = () => {
    cancelTimer();
    if (disposed) return;
    const prefs = preferences.get();
    // No schedule configured means the passive path stays exactly as it was.
    if (!prefs.enabled || prefs.intervalMinutes === null) return;
    timer = ports.setTimer(() => {
      timer = undefined;
      void start("scheduled");
      schedule();
    }, prefs.intervalMinutes * MINUTE_MS);
  };

  const current = (mine: number) => !disposed && mine === generation;

  const finish = (nextPhase: SyncPhase, code: string | null) => {
    phase = nextPhase;
    failure = code;
    running = false;
    detach();
    emit();
  };

  const stopForGameplay = (by: SyncTrigger) => {
    if (by === "manual") {
      finish("failed", "sync_game_running");
      return;
    }
    phase = "idle";
    trigger = null;
    running = false;
    emit();
  };

  async function start(by: SyncTrigger): Promise<boolean> {
    if (disposed || !game || !isExactAppId(game.appId)) return false;
    // Coalesce: a second press, or a tick while a run is live, joins the run in
    // progress rather than starting a competing one.
    if (running) return false;
    if (!ports.isIdle()) {
      // Same rule the passive path already applies. A scheduled tick simply
      // does not run; nothing is renewed and nothing is torn down.
      if (by === "scheduled") return false;
      finish("failed", "sync_game_running");
      return false;
    }
    generation += 1;
    const mine = generation;
    const target = { ...game };
    running = true;
    trigger = by;
    failure = null;
    preparation = null;
    phase = "checking";
    emit();

    let needs: ReadinessResult | null = null;
    try {
      needs = await ports.refreshReadiness(target.appId);
    } catch {
      if (!current(mine)) return false;
      finish("failed", "sync_readiness_unavailable");
      return false;
    }
    if (!current(mine) || !sameGame(game, target)) return false;
    if (needs) readiness = needs;
    if (!ports.isIdle()) {
      stopForGameplay(by);
      return false;
    }

    phase = "preparing";
    emit();
    // Subscribers run synchronously. Revalidate selection and gameplay after
    // publishing this transition, immediately before the native request.
    if (!current(mine) || !sameGame(game, target)) return false;
    if (!ports.isIdle()) {
      stopForGameplay(by);
      return false;
    }
    try {
      const started = startOfflinePreparation(
        target.appId, "queue", ports.preparation,
        (report) => {
          if (!current(mine) || !sameGame(game, target) || report.appId !== target.appId) return;
          preparation = report;
          emit();
          // A notification can synchronously select another game or dispose.
          // Never let this run finish over the replacement state.
          if (!current(mine) || !sameGame(game, target)) return;
          if (!TERMINAL.includes(report.state)) return;
          if (report.state === "error") { finish("failed", "sync_preparation_failed"); return; }
          void recheck(mine, target);
        },
      );
      // The adapter emits `requested` before returning its stop handle. That
      // callback can synchronously dispose this controller, change selection,
      // or complete the run. Do not retain a handle for a run that moved on.
      if (!current(mine) || !sameGame(game, target) || !running || phase !== "preparing") {
        try { started.stop(); } catch { /* observation is already ending */ }
        return current(mine) && sameGame(game, target);
      }
      active = started;
    } catch (error) {
      if (!current(mine)) return false;
      finish("failed", error instanceof PreparationUnavailableError
        ? "sync_preparation_unavailable" : "sync_preparation_failed");
      return false;
    }
    emit();
    return true;
  }

  /** Re-measure after preparation. This is a real check, not an extension of
   * the evidence we already had. */
  async function recheck(mine: number, target: GameIdentity): Promise<void> {
    if (!current(mine)) return;
    phase = "rechecking";
    detach();
    emit();
    let fresh: ReadinessResult | null = null;
    try {
      fresh = await ports.refreshReadiness(target.appId);
    } catch {
      if (current(mine)) finish("failed", "sync_readiness_unavailable");
      return;
    }
    if (!current(mine) || !sameGame(game, target)) return;
    if (fresh) {
      readiness = fresh;
      finish("done", null);
      return;
    }
    // A download that finished but produced no fresh evidence is not readiness.
    finish("failed", "sync_readiness_unavailable");
  }

  return {
    getState: snapshot,

    subscribe(listener: (state: SyncState) => void): () => void {
      if (typeof listener !== "function" || disposed) return () => {};
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },

    selectGame(next: GameIdentity | null): void {
      if (disposed) return;
      if (next !== null && !isExactAppId(next.appId)) return;
      if (sameGame(game, next)) return;
      generation += 1;
      detach();
      game = next ? { ...next } : null;
      phase = "idle"; trigger = null; readiness = null;
      preparation = null; failure = null; running = false;
      schedule();
      emit();
    },

    syncNow(): Promise<boolean> {
      return Promise.resolve(start("manual"));
    },

    setSchedule(next: unknown): boolean {
      if (disposed) return false;
      if (!preferences.set(next)) return false;
      schedule();
      emit();
      return true;
    },

    /** Stop watching. Any native download keeps going, by design. */
    dispose(): void {
      if (disposed) return;
      disposed = true;
      cancelTimer();
      detach();
      running = false;
      listeners.clear();
    },
  };
}

export type OfflineSyncController = ReturnType<typeof createOfflineSyncController>;
