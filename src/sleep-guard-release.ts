/** Wait, with evidence, until nothing is still blocking sleep.
 *
 * A software disconnect succeeding is not the same as sleep being allowed.
 * Two guards are still up on stale evidence at that moment, and Steam's own
 * suspend honours both:
 *
 * - the backend's login1 inhibitor, released only when its 1-second reconcile
 *   next observes the eGPU gone;
 * - Re-Gear's own Steam-side preflight blocker, released only when the panel's
 *   next snapshot poll calls `reconcile` with an observation that no longer
 *   needs it.
 *
 * Firing suspend the instant the disconnect returns races both. That is
 * exactly what the 2026-09-13 manual trial hit: dock removed, sleep pressed,
 * sleep blocked. So this reads fresh snapshots -- the same call the panel
 * already makes, no new poller, a bounded number of times inside one press --
 * until the backend reports the guard neither required nor held, then hands
 * that observation to the preflight so the Steam-side blocker drops on the
 * same evidence.
 *
 * It fails closed. If the guard is still required or still held when the
 * budget runs out, the answer is false and the caller must not sleep: an eGPU
 * that still needs a sleep guard is an eGPU that would wake the handheld
 * straight back up, and refusing is the smaller harm. It never releases the
 * blocker itself; only `reconcile` does, from evidence.
 */
import type { SnapshotPayload } from "./backend";

export interface SleepGuardReleasePorts {
  /** The panel's own snapshot read. */
  read(): Promise<SnapshotPayload>;
  /** Hand a fresh payload to the preflight; true when no blocker is required. */
  reconcile(payload: SnapshotPayload): boolean;
  wait(ms: number): Promise<void>;
}

/** Matches the backend's 1-second reconcile: a few reads across a few seconds
 * is enough for a guard that is going to drop, and not long enough to hold a
 * player's press hostage to one that is not. */
export const RELEASE_ATTEMPTS = 4;
export const RELEASE_INTERVAL_MS = 750;

export type SleepGuardRelease =
  | { released: true }
  | { released: false; code: "guard_required" | "guard_held" | "unreadable" | "blocker_required" };

/** True only when the backend guard is down AND the preflight agrees. */
export async function awaitSleepGuardRelease(
  ports: SleepGuardReleasePorts,
): Promise<SleepGuardRelease> {
  let last: SleepGuardRelease = { released: false, code: "unreadable" };
  for (let attempt = 0; attempt < RELEASE_ATTEMPTS; attempt++) {
    if (attempt > 0) await ports.wait(RELEASE_INTERVAL_MS);
    let payload: SnapshotPayload;
    try {
      payload = await ports.read();
    } catch {
      last = { released: false, code: "unreadable" };
      continue;
    }
    const guard = payload?.snapshot?.sleep_guard;
    if (!guard) {
      last = { released: false, code: "unreadable" };
      continue;
    }
    // `required` is the backend's decision from presence; `active` is whether
    // the login1 lease is actually held right now. Both must be false: a
    // guard the backend no longer wants can still be held for up to a second.
    if (guard.required !== false) {
      last = { released: false, code: "guard_required" };
      continue;
    }
    if (guard.active !== false) {
      last = { released: false, code: "guard_held" };
      continue;
    }
    // The evidence says nothing needs guarding. Let the preflight decide from
    // that same evidence; it is the only thing allowed to drop the blocker.
    if (!ports.reconcile(payload)) {
      last = { released: false, code: "blocker_required" };
      continue;
    }
    return { released: true };
  }
  return last;
}
