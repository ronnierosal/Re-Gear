export type ReadingClock = {
  now(): number;
  schedule(callback: () => void, delay: number): () => void;
};
const clock: ReadingClock = {
  now: () => performance.now(),
  schedule(callback, delay) {
    const timer = setTimeout(callback, delay);
    return () => clearTimeout(timer);
  },
};
export type ReadingTicket = { generation: number; started: number };

/** Bounds a response from its own client request start, not device observation
 * time. The existing owner still performs every read; this adds only expiry. */
export function createControllerReadingLifetime<T>(time: ReadingClock = clock) {
  let eligible = false;
  let generation = 0;
  let current: T | null = null;
  let expiresAt = 0;
  let cancelExpiry: (() => void) | undefined;
  const listeners = new Set<() => void>();
  const publish = (value: T | null) => {
    if (current === value) return;
    current = value;
    for (const listener of listeners) listener();
  };
  const invalidate = () => {
    generation++;
    cancelExpiry?.(); cancelExpiry = undefined;
    expiresAt = 0;
    publish(null);
  };
  const source = {
    read: () => {
      // A throttled host timer must not let a later read return expired data.
      return current !== null && time.now() >= expiresAt ? null : current;
    },
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
  };
  return {
    source,
    setEligible(value: boolean) {
      if (eligible === value) return;
      eligible = value;
      if (!eligible) invalidate();
    },
    start(): ReadingTicket | null {
      if (!eligible) return null;
      invalidate();
      return { generation, started: time.now() };
    },
    complete(ticket: ReadingTicket | null, value: T | null) {
      if (!ticket || !eligible || ticket.generation !== generation) return;
      if (value === null || time.now() - ticket.started >= 10_000) {
        invalidate(); return;
      }
      expiresAt = ticket.started + 10_000;
      cancelExpiry = time.schedule(() => {
        if (ticket.generation === generation) invalidate();
      }, Math.max(0, expiresAt - time.now()));
      publish(value);
    },
    stop() { eligible = false; invalidate(); },
  };
}
