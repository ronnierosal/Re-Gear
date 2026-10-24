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
  isExactAppId,
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

  /** The installed build moved under the selection (for example the update
   * this sync requested just completed), so the selection is no longer the
   * subject that evidence describes. */
  const buildMoved = (state: SyncState, selected: GameIdentity | null) => {
    const reported = state.preparation?.buildId;
    return typeof reported === "number" && typeof selected?.buildId === "number" && reported !== selected.buildId;
  };

  let invalidatedKey = "";
  const forwardReadiness = (state: SyncState) => {
    const snapshot = model.getSnapshot();
    if (!snapshot.game) return;
    const selected = identity(snapshot.game);
    if (buildMoved(state, selected)) {
      // Evidence measured now describes a different build than the one
      // selected. Never present it under the old identity, and do not leave
      // earlier evidence for the old build looking current either.
      const key = `${snapshot.generation}:${state.preparation?.buildId}`;
      if (key === invalidatedKey) return;
      invalidatedKey = key;
      // No timestamps: this always replaces older evidence, and with no usable
      // expiry the model presents it as expired.
      model.applyReadiness({
        generation: snapshot.generation,
        appId: snapshot.game.appId,
        status: "unverified",
        label: "Unverified",
        reasons: ["The installed game version changed. Check the current version again."],
        checkedAt: null as unknown as number,
        expiresAt: null as unknown as number,
      });
      return;
    }
    const readiness = state.readiness;
    if (!readiness) return;
    // Evidence that names its subject must name this one.
    if (readiness.account !== undefined && (readiness.account ?? null) !== (selected?.account ?? null)) return;
    if (readiness.buildId !== undefined && (readiness.buildId ?? null) !== (selected?.buildId ?? null)) return;
    const key = JSON.stringify(readiness);
    if (key === lastReadinessKey) return;
    lastReadinessKey = key;
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

  /** Point the controller at the subject the model is about to publish. This
   * runs before the model notifies, so a subscriber that reacts synchronously
   * (for example by pressing Sync now) always finds both aligned. Only an
   * available tab gives the controller a subject: without one it can neither
   * schedule nor dispatch. An already-started Steam download is untouched. */
  const alignController = (game: SelectedGame, available: boolean) => {
    const target = available ? identity(game) : null;
    if (sameIdentity(controller.getState().game, target)) return;
    pending = null;
    lastReadinessKey = "";
    lastPreparationKey = "";
    controller.selectGame(target);
  };

  return {
    getSnapshot: (): OfflineGameModeSnapshot => model.getSnapshot(),
    subscribe: (listener: (snapshot: OfflineGameModeSnapshot) => void) => model.subscribe(listener),

    /** Resolve availability and the initial selection. The schedule always
     * comes from Re-Gear's stored preference, which reads back disabled when
     * missing or malformed. */
    applyInitialState(initial: OfflineSyncRuntimeInitial | null): void {
      if (disposed) return;
      const available = initial?.available ?? false;
      const game = initial?.game && isExactAppId(initial.game.appId) ? initial.game : null;
      pending = null;
      alignController(game, available);
      model.applyInitialState({
        available,
        unavailableReason: initial?.unavailableReason ?? null,
        game,
        schedule: preferences.get(),
      });
    },

    /** Exact identity: app, account, installed build and display name. A
     * rename of the same subject updates the name and keeps its evidence. */
    selectGame(next: SelectedGame): void {
      if (disposed) return;
      const snapshot = model.getSnapshot();
      if (!snapshot.available) return;
      if (next !== null && !isExactAppId(next?.appId)) return;
      alignController(next, true);
      model.selectGame(next);
    },

    syncNow: (): boolean => model.syncNow(),
    setSyncSchedule: (next: SyncSchedule): boolean => model.setSyncSchedule(next),
    refresh: (): boolean => model.refresh(),

    /** Losing availability also stops future scheduling and dispatch; it
     * never cancels a Steam download that already started. */
    setAvailability(next: { available: boolean; unavailableReason?: string | null }): void {
      if (disposed) return;
      const available = !!next?.available;
      if (!available) pending = null;
      alignController(model.getSnapshot().game, available);
      model.setAvailability(next);
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
