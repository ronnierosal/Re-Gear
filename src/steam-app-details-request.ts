// Adapted from mcarlucci/decky-storage-cleaner, src/utils.ts, revision
// 932e6876dbf94b6feb4b033401139b193f9cc79a. Upstream license: GNU GPL version 3.
// See THIRD_PARTY_NOTICES.md. Changes: injected subscription, cancellation,
// synchronous callback handling, fail-closed cleanup, and exact input checks.

export type SubscribeAppDetails = (
  appId: number,
  callback: (details: unknown) => void,
) => { unregister(): void };

/**
 * One private, explicitly requested game-detail subscription, never a poller.
 * Used by the bounded selected-game check; see the offline source review.
 * Callback receipt time does not prove freshness. Caller must minimize fields
 * and discard on game/session changes; raw details must not enter public RPC.
 */
export function requestSteamAppDetails(
  appId: number,
  subscribe: SubscribeAppDetails,
  signal?: AbortSignal,
): Promise<unknown | null> {
  if (!Number.isInteger(appId) || appId <= 0 || appId >= 2 ** 32 || signal?.aborted) {
    return Promise.resolve(null);
  }
  return new Promise((resolve) => {
    let lease: { unregister(): void } | undefined;
    let registrationFinished = false;
    let pending = false;
    let settled = false;
    let result: unknown = null;
    const drain = () => {
      if (!registrationFinished || !pending || settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      try {
        if (lease) lease.unregister();
      } catch {
        result = null;
      }
      resolve(result);
    };
    const finish = (value: unknown) => {
      if (pending || settled) return;
      pending = true;
      result = value ?? null;
      drain();
    };
    const abort = () => {
      // Cancellation during registration overrides an early callback result.
      if (!settled) { pending = true; result = null; drain(); }
    };
    const timer = setTimeout(() => finish(null), 1000);
    signal?.addEventListener("abort", abort, { once: true });
    try {
      lease = subscribe(appId, finish);
      if (!lease || typeof lease.unregister !== "function") {
        lease = undefined;
        pending = true;
        result = null;
      }
    } catch {
      pending = true;
      result = null;
    }
    registrationFinished = true;
    if (signal?.aborted) abort();
    drain();
  });
}
