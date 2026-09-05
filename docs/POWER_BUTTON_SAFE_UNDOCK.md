# Physical power-button Safe Undock feasibility

## Decision

HDM does **not** implement physical power-button double-press Safe Undock.
The current platform boundary cannot distinguish first and second power-button
presses before Steam handles ordinary Sleep, and the Ally profile marks physical
button interception Experimental only. Delaying, suppressing, reinjecting, or
synthetically replaying a first press would change normal Sleep behavior and is
outside HDM's current authority.

The physical button remains Steam-owned. HDM's existing Steam preflight may
block an unsafe G1-attached sleep request, but that is safety enforcement, not
a double-press gesture implementation.

## Evidence and limits

- Read-only capture can observe topology and categorical wake state only. It
  cannot observe button edges, a Steam sleep lifecycle, suspend/resume, or
  player-visible recovery.
- Earlier supervised evidence showed guarded requests could be blocked, but did
  not validate physical-button UX, G1-attached sleep, or a double-press order.
- The canonical sleep facade is dormant and models `SLEEP`; it is not the
  delivery target for an `UNDOCK` gesture.

## Current fallback

The controller alternative is the locally implemented candidate: verified,
exact **Xbox/Guide + Y** held for 3 seconds. Its pure policy emits
`LogicalAction.SAFE_UNDOCK`, which routes to the ordinary `UNDOCK` intent. The
delivery relay accepts one verified opaque event at most once and has no input
listener, mechanism, or transition authority.

No UI may claim physical power-button support. The native Xbox/Guide + Y
listener candidate opens the existing guarded confirmation; hardware event
delivery and Guide-menu compatibility remain unverified. A controller-focusable Decky fallback is
implemented separately: return to verified Portable, acknowledge the durable
transition, then issue one confirmed normal shutdown request. The accepted
request is not a completion result. Physical removal remains prohibited until
the fan has stopped and the Ally is physically off. The 2026-09-02 watched G1
test required a manual long power-button hold after user space and networking
stopped but the fan and two top LEDs remained on; HDM must not automate that
forced-off recovery.

## Future gate

Reconsider a double press only when SteamOS or Steam exposes a supported,
non-exclusive, verified physical-button event source that guarantees native
single-press behavior is passed through. A future adapter must:

1. fail closed for unknown/unverified profile, event, generation, or timing;
2. emit only the second verified edge within a bounded window;
3. route `SAFE_UNDOCK` through the existing logical-action `UNDOCK` path;
4. never grab raw input, suppress/reinject a press, or synthesize Sleep; and
5. pass a player-watched supervised validation of event ordering, ordinary
   Sleep pass-through, display/input/network recovery, and no unsafe eGPU
   removal.

Until that gate passes, Safe Undock can only assess and explain readiness. The
current G1 profile remains shutdown-before-disconnect and never confirms live
physical unplugging.
