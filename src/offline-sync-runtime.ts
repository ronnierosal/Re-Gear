/** Headless runtime composition for the Offline Game Mode tab.
 *
 * Joins the merged seams without adding policy of its own:
 *   tab model (UI-facing snapshot and actions)
 *     ↕ this runtime
 *   sync controller (one-game workflow, schedule) ← preferences, native adapter
 *
 * The UI reads one value-stable snapshot and calls `selectGame`, `syncNow` and
 * `setSyncSchedule`. Everything else is the controller observing Steam and the
 * evidence path, and this runtime forwarding what was actually observed.
 *
 * Deliberate boundaries:
 * - Reads never act: `getSnapshot` and `subscribe` dispatch nothing.
 * - A command return is never an outcome; only controller observations move
 *   preparation and readiness.
 * - One chosen game. Nothing here enumerates the library.
 * - Schedules stay default-off and only Re-Gear's own preference is written.
 * - Disposal detaches observation; it never cancels a Steam download.
 * - Completing a download never asserts the game launches offline.
 */

import {
  createOfflineGameModeModel,
  type ConfidenceStatus,
  type OfflineGameModeSnapshot,
  type PreparationState,
  type SelectedGame,
  type SyncSchedule,
} from "./offline-game-mode-model.ts";
import {
  createOfflineSyncController,
  type GameIdentity,
  type SyncControllerPorts,
  type SyncState,
} from "./offline-sync-controller.ts";
import {
  createSyncPreferences,
  type SyncPreferencesStore,
} from "./offline-sync-preferences.ts";

export type OfflineSyncRuntimePorts = SyncControllerPorts & {
  /** Re-Gear's own schedule storage. Never Steam or account settings. */
  preferencesStore: SyncPreferencesStore;
};

export type OfflineSyncRuntimeInitial = {
  available: boolean;
  unavailableReason?: string | null;
  game?: SelectedGame;
};

const CONFIDENCE: ConfidenceStatus[] = [
  "needs_preparation", "likely_offline_ready", "tested_offline", "unverified",
];
const PREPARATION: PreparationState[] = [
  "requested", "queued", "active", "completed", "error", "unconfirmed",
];
const TERMINAL: PreparationState[] = ["completed", "error", "unconfirmed"];

function identity(game: SelectedGame): GameIdentity | null {
  return game ? { appId: game.appId, account: game.account ?? null, buildId: game.buildId ?? null } : null;
}

function sameIdentity(a: GameIdentity | null, b: GameIdentity | null): boolean {
  return a?.appId === b?.appId
    && (a?.account ?? null) === (b?.account ?? null)
    && (a?.buildId ?? null) === (b?.buildId ?? null);
}

/** An unrecognised status is not evidence of anything; present it as unverified. */
function confidence(status: unknown): ConfidenceStatus {
  return CONFIDENCE.includes(status as ConfidenceStatus) ? (status as ConfidenceStatus) : "unverified";
}

export function createOfflineSyncRuntime(ports: OfflineSyncRuntimePorts) {
  const preferences = createSyncPreferences(ports.preferencesStore);
  const controller = createOfflineSyncController(ports, preferences);
  let disposed = false;
  /** The press (model generation + attempt) that controller observations land on. */
  let pending: { generation: number; attempt: number } | null = null;
  let lastReadinessKey = "";
  let lastPreparationKey = "";

  const model = createOfflineGameModeModel({
    startSync(_appId, generation, attempt) {
      pending = { generation, attempt };
      lastPreparationKey = "";
      // A press during a run already in progress (for example a scheduled one)
      // joins it instead of starting a competing run.
      if (controller.getState().running) { forward(controller.getState()); return; }
      void controller.syncNow().then((started) => {
        // A run that never started, or ended without a terminal observation,
        // must not leave the press in flight.
        if (!disposed && !started && !controller.getState().running) settle(controller.getState());
      }, () => {
        if (!disposed) settle(controller.getState());
      });
    },
    persistSchedule(schedule: SyncSchedule) {
      return controller.setSchedule(schedule);
    },
    now: () => ports.now(),
  });

  /** The controller's subject must be the model's subject, or nothing is forwarded. */
  const current = (state: SyncState) => {
    const snapshot = model.getSnapshot();
    return !disposed && sameIdentity(state.game, identity(snapshot.game));
  };

  const forwardReadiness = (state: SyncState) => {
    const readiness = state.readiness;
    if (!readiness) return;
    const key = JSON.stringify(readiness);
    if (key === lastReadinessKey) return;
    lastReadinessKey = key;
    const snapshot = model.getSnapshot();
    if (!snapshot.game) return;
    model.applyReadiness({
      generation: snapshot.generation,
      appId: snapshot.game.appId,
      status: confidence(readiness.status),
      label: readiness.label,
      reasons: readiness.reasons ?? [],
      checkedAt: readiness.checkedAt,
      expiresAt: readiness.expiresAt,
    });
  };

  const applyPreparation = (state: PreparationState, report: SyncState["preparation"]) => {
    if (!pending) return;
    const key = JSON.stringify([pending, state, report]);
    if (key === lastPreparationKey) return;
    lastPreparationKey = key;
    const snapshot = model.getSnapshot();
    if (!snapshot.game) return;
    model.applyPreparation({
      generation: pending.generation,
      appId: snapshot.game.appId,
      attempt: pending.attempt,
      state,
      content: report?.content ?? [],
      errorCode: report?.errorCode ?? null,
    });
    if (TERMINAL.includes(state)) pending = null;
  };

  /** End the press honestly once the controller is no longer running it. */
  const settle = (state: SyncState) => {
    if (!pending || state.running) return;
    const reported = state.preparation?.state;
    if (state.failure) { applyPreparation("error", state.preparation); return; }
    if (reported && TERMINAL.includes(reported as PreparationState)) {
      applyPreparation(reported as PreparationState, state.preparation);
      return;
    }
    // Stopped without an outcome (for example a scheduled run deferred by
    // gameplay): say so rather than leave the press in flight.
    applyPreparation("unconfirmed", state.preparation);
  };

  const forward = (state: SyncState) => {
    if (!current(state)) return;
    forwardReadiness(state);
    if (!pending) {
      // A scheduled run with no press: show its progress on the latest attempt
      // without marking anything in flight.
      if (!state.running || !state.preparation) return;
      const snapshot = model.getSnapshot();
      pending = { generation: snapshot.generation, attempt: snapshot.attempt };
    }
    if (state.running) {
      const reported = state.preparation?.state;
      const mapped = reported && PREPARATION.includes(reported as PreparationState)
        ? (reported as PreparationState) : "requested";
      // A terminal download state while readiness is still being re-measured
      // stays visible but does not end the press yet.
      applyPreparation(TERMINAL.includes(mapped) ? "active" : mapped, state.preparation);
      return;
    }
    settle(state);
  };

  const unsubscribe = controller.subscribe(forward);

  const selectBoth = (game: SelectedGame) => {
    pending = null;
    lastReadinessKey = "";
    lastPreparationKey = "";
    controller.selectGame(identity(game));
  };

  return {
    getSnapshot: (): OfflineGameModeSnapshot => model.getSnapshot(),
    subscribe: (listener: (snapshot: OfflineGameModeSnapshot) => void) => model.subscribe(listener),

    /** Resolve availability and the initial selection. The schedule always
     * comes from Re-Gear's stored preference, which reads back disabled when
     * missing or malformed. */
    applyInitialState(initial: OfflineSyncRuntimeInitial | null): void {
      if (disposed) return;
      model.applyInitialState({
        available: initial?.available ?? false,
        unavailableReason: initial?.unavailableReason ?? null,
        game: initial?.game ?? null,
        schedule: preferences.get(),
      });
      selectBoth(model.getSnapshot().game);
    },

    /** Exact identity: app, account, installed build and display name. */
    selectGame(next: SelectedGame): void {
      if (disposed) return;
      const before = model.getSnapshot().generation;
      model.selectGame(next);
      if (model.getSnapshot().generation !== before) selectBoth(model.getSnapshot().game);
    },

    syncNow: (): boolean => model.syncNow(),
    setSyncSchedule: (next: SyncSchedule): boolean => model.setSyncSchedule(next),
    refresh: (): boolean => model.refresh(),

    setAvailability(next: { available: boolean; unavailableReason?: string | null }): void {
      if (disposed) return;
      model.setAvailability(next);
      if (!next?.available) pending = null;
    },

    /** Detach observation. Any native download keeps going, by design. */
    dispose(): void {
      if (disposed) return;
      disposed = true;
      pending = null;
      try { unsubscribe(); } catch { /* already detached */ }
      controller.dispose();
      model.dispose();
    },
  };
}

export type OfflineSyncRuntime = ReturnType<typeof createOfflineSyncRuntime>;
