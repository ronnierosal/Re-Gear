# Controller Safe Undock presentation

Status: **Implemented locally; native controller delivery and hardware validation pending**

The requested gesture is **Back/View + Y held for 3 seconds**. The pure backend
policy retains that threshold, exact-chord matching and verified-evidence
requirements. Its dormant logical-action relay remains separately tested.

The frontend candidate uses SteamClient.Input's non-exclusive native input
messages and controller-list changes, falling back to active-controller changes
on Steam builds such as the Ally that lack the list API. The installed Ally
returned valid unregister handles for both button and active-controller
subscriptions during a bounded subscribe/unsubscribe probe. Physical press
and disconnect delivery still require supervised verification. It tracks button edges per controller,
ignores repeats, requires the exact two-button chord, and cancels on release,
extra buttons, malformed events, controller-list changes or unload. One hold
can open at most one confirmation; release both buttons before another attempt.
No raw input grabbing, remapping, synthetic button presses or polling is added.

Snapshot evidence must use the current schema, be no more than 15 seconds old,
and not more than five seconds ahead of the frontend clock.
At chord start and completion, bounded read-only snapshot/journal requests
require an idle game, live Gamescope, certified support, a verified present
eGPU, an applicable disconnect workflow and an idle safety journal. Missing,
stale-in-flight or unknown evidence stays closed. Only one context read can
be outstanding; a timed-out read cannot later open a confirmation.

A valid hold opens the same confirmation as the panel button; it does not
execute a transition. Confirming uses the same backend approval and execution
APIs. The dialog captures whether the user confirmed Return to Ally or Shutdown,
and backend guards revalidate before action. A shared busy guard prevents a
panel click and shortcut from executing concurrently. The always-rendered
Decky content owns the subscription and releases it on unmount. Subscription
failure leaves the ordinary button available and labels the shortcut unavailable.

Hardware validation must establish native View/Y delivery, supported controller
mapping, operation outside Quick Access, cancellation on disconnect, and native
View-button behavior. API type declarations and fake-event tests do not
establish that hardware evidence.

## Physical removal boundary

From TV Docked, the confirmation returns through the existing Portable transition.
The player must acknowledge its durable result before requesting normal shutdown.
Intentional Portable return suppresses automatic redocking. Shutdown acceptance
is not power-off proof: keep the G1 connected until the fan and power LEDs are
off. If shutdown hangs, follow the separately supervised recovery procedure.

The alternate requested gesture is physical power-button double press, not RB.
It is not implemented: see [power-button feasibility](POWER_BUTTON_SAFE_UNDOCK.md).
The first press must preserve Steam's normal Sleep behavior. No UI advertises
power-button shortcut support or safe live unplugging.

## First supervised controller check

Install only with the G1 disconnected. During a later supervised attached, idle
session, first test confirmation delivery without confirming any transition.
Try five separate three-second holds with Quick Access closed; cancel each
dialog and fully release both buttons between attempts. Verify early release
opens nothing, partial release cannot reopen a dismissed dialog, and opening
a native Steam menu does not swallow the gesture or hide its confirmation.
Record controller model, transport, delivered dialogs and misses. Passing this
check establishes only that controller configuration; shutdown remains a
separate unresolved hardware gate. Double-power-press work is deferred until
Back/View + Y works consistently.
