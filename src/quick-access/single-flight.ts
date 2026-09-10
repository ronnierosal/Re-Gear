/** One operation at a time, refused synchronously: pure, no React, no I/O.
 *
 * React state is not a lock. `setBusy(true)` does not take effect until the
 * next render, so two activations in the same tick both read the old value and
 * both dispatch. On a controller that is not hypothetical: a held button, a
 * double press, or an A press arriving alongside a confirmation dialog's own
 * activation all land inside one tick.
 *
 * The backend serialises the disconnect, but a second press must be refused
 * here as well. A player answered one confirmation and must get one operation;
 * "the backend will sort it out" is how a second request reaches a device that
 * has already begun changing.
 *
 * The claim is taken before the first await and released on EVERY outcome,
 * including failure and cancellation, so a refused attempt never wedges the
 * control permanently.
 */

export type SingleFlight = {
  /** Run `operation` unless one is already in flight. Returns `refused` in that
   * case, so a caller can tell "did not run" from "ran and returned nothing". */
  run<T>(operation: () => Promise<T>): Promise<{ ran: true; value: T } | { ran: false }>;
  /** Whether a run is currently in flight. */
  readonly busy: boolean;
};

export function createSingleFlight(): SingleFlight {
  let active = false;
  return {
    get busy() { return active; },
    async run<T>(operation: () => Promise<T>) {
      // Synchronous check and claim, with nothing awaited between them.
      if (active) return { ran: false as const };
      active = true;
      try {
        return { ran: true as const, value: await operation() };
      } finally {
        active = false;
      }
    },
  };
}
