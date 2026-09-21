/** Headless wiring model for the Offline Game Mode tab.
 *
 * This is the consumer seam only: the UI reads immutable snapshots and calls
 * three actions, and whatever owns real scheduling, persistence and native
 * composition (offline-sync-workflow) pushes observations in. The model itself
 * holds no scheduler, no persistence, no native binding and no view.
 *
 * Two rules this file exists to enforce:
 * reads never act — `getSnapshot` and `subscribe` cannot dispatch a command, so
 * rendering the tab can never queue a download; and a command's return is never
 * an outcome — only an observation pushed back in moves preparation state.
 *
 * Nothing here proves a game launches offline, and a completed download least of
 * all. The existing automatic focused-tile checks are untouched, and the offline
 * centre state stays separate from the Auto TDP performance gear.
 */

export type ConfidenceStatus =
  | "needs_preparation"
  | "likely_offline_ready"
  | "tested_offline"
  | "unverified";

export type PreparationState =
  | "idle"
  | "requested"
  | "queued"
  | "active"
  | "completed"
  | "error"
  | "unconfirmed";

export type ContentType = "content" | "shader" | "workshop";

export type ContentProgress = {
  type: ContentType;
  /** null means Steam did not report this content type in a shape we accept. */
  hasUpdate: boolean | null;
  completed: boolean | null;
  bytesDownloaded: number | null;
  bytesTotal: number | null;
};

export type SyncSchedule = { enabled: boolean; intervalMinutes: number | null };

/** Identity is the app **plus** the account and installed build. A rebuilt or
 * re-owned game is a different subject even under the same app id, so evidence
 * gathered against the old one must not survive. */
export type SelectedGame = {
  appId: number;
  name: string;
  account?: string | null;
  buildId?: number | null;
} | null;

export type OfflineGameModeSnapshot = {
  /** True until the injected initial state resolves. Never guessed. */
  loading: boolean;
  available: boolean;
  unavailableReason: string | null;
  generation: number;
  /** Increments on every syncNow; resets with a new selection. */
  attempt: number;
  game: SelectedGame;
  readiness: {
    status: ConfidenceStatus | null;
    label: string | null;
    reasons: readonly string[];
    checkedAt: number | null;
    expiresAt: number | null;
    expired: boolean;
  };
  schedule: SyncSchedule;
  preparation: {
    state: PreparationState;
    content: readonly ContentProgress[];
    errorCode: number | null;
    inFlight: boolean;
  };
  capabilities: { canSelectGame: boolean; canSyncNow: boolean; canSetSchedule: boolean };
};

/** Outbound seam. Each is called at most once per player action, never from a read. */
export type OfflineGameModePorts = {
  /** Start one preparation sync for this exact game, generation and attempt.
   * `attempt` exists so a late reply from an earlier press of the same button,
   * on the same selection, can be told apart from the current one. */
  startSync(appId: number, generation: number, attempt: number): void;
  /** Record a schedule the player changed. Never called to enable one by itself. */
  persistSchedule(schedule: SyncSchedule): void;
  now(): number;
};

export type ReadinessObservation = {
  generation: number;
  appId: number;
  status: ConfidenceStatus;
  label: string;
  reasons: readonly string[];
  checkedAt: number;
  /** Absolute time this evidence stops being presentable. */
  expiresAt: number;
};

export type PreparationObservation = {
  generation: number;
  appId: number;
  /** Which `syncNow` press this belongs to. Required, so an older attempt's late
   * reply cannot land on a newer one. */
  attempt: number;
  state: PreparationState;
  content?: readonly Partial<ContentProgress>[];
  errorCode?: number | null;
};

const CONTENT_TYPES: ContentType[] = ["content", "shader", "workshop"];
const TERMINAL: PreparationState[] = ["completed", "error", "unconfirmed"];

function integer(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) ? value : null;
}

function bool(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

export function isExactAppId(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) > 0 && (value as number) < 2 ** 32;
}

function emptyContent(): ContentProgress[] {
  return CONTENT_TYPES.map((type) => ({
    type, hasUpdate: null, completed: null, bytesDownloaded: null, bytesTotal: null,
  }));
}

/** Accept only a shape we recognise; anything else stays unknown rather than
 * becoming a confident "no update". */
function normalizeContent(raw: readonly Partial<ContentProgress>[] | undefined): ContentProgress[] {
  const base = emptyContent();
  if (!Array.isArray(raw)) return base;
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const slot = base.find((item) => item.type === entry.type);
    if (!slot) continue;
    slot.hasUpdate = bool(entry.hasUpdate);
    slot.completed = bool(entry.completed);
    slot.bytesDownloaded = integer(entry.bytesDownloaded);
    slot.bytesTotal = integer(entry.bytesTotal);
  }
  return base;
}

function freeze(snapshot: OfflineGameModeSnapshot): OfflineGameModeSnapshot {
  Object.freeze(snapshot.readiness.reasons);
  Object.freeze(snapshot.readiness);
  Object.freeze(snapshot.schedule);
  snapshot.preparation.content.forEach((entry) => Object.freeze(entry));
  Object.freeze(snapshot.preparation.content);
  Object.freeze(snapshot.preparation);
  Object.freeze(snapshot.capabilities);
  if (snapshot.game) Object.freeze(snapshot.game);
  return Object.freeze(snapshot);
}

export type InitialState = {
  available?: boolean;
  unavailableReason?: string | null;
  game?: SelectedGame;
  schedule?: SyncSchedule;
};

export function createOfflineGameModeModel(
  ports: OfflineGameModePorts,
  options: { initial?: InitialState } = {},
) {
  let disposed = false;
  let generation = 0;
  let attempt = 0;
  let loading = options.initial === undefined;
  let available = options.initial?.available ?? false;
  let unavailableReason = options.initial?.unavailableReason ?? null;
  let game: SelectedGame = options.initial?.game ?? null;
  let schedule: SyncSchedule = options.initial?.schedule ?? { enabled: false, intervalMinutes: null };
  let readiness = { status: null as ConfidenceStatus | null, label: null as string | null,
    reasons: [] as readonly string[], checkedAt: null as number | null, expiresAt: null as number | null };
  let preparation = { state: "idle" as PreparationState, content: emptyContent(), errorCode: null as number | null };
  let inFlight = false;

  const listeners = new Set<(snapshot: OfflineGameModeSnapshot) => void>();
  let cached: OfflineGameModeSnapshot | null = null;
  let cachedKey = "";
  let notifiedKey = "";

  const build = (): OfflineGameModeSnapshot => {
    const at = ports.now();
    const expired = readiness.expiresAt !== null && Number.isFinite(at) && at >= readiness.expiresAt;
    return freeze({
      loading, available, unavailableReason, generation, attempt,
      game: game ? { ...game } : null,
      readiness: { ...readiness, reasons: [...readiness.reasons], expired },
      schedule: { ...schedule },
      preparation: {
        state: preparation.state,
        content: preparation.content.map((entry) => ({ ...entry })),
        errorCode: preparation.errorCode,
        inFlight,
      },
      capabilities: {
        canSelectGame: available && !disposed,
        canSyncNow: available && !disposed && !!game && !inFlight,
        canSetSchedule: available && !disposed,
      },
    });
  };

  /** Reads never dispatch. Snapshots are value-stable: the same frozen object is
   * returned until something actually changes. */
  const getSnapshot = (): OfflineGameModeSnapshot => {
    const next = build();
    const key = JSON.stringify(next);
    if (cached && key === cachedKey) return cached;
    cached = next;
    cachedKey = key;
    return next;
  };

  // Compare the whole snapshot, not a state name. A content entry completing
  // while the overall state stays `active` is a real change subscribers need.
  const notify = () => {
    if (disposed) return false;
    const next = getSnapshot();
    // Reads may refresh the cache without delivering the change to subscribers.
    if (cachedKey === notifiedKey) return false;
    notifiedKey = cachedKey;
    for (const listener of [...listeners]) {
      try { listener(next); } catch { /* One bad subscriber must not stop the rest. */ }
    }
    return true;
  };

  const resetForNewSelection = () => {
    generation += 1;
    attempt = 0;
    readiness = { status: null, label: null, reasons: [], checkedAt: null, expiresAt: null };
    preparation = { state: "idle", content: emptyContent(), errorCode: null };
    inFlight = false;
  };

  /** Same app id is not the same subject: account and installed build are part
   * of identity, so a rebuild or an account switch is a new selection. */
  const sameSubject = (a: SelectedGame, b: SelectedGame) =>
    a?.appId === b?.appId && (a?.account ?? null) === (b?.account ?? null)
    && (a?.buildId ?? null) === (b?.buildId ?? null);

  const current = (observation: { generation: number; appId: number }) =>
    !disposed && observation.generation === generation && !!game && observation.appId === game.appId;

  return {
    getSnapshot,

    subscribe(listener: (snapshot: OfflineGameModeSnapshot) => void): () => void {
      if (typeof listener !== "function" || disposed) return () => {};
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },

    /** Resolve the injected initial state. Until this lands the tab reports
     * loading rather than inventing an empty but confident view. */
    applyInitialState(initial: InitialState | null): void {
      if (disposed) return;
      loading = false;
      available = initial?.available ?? false;
      unavailableReason = initial?.unavailableReason ?? (available ? null : "Offline preparation is unavailable");
      if (initial?.game !== undefined) game = initial.game;
      // An injected schedule is reported as-is and never enabled on our own.
      if (initial?.schedule) schedule = { ...initial.schedule };
      resetForNewSelection();
      notify();
    },

    selectGame(next: SelectedGame): void {
      if (disposed || !available) return;
      if (next !== null && !isExactAppId(next.appId)) return;
      if (sameSubject(game, next)) return;
      game = next ? { ...next } : null;
      resetForNewSelection();
      notify();
    },

    /** Recompute and notify if anything the clock affects has changed.
     *
     * Expiry is derived from `ports.now()`, so a subscribed view would never
     * hear about it on its own. The host drives this from whatever it already
     * has — a focus event, an existing interval — and the model stays free of
     * any scheduler of its own. Returns true when subscribers were notified.
     */
    refresh(): boolean {
      return notify();
    },

    /** One player action, one port call. Duplicate presses while a sync is in
     * flight are suppressed, and the suppression lifts on any terminal state,
     * so a retry is never permanently blocked. */
    syncNow(): boolean {
      if (disposed || !available || !game || inFlight) return false;
      attempt += 1;
      const dispatched = attempt;
      inFlight = true;
      // Set the optimistic state before dispatching, so a port that calls back
      // synchronously overwrites it rather than being overwritten by it.
      preparation = { state: "requested", content: emptyContent(), errorCode: null };
      try {
        ports.startSync(game.appId, generation, dispatched);
      } catch {
        // An observation delivered synchronously before the throw is real
        // evidence; only discard state that is still our own optimistic guess.
        if (attempt === dispatched && preparation.state === "requested") {
          preparation = { state: "error", content: emptyContent(), errorCode: null };
        }
        inFlight = false;
        notify();
        return false;
      }
      notify();
      return true;
    },

    setSyncSchedule(next: SyncSchedule): boolean {
      if (disposed || !available || !next || typeof next.enabled !== "boolean") return false;
      const interval = next.intervalMinutes;
      if (next.enabled && !(typeof interval === "number" && Number.isFinite(interval) && interval > 0)) return false;
      const candidate = { enabled: next.enabled, intervalMinutes: next.enabled ? (interval as number) : null };
      try {
        ports.persistSchedule({ ...candidate });
      } catch {
        return false;
      }
      schedule = candidate;
      notify();
      return true;
    },

    /** Fresh readiness evidence. Only this renews expiry. */
    applyReadiness(observation: ReadinessObservation): boolean {
      if (!observation || !current(observation)) return false;
      const checkedAt = integer(observation.checkedAt);
      if (checkedAt !== null && readiness.checkedAt !== null && checkedAt < readiness.checkedAt) return false;
      readiness = {
        status: observation.status,
        label: observation.label,
        reasons: [...(observation.reasons ?? [])],
        checkedAt,
        expiresAt: integer(observation.expiresAt),
      };
      notify();
      return true;
    },

    /** Preparation progress. Deliberately does NOT touch readiness expiry: a
     * finished download is not fresh evidence, and a longer schedule must never
     * keep a stale positive badge alive until the next check. */
    applyPreparation(observation: PreparationObservation): boolean {
      if (!observation || !current(observation)) return false;
      // A late reply from an earlier press of the same button, on the same
      // selection, must not land on the current attempt.
      if (integer(observation.attempt) !== attempt) return false;
      preparation = {
        state: observation.state,
        content: normalizeContent(observation.content),
        errorCode: integer(observation.errorCode ?? null),
      };
      if (TERMINAL.includes(observation.state)) inFlight = false;
      notify();
      return true;
    },

    setAvailability(next: { available: boolean; unavailableReason?: string | null }): void {
      if (disposed) return;
      available = !!next?.available;
      unavailableReason = next?.unavailableReason ?? (available ? null : "Offline preparation is unavailable");
      if (!available) { inFlight = false; }
      notify();
    },

    dispose(): void {
      if (disposed) return;
      disposed = true;
      inFlight = false;
      listeners.clear();
    },
  };
}

export type OfflineGameModeModel = ReturnType<typeof createOfflineGameModeModel>;
