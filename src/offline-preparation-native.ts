/** One explicitly requested preparation action for one chosen local game.
 *
 * Steam's download mutators return `void`, so nothing this module calls can
 * report that Steam accepted the request. Acceptance is only ever inferred by
 * watching the download list change relative to a baseline captured before
 * dispatch. A request that produces no observed change expires to
 * `unconfirmed` rather than sitting in `requested` forever, and a download item
 * that was already complete before we asked is never this request's completion.
 *
 * Finishing a download does not prove a game launches offline. See
 * docs/OFFLINE_EVIDENCE_SOURCE_REVIEW.md.
 *
 * No polling, persistence, launch authority, settings write or cache deletion.
 * Deliberately never calls SetLaunchOnUpdateComplete, EnableAllDownloads,
 * SetAppAutoUpdateBehavior, SetAppBackgroundDownloadsBehavior or
 * Settings.ClearDownloadCache. PauseAppUpdate is excluded too: upstream
 * documents it as behaving like RemoveFromDownloadList.
 */

export type PreparationContentType = "content" | "shader" | "workshop";

/** Steam indexes update_type_info by a native enum whose numeric values are not
 * published. The caller supplies the mapping from a verified source; we never
 * guess an index. */
export type ContentTypeIndex = Partial<Record<PreparationContentType, number>>;

export type PreparationState =
  | "unavailable"
  | "requested"
  | "queued"
  | "active"
  | "completed"
  | "error"
  | "unconfirmed";

export type PreparationContent = {
  type: PreparationContentType;
  /** null means Steam did not report this content type in a shape we accept. */
  hasUpdate: boolean | null;
  completed: boolean | null;
};

export type PreparationReport = {
  appId: number;
  state: PreparationState;
  content: PreparationContent[];
  buildId: number | null;
  targetBuildId: number | null;
  /** EAppUpdateError as reported. Callers map it to their own player copy;
   * Steam's update_error string is unlocalized and is never carried here. */
  errorCode: number | null;
};

export type DownloadSubscription = { unregister(): void };

/** The narrow native seam. Nothing in this module reads a global directly. */
export type PreparationPorts = {
  /** Must return the LOCAL client id, from the app overview's
   * local_per_client_data.clientid. Returning null fails the request closed.
   * Never substitute the currently viewed remote client. */
  localClientId(appId: number): string | null;
  queueAppUpdate?(appId: number, clientId: string): void;
  resumeAppUpdate?(appId: number, clientId: string): void;
  registerForDownloadItems?(
    callback: (isDownloading: boolean, items: unknown[]) => void,
  ): DownloadSubscription;
  /** Verified numeric indices for update_type_info. */
  contentTypeIndex: ContentTypeIndex;
};

export type PreparationKind = "queue" | "resume";

/** Thrown only for a player-initiated action Steam cannot be asked to perform,
 * so a caller can always tell "never asked" from "asked and unfinished".
 * Parameter properties are avoided deliberately: the frontend suites load these
 * modules through Node's strip-only TypeScript mode, which rejects them. */
export class PreparationUnavailableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PreparationUnavailableError";
  }
}

const CONTENT_TYPES: PreparationContentType[] = ["content", "shader", "workshop"];
const UNCONFIRMED_AFTER_MS = 30000;

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function integer(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) ? value : null;
}

function boolean(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

export function isExactAppId(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) > 0 && (value as number) < 2 ** 32;
}

/** One download-list entry reduced to the fields we accept.
 *
 * The published UpdateTypeInfo type and the shipped client disagree: the client
 * reads `completed` while the declaration names `completed_update`, and the
 * client nests byte counts under `progress[]`. We accept either completion
 * field and treat anything else as unknown rather than as "no update".
 */
export function projectDownloadItem(
  raw: unknown,
  appId: number,
  index: ContentTypeIndex,
): { item: Record<string, unknown>; content: PreparationContent[]; buildId: number | null; targetBuildId: number | null; errorCode: number | null } | null {
  const item = record(raw);
  if (!item || integer(item.appid) !== appId) return null;
  const info = Array.isArray(item.update_type_info) ? item.update_type_info : [];
  const content = CONTENT_TYPES.map((type) => {
    const at = index[type];
    const entry = at !== undefined && Number.isInteger(at) ? record(info[at]) : null;
    if (!entry) return { type, hasUpdate: null, completed: null };
    const completed = boolean(entry.completed) ?? boolean(entry.completed_update);
    return { type, hasUpdate: boolean(entry.has_update), completed };
  });
  return {
    item,
    content,
    buildId: integer(item.buildid),
    targetBuildId: integer(item.target_buildid),
    errorCode: integer(item.update_result),
  };
}

/** The observed state of one item, before baseline comparison. */
function observedState(item: Record<string, unknown>, errorCode: number | null): PreparationState | null {
  if (errorCode !== null && errorCode !== 0) return "error";
  if (boolean(item.completed) === true) return "completed";
  if (boolean(item.active) === true) return "active";
  // queue_index is -1 when unqueued. A paused item is still in the download
  // list, so it reports as queued rather than as progress or as an error.
  const queueIndex = integer(item.queue_index);
  if ((queueIndex !== null && queueIndex >= 0) || boolean(item.paused) === true) return "queued";
  return null;
}

/** A fingerprint of the item as it stood before we dispatched.
 *
 * A game that was already fully downloaded before the player asked must not be
 * reported as this request completing, so completion only counts when the
 * fingerprint moved.
 */
function fingerprint(item: Record<string, unknown>): string {
  return [
    boolean(item.completed) === true ? 1 : 0,
    integer(item.completed_time) ?? -1,
    integer(item.target_buildid) ?? -1,
    integer(item.update_result) ?? -1,
  ].join(":");
}

export function startOfflinePreparation(
  appId: number,
  kind: PreparationKind,
  ports: PreparationPorts,
  onChange: (report: PreparationReport) => void,
  options: { unconfirmedAfterMs?: number } = {},
): { stop(): void } {
  if (!isExactAppId(appId)) {
    throw new PreparationUnavailableError("A valid local game was not selected");
  }
  const method = kind === "queue" ? "QueueAppUpdate" : "ResumeAppUpdate";
  const dispatch = kind === "queue" ? ports.queueAppUpdate : ports.resumeAppUpdate;
  const subscribe = ports.registerForDownloadItems;
  // Absent means absent, reported as such. A player asked for this, so a
  // missing method must never look like a request that quietly did nothing.
  if (typeof dispatch !== "function") {
    throw new PreparationUnavailableError(`SteamClient.Downloads.${method} is unavailable`);
  }
  if (typeof subscribe !== "function") {
    throw new PreparationUnavailableError(
      "SteamClient.Downloads.RegisterForDownloadItems is unavailable",
    );
  }
  const clientId = ports.localClientId(appId);
  if (typeof clientId !== "string" || clientId.length === 0) {
    // Never default a client id and never assume the currently viewed remote
    // client is this machine.
    throw new PreparationUnavailableError("The local Steam client could not be identified");
  }

  let stopped = false;
  let lease: DownloadSubscription | undefined;
  let baseline: string | null | undefined;
  let dispatched = false;
  let last: PreparationState | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const emit = (state: PreparationState, projected: ReturnType<typeof projectDownloadItem>) => {
    if (stopped || state === last) return;
    last = state;
    onChange({
      appId,
      state,
      content: projected?.content ?? CONTENT_TYPES.map((type) => ({ type, hasUpdate: null, completed: null })),
      buildId: projected?.buildId ?? null,
      targetBuildId: projected?.targetBuildId ?? null,
      errorCode: projected?.errorCode ?? null,
    });
  };

  const stop = () => {
    if (stopped) return;
    stopped = true;
    clearTimeout(timer);
    try {
      lease?.unregister();
    } catch {
      /* A failed unregister must not mask the result already delivered. */
    }
    lease = undefined;
  };

  const observe = (_isDownloading: boolean, items: unknown[]) => {
    if (stopped) return;
    const list = Array.isArray(items) ? items : [];
    let projected: ReturnType<typeof projectDownloadItem> = null;
    for (const raw of list) {
      // Correlate strictly by the exact app id we asked about. Other games'
      // downloads are not our business and must never move our state.
      const candidate = projectDownloadItem(raw, appId, ports.contentTypeIndex);
      if (candidate) { projected = candidate; break; }
    }
    // The first snapshot we see is the baseline, whether it arrives
    // synchronously during registration or after dispatch. Steam gives us no
    // acceptance signal, so without a baseline we cannot tell a pre-existing
    // download from one our request caused.
    if (baseline === undefined) baseline = projected ? fingerprint(projected.item) : null;
    if (!dispatched || !projected) return;
    const state = observedState(projected.item, projected.errorCode);
    if (state === null) return;
    // `queued`, `active` and `error` describe what is true right now, and a
    // current failure is worth surfacing whoever caused it. `completed` is the
    // one claim about an outcome, so it is only ours once the fingerprint has
    // moved: a game that was already fully downloaded before the player asked
    // must never read as this request succeeding.
    if (state === "completed" && fingerprint(projected.item) === baseline) return;
    clearTimeout(timer);
    emit(state, projected);
    if (state === "completed" || state === "error") stop();
  };

  try {
    lease = subscribe(observe);
  } catch {
    throw new PreparationUnavailableError(
      "SteamClient.Downloads.RegisterForDownloadItems is unavailable",
    );
  }
  if (!lease || typeof lease.unregister !== "function") {
    lease = undefined;
    throw new PreparationUnavailableError(
      "SteamClient.Downloads.RegisterForDownloadItems is unavailable",
    );
  }
  try {
    dispatch(appId, clientId);
  } catch {
    stop();
    throw new PreparationUnavailableError(`SteamClient.Downloads.${method} did not accept the request`);
  }
  dispatched = true;
  emit("requested", null);

  // The call returned void, which is not acceptance. Give Steam a bounded
  // window to show the request in the download list, then say so honestly.
  timer = setTimeout(() => {
    if (stopped) return;
    emit("unconfirmed", null);
    stop();
  }, options.unconfirmedAfterMs ?? UNCONFIRMED_AFTER_MS);

  return { stop };
}
