export const ATTACHED_EGPU_SLEEP_WARNING_KEY =
  "regear.hideAttachedEgpuSleepWarning.v1";

export const FORMER_ATTACHED_EGPU_SLEEP_WARNING_KEYS = [
  "hdm.hideAttachedEgpuSleepWarning",
  "hdm.hideAttachedG1SleepWarning",
] as const;

export interface PreferenceStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

function browserStorage(): PreferenceStorage | undefined {
  try {
    return globalThis.localStorage;
  } catch {
    return undefined;
  }
}

function removeFormerKeys(storage: PreferenceStorage): void {
  for (const key of FORMER_ATTACHED_EGPU_SLEEP_WARNING_KEYS) {
    try {
      storage.removeItem(key);
    } catch {
      // The current value is already durable. Cleanup can be retried later.
    }
  }
}

export function readAttachedEgpuSleepWarningDismissed(
  storage: PreferenceStorage | undefined = browserStorage(),
): boolean {
  if (!storage) return false;

  let current: string | null;
  try {
    current = storage.getItem(ATTACHED_EGPU_SLEEP_WARNING_KEY);
  } catch {
    return false;
  }

  if (current !== null) return current === "1";

  let formerValues: readonly (string | null)[];
  try {
    formerValues = FORMER_ATTACHED_EGPU_SLEEP_WARNING_KEYS.map((key) =>
      storage.getItem(key),
    );
  } catch {
    return false;
  }

  if (!formerValues.some((value) => value === "1")) return false;

  try {
    storage.setItem(ATTACHED_EGPU_SLEEP_WARNING_KEY, "1");
  } catch {
    // Honor the dismissal for this read, but preserve the former durable value.
    return true;
  }

  removeFormerKeys(storage);
  return true;
}

export function dismissAttachedEgpuSleepWarning(
  storage: PreferenceStorage | undefined = browserStorage(),
): boolean {
  if (!storage) return false;

  try {
    storage.setItem(ATTACHED_EGPU_SLEEP_WARNING_KEY, "1");
  } catch {
    return false;
  }

  removeFormerKeys(storage);
  return true;
}

export function resetAttachedEgpuSleepWarning(
  storage: PreferenceStorage | undefined = browserStorage(),
): void {
  if (!storage) return;

  for (const key of [
    ATTACHED_EGPU_SLEEP_WARNING_KEY,
    ...FORMER_ATTACHED_EGPU_SLEEP_WARNING_KEYS,
  ]) {
    try {
      storage.removeItem(key);
    } catch {
      // Reset is best-effort so one inaccessible key does not block the rest.
    }
  }
}
