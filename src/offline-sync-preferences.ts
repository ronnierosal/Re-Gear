/** Re-Gear's own offline sync preference, over an injected store.
 *
 * This persists a Re-Gear setting and nothing else. It never writes Steam,
 * account or game configuration, and it never enables a schedule on its own:
 * anything missing, malformed or out of range reads back as disabled, because a
 * player who never turned this on must not find it running.
 */

export type SyncPreferences = {
  enabled: boolean;
  intervalMinutes: number | null;
};

/** Below this a schedule would behave like polling rather than a cadence. */
export const MIN_INTERVAL_MINUTES = 15;
/** A week. Beyond this the evidence would always be expired anyway. */
export const MAX_INTERVAL_MINUTES = 10080;

export const DISABLED: SyncPreferences = Object.freeze({
  enabled: false,
  intervalMinutes: null,
});

export type SyncPreferencesStore = {
  /** Re-Gear's own storage. May return anything, including nothing. */
  read(): unknown;
  write(value: SyncPreferences): void;
};

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function isUsableInterval(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value)
    && value >= MIN_INTERVAL_MINUTES && value <= MAX_INTERVAL_MINUTES;
}

/** Fail closed: only an explicitly enabled, in-range preference survives. */
export function sanitizeSyncPreferences(raw: unknown): SyncPreferences {
  const source = record(raw);
  if (!source || source.enabled !== true) return { ...DISABLED };
  return isUsableInterval(source.intervalMinutes)
    ? { enabled: true, intervalMinutes: source.intervalMinutes }
    : { ...DISABLED };
}

export function createSyncPreferences(store: SyncPreferencesStore) {
  let current: SyncPreferences;
  try {
    current = sanitizeSyncPreferences(store.read());
  } catch {
    // Unreadable storage is not consent to run on a schedule.
    current = { ...DISABLED };
  }

  return {
    get(): SyncPreferences {
      return { ...current };
    },

    /** Returns false and changes nothing when the value is unusable or the
     * store refuses it, so the caller never shows a setting that did not stick. */
    set(next: unknown): boolean {
      const source = record(next);
      if (!source || typeof source.enabled !== "boolean") return false;
      if (source.enabled && !isUsableInterval(source.intervalMinutes)) return false;
      const value: SyncPreferences = source.enabled
        ? { enabled: true, intervalMinutes: source.intervalMinutes as number }
        : { ...DISABLED };
      try {
        store.write({ ...value });
      } catch {
        return false;
      }
      current = value;
      return true;
    },
  };
}

export type OfflineSyncPreferences = ReturnType<typeof createSyncPreferences>;
