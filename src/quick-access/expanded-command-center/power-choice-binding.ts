/** A visible power choice for the popups, and nothing else.
 *
 * The guarantee this module is held to, and the one its suite proves: WITHIN
 * THE QUIET WINDOW THE SUITE HOLDS -- `QUIET_WINDOW_MS` in
 * `frontend-tests/power-choice-binding.test.mjs` -- IT MAKES NO PORT CALL AND
 * NO NETWORK CALL THAT A BUTTON PRESS OR AN EXPLICIT `refresh()` DID NOT ASK
 * FOR: not on import, not on construction, and in none of the phases a request
 * can reach, watched or unwatched, however a poll would have asked for its
 * turn. The suite parks bindings in every phase the coordinator's own
 * `PowerPhase` says the machine can publish, presses nothing, and holds them
 * all across a window of real elapsed time in which neither port counter, and
 * no counter on the runtime's network surface, may move by one.
 *
 * The window is the bound, and it is half the claim. A poll whose period is
 * longer than `QUIET_WINDOW_MS` never comes due inside the window, and 2s, 5s
 * and 30s are periods a status poll is routinely given; the suite excludes none
 * of those. What it does exclude, it excludes regardless of MECHANISM, and that
 * is the strong half: a counter that must not move does not care whether the
 * turn was asked for by a timer, an `AbortSignal`, an event listener, a name
 * assembled at run time or a scheduler captured at import, which is more than
 * any spy on a scheduler's name can say.
 *
 * The port is counted because the port is the route this module is BUILT to
 * reach the backend by -- not because it is the only route the runtime offers.
 * It is not, so the suite counts the network surface as well: `fetch`,
 * `WebSocket`, `EventSource`, `XMLHttpRequest` and `sendBeacon` where the
 * runtime has them, and the socket layer all of those arrive at, which is what
 * catches a reference captured before a spy could be installed. Neither layer
 * is exhaustive, and the suite says where each one ends rather than implying it
 * is. Together the counters bound what a poll could cause OUTSIDE this module,
 * and no more than that. They are also not everything this module can do:
 * retiring the choice and disposing itself are damage that never touches any
 * counter, so the same window also freezes each parked binding's snapshot
 * identity, its choice, and the publications a subscriber hears.
 *
 * Cheaper lints sit behind that: the suite reads this file and checks that it
 * names no scheduler, imports nothing but the coordinator, calls `refresh` in
 * exactly one place, and states its bound -- in the sentence above that makes
 * the claim, not in some later one -- as the window, rather than as a number
 * that can go stale beside it or as an absolute the suite cannot hold anything
 * to. They catch the ordinary case early. They are lints on source text and
 * prove nothing about dormancy, and the suite says so where they are.
 *
 * Everything that makes a power request dangerous -- admission, ticket
 * identity, dispatch, single-flight, reply verification and disposal -- lives in
 * `createPowerRequestCoordinator`, with the argument and the suite to match. So
 * this file owns the one thing that module deliberately does not: a choice
 * presentation can render, and the discipline of retiring it. (No test here
 * establishes that division of labour; it is a thing to read.)
 *
 * A retired popup's buttons reach nothing. Pressing them neither dispatches nor
 * disturbs the request that replaced it -- not even when the replacement is the
 * same intent, so that every button the stale popup holds also exists on the
 * live request.
 *
 * Retirement follows the published phase, never a payload field. `requested`
 * means the backend accepted a submission, not that the machine slept; only
 * the coordinator's `sleep_observed` says that. A popup that closed on
 * `power_requested` would be telling a player the sleep happened because the
 * request was taken.
 *
 * The label and the token are the caller's, and both are passed on as given.
 * `connectionLabel` is rendered exactly as it was written, because a label this
 * module shortened or prettified would be this module describing hardware it
 * never observed. `attachmentToken` reaches the port untouched, empty string
 * included, because which topology an empty token means is the coordinator's
 * and the backend's decision, not a choice a popup binding is entitled to make
 * -- and for that same reason a token that was never supplied is refused rather
 * than admitted as an empty one. "The caller forgot" and "the caller meant
 * none" are different facts about the hardware, and inventing the second from
 * the first would dispatch a topology nobody asked for. A `connectionLabel`
 * that was never supplied is refused on the same rule and for the same reason:
 * admitting it would put a dispatchable choice on screen whose label is
 * `undefined`, which is this module describing the dock as nothing at all --
 * and a caller that forgot the words is a caller that has not decided what the
 * player should read. Pass through what was given; refuse what was not given.
 *
 * Admission is atomic from the caller's side. Everything the choice needs is
 * read off the request before the coordinator holds a ticket, so a request
 * object that fails to answer raises out of here with nothing admitted and the
 * binding still able to admit the next one. The failure is the caller's to see;
 * a ticket held while no popup shows a button for it is not -- it would refuse
 * every later request for the life of the binding, with nothing on screen able
 * to cancel it.
 *
 * Publications are serialized, never nested. A subscriber that publishes while
 * a delivery is running appends to a queue that the delivery in progress
 * drains in publication order, so every listener observes every publication in
 * the same order, and the last snapshot any of them is handed is the newest.
 * That ordering is the whole point of the queue: a nested fan-out delivers to
 * the listeners behind the re-entrant one backwards, and the last of those --
 * the popup, which renders whatever it was handed last -- is left showing
 * buttons for a ticket that is already gone. `read()` is the newest snapshot
 * that has been published.
 *
 * Two things take a popup out of that order, and both take effect immediately.
 * Unsubscribing: a popup detached part-way through a delivery does not receive
 * it, and a handle detaches only the registration it came from -- never a later
 * subscription that happens to use the same function, which is exactly what a
 * StrictMode remount produces. And disposal: it cuts every publication still
 * owed, so the last thing an attached popup hears is that its owner is gone,
 * and a popup that mounts into a binding already disposed attaches to nothing.
 *
 * A disposal is the one publication nothing here may hold back or overtake.
 * Held back -- suppressed by a capture, the way a `choosing` is -- it would
 * leave an attached popup rendering a request whose owner is gone as its last
 * word, with buttons nothing answers. Overtaken, it would leave the binding
 * reporting a live phase after disposal, which is what an owner that disposes
 * from inside its own `requestId` would otherwise produce. Disposed is the last
 * thing this binding ever says.
 *
 * `refresh()` is an owner's action or a person's.
 */
import { createPowerRequestCoordinator } from "../../power-request-coordinator";
import type { PowerPhase, PowerRequestPort, PowerView } from "../../power-request-coordinator";

type Coordinator = ReturnType<typeof createPowerRequestCoordinator>;
type SleepTicket = NonNullable<ReturnType<Coordinator["captureSleep"]>>;
type ShutdownTicket = NonNullable<ReturnType<Coordinator["captureShutdown"]>>;

/** What an owner knows when it asks for a choice: the identity the coordinator
 * will dispatch with, and the words this particular player should read. */
export type PowerChoiceRequest = Readonly<{ attachmentToken: string; connectionLabel: string }>;
export type SleepChoice = Readonly<{ intent: "sleep"; connectionLabel: string }> & SleepTicket;
export type ShutdownChoice = Readonly<{ intent: "shutdown"; connectionLabel: string }> & ShutdownTicket;
export type PowerChoice = SleepChoice | ShutdownChoice;
export type PowerChoiceView = Readonly<{ power: PowerView; choice: PowerChoice | null }>;
export type PowerChoiceListener = (view: PowerChoiceView) => void;

/** Phases where a rendered choice would be a lie: the request is over
 * (`refused`, `sleep_observed`), was never made (`idle`), or has no owner left
 * (`disposed`). Every other phase is an operation still worth showing --
 * including `uncertain`, where withdrawing the popup would be a claim that the
 * outcome is known. */
const RETIRING: ReadonlySet<PowerPhase> = new Set<PowerPhase>([
  "idle", "refused", "sleep_observed", "disposed",
]);

export function createPowerChoiceBinding(
  port: PowerRequestPort, options: { requestId?: () => string } = {},
) {
  /** A subscription is the registration, not the function. Two mounts of the
   * same popup are two subscriptions, and one's cleanup is not the other's. */
  type Registration = { readonly listener: PowerChoiceListener };
  const listeners = new Set<Registration>();
  /** Publications waiting their turn, oldest first. */
  const pending: PowerChoiceView[] = [];
  let draining = false;
  let choice: PowerChoice | null = null;
  /** How many captures are open, not whether one is. A nested capture's exit
   * must not clear the outer capture's suppression: the outer ticket's
   * `choosing` would then publish paired with the inner request's popup, which
   * the outer admission has already displaced. */
  let captureDepth = 0;
  let disposed = false;
  const coordinator = createPowerRequestCoordinator(port, {
    requestId: options.requestId, onChange: observe,
  });
  let view: PowerChoiceView = Object.freeze({ power: coordinator.read(), choice });

  function publish() {
    const power = coordinator.read();
    // Disposed is the last thing this binding says. An owner that disposes from
    // inside its own `requestId` leaves the coordinator publishing `choosing`
    // after the disposal, and forwarding that would leave presentation holding
    // an intent and a requestId for a ticket nobody can cancel, with no popup
    // and no way to end it.
    if (disposed && power.phase !== "disposed") return;
    // Nothing observable moved, so nothing was published: a snapshot identity
    // is how presentation decides it has to re-render.
    if (view.power === power && view.choice === choice) return;
    view = Object.freeze({ power, choice });
    pending.push(view);
    // One delivery at a time, in publication order. Starting a second one from
    // inside the first is what hands the listeners behind a re-entrant popup
    // their publications backwards, oldest last.
    if (draining) return;
    drain();
  }
  function drain() {
    draining = true;
    try {
      while (pending.length > 0) {
        const published = pending[0];
        pending.shift();
        // The copy is the decision, not an artefact of writing it this way. A
        // popup that subscribes from inside this fan-out is not handed the
        // publication already in flight: it never saw the state that
        // publication reports a change from, so being told about the change
        // would be telling it about a transition it has no "before" for. It is
        // attached from the next publication on.
        for (const registration of [...listeners]) {
          // Detaching is immediate. A popup unsubscribed by an earlier listener
          // in this same delivery is gone before its turn arrives.
          if (!listeners.has(registration)) continue;
          // A disposal cuts every publication still owed behind it, so the last
          // thing an attached popup hears is that its owner is gone -- not a
          // dispatch phase from a request the disposal already ended.
          if (disposed && published.power.phase !== "disposed") continue;
          // Presentation is not operation ownership. A popup that throws,
          // detaches or re-enters cannot change what the coordinator does next,
          // and cannot cost the listeners or the publications behind it a turn.
          try { registration.listener(published); } catch { /* A failed render is not a failed request. */ }
        }
      }
    } finally {
      // The reset is in a `finally` so a drain that ends any other way still
      // leaves the next publication able to start one. Nothing in the loop can
      // end it any other way today -- a listener's throw is caught at the call
      // -- so no test here tells this apart from a plain assignment after the
      // loop.
      draining = false;
    }
  }
  function observe() {
    const phase = coordinator.read().phase;
    if (RETIRING.has(phase)) choice = null;
    // Mid-capture the coordinator has published "choosing" but the buttons for
    // it do not exist yet; the capture publishes once, with them attached.
    // A disposal is not that, and must never wait for a capture that will now
    // never produce buttons: the popups attached at this moment are about to be
    // detached, and suppressing it would leave them rendering a request whose
    // owner is gone -- permanently, because the capture clears the choice and
    // nothing is ever published to them again.
    if (captureDepth > 0 && phase !== "disposed") return;
    publish();
  }
  function capture<T>(open: () => T | null): T | null {
    captureDepth += 1;
    try { return open(); } finally { captureDepth -= 1; }
  }
  /** Admission, and the one guarantee a caller cannot check for itself: a
   * request object that raises while it is being read leaves the binding able
   * to admit the next request, instead of wedged behind a ticket no popup can
   * cancel. The boolean is a narrower thing -- it answers whether the choice
   * THIS call put up is the one still standing when the call returns, which
   * `false` can mean while a different, live choice is on screen. */
  function begin<T extends { cancel: () => void }>(
    request: PowerChoiceRequest,
    open: (attachmentToken: string) => T | null,
    dress: (ticket: T, connectionLabel: string) => PowerChoice,
  ): boolean {
    // Read every fact this choice needs before anything is admitted, so a
    // request object that fails to answer cannot strand a live ticket.
    const attachmentToken = request.attachmentToken;
    const connectionLabel = request.connectionLabel;
    // An absent token is a caller mistake, not an empty topology.
    if (typeof attachmentToken !== "string") return false;
    // And an absent label is the same mistake one field over. Admitting it
    // would hand back `true` -- render this -- for a dispatchable choice whose
    // words are `undefined`.
    if (typeof connectionLabel !== "string") return false;
    const ticket = capture(() => open(attachmentToken));
    // A refused admission leaves the live choice alone: the coordinator refuses
    // precisely when an earlier request still owns the operation, and that
    // request's popup still needs its buttons. It publishes anyway, because the
    // caller's `requestId` can retire a choice from inside this capture, where
    // the retirement's own publication is suppressed; a refusal is then the
    // last chance anything has to tell presentation the buttons are gone.
    if (!ticket) { publish(); return false; }
    // An owner whose own `requestId` disposed this binding left no presentation
    // for the buttons to appear in, and a binding nobody is watching must not
    // be showing a choice. So the ticket is not dressed and no choice goes up.
    let dressed: PowerChoice | null = null;
    if (!disposed) {
      choice = dress(ticket, connectionLabel);
      dressed = choice;
    }
    publish();
    // Publishing is the one window in which a popup can take this choice back
    // off screen before this call has returned: by cancelling it, by disposing
    // the owner, or by capturing a replacement over it. Reporting a choice that
    // is already gone -- or somebody else's -- would be the caller's cue to
    // render one. So the answer is whether the choice this call put up is the
    // one still standing, not merely whether something is.
    return dressed !== null && choice === dressed;
  }
  function beginSleep(request: PowerChoiceRequest): boolean {
    return begin(request, (attachmentToken) => coordinator.captureSleep(attachmentToken),
      (ticket, connectionLabel): SleepChoice =>
        Object.freeze({ intent: "sleep", connectionLabel, ...ticket }));
  }
  function beginShutdown(request: PowerChoiceRequest): boolean {
    return begin(request, (attachmentToken) => coordinator.captureShutdown(attachmentToken),
      (ticket, connectionLabel): ShutdownChoice =>
        Object.freeze({ intent: "shutdown", connectionLabel, ...ticket }));
  }
  return Object.freeze({
    read: (): PowerChoiceView => view,
    subscribe(listener: PowerChoiceListener): () => void {
      // A popup mounting into a disposed binding is attaching to nothing --
      // including the disposal delivery it may itself be running inside, which
      // is the one publication a late registration could still be handed.
      if (disposed) return () => { /* Already detached. */ };
      const registration: Registration = { listener };
      listeners.add(registration);
      // This handle detaches this registration and nothing else, however many
      // times it is called and whoever else subscribed the same function.
      return () => { listeners.delete(registration); };
    },
    beginSleep,
    beginShutdown,
    /** An explicit readback, owned by the caller. This module never calls it:
     * the suite's source gate holds this file to exactly one `refresh` call
     * site, and it is the forward on the next line. That is a lint on source
     * text -- it cannot see a call reached without spelling the name -- and the
     * quiet window is what covers the rest. */
    refresh: (): Promise<void> => coordinator.refresh(),
    dispose(): void {
      if (disposed) return;
      disposed = true;
      // Disposal detaches presentation and forbids new dispatch. It sends
      // nothing: a submission the backend already accepted is not ours to
      // recall, and pretending otherwise would be the more dangerous lie. A
      // disposal raised from inside a delivery still reaches the popups
      // attached at that moment rather than swallowing its own announcement,
      // and one raised from inside a capture is not held back the way a
      // `choosing` is.
      coordinator.dispose();
    },
  });
}
