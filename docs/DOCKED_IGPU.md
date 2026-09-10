# Docked-iGPU workflow

Docked-iGPU is a first-class observed placement: the exact internal GPU renders
while the exact external display is active. It is not inferred merely because a
G1 and TV are connected.

## Implemented pieces

- The boot-scoped Gamescope config can explicitly select the TV connector and
  internal GPU.
- The existing supervised durable transition engine can promote exact idle
  Docked-iGPU to Docked-eGPU.
- The same engine can recover to Docked-iGPU after failed promotion.
- A bounded read-only watcher can arm only around one exact running Steam game,
  bind the Gamescope PID/start-time/UID generation, bracket its initial state
  with two game samples, and recognize its natural exit only after two exact
  Idle samples surround a fresh Docked-iGPU snapshot.
- The watcher cancels on another game, placement change, or expiry and enters
  Action Required on unknown identity/profile evidence.
- Public watcher payloads omit AppID, scopes, profile IDs, eGPU identity, and
  observation generations.
- A serialized backend lifecycle owns one private watch, provides bounded poll
  timing, requires acknowledgement after Action Required, and cancels the
  watch on unload. Preview-capable composition retains `promotion_ready` for
  inspection; production watch-only composition reports it for one five-second
  interval, clears the private watch, and resumes conservative discovery.
- Lifecycle inspection always requests an unconfirmed supervised preview. It
  exposes only placement/readiness/blocker categories and fails closed if any
  approval token is unexpectedly returned.
- An async driver serializes lifecycle ticks, quiesces at terminal
  states, supports an explicit wake after acknowledgement, rejects duplicate
  runners, and closes the lifecycle when its owner task is cancelled.
- The production backend binds the watcher to the exact Gamescope process
  generation, scans cheaply every fifteen seconds while ineligible and every
  five seconds while watching, exposes only categorical status in the opt-in
  troubleshooting view, and cancels it on plugin unload. A bounded supervisor
  retries construction or a failed runner after thirty seconds.
- Support Preview can now run one explicit bounded, read-only comparison of the
  exact game's DRM engine activity on the independently re-resolved Ally
  internal GPU and G1. Only categorical, identity-free results enter the
  support event log; this does not arm or execute a transition.

The watcher emits only `promotion_ready`. It cannot create approval, write
config, restart Gamescope, or invoke the transition engine. Current Ally X/G1
display handoff remains Experimental, so the supervised path still needs the
existing explicit short-lived approval.

The production backend constructs the opaque facade in watch-only mode. The
lifecycle owns its watch ID and private generations; neither crosses the Decky
boundary. Status and Action Required acknowledgement cannot inspect, approve,
or execute a transition. A separate dormant composition can connect the facade
to supervised read-only preview. It must observe the exact generation and
Docked-iGPU placement, retains the watch on inspection or a blocked preview,
and can consume it only after separate explicit confirmation produces a
short-lived approval token.

## Remaining gates

- prove on hardware that a running iGPU game can be presented on the TV through
  the G1 without changing game or Gamescope identity
- use a complete one-shot Support Preview comparison on the current candidate
  to observe internal activity and no G1 activity during that supervised
  experiment; either Unknown result is incomplete and proves neither absence
  nor placement
- hardware-test the identity-free watcher status, natural-exit readiness,
  Action Required acknowledgement, and unload cleanup
- wire the dormant identity-free inspection mapping only after production can
  construct the supervised read-only preview without importing mutation
  authority; keep confirmation and execution separate
- verify Docked-iGPU rollback before enabling any automatic trigger
- after transition, use exact DRM engine activity to prove the next game uses
  the G1

None of these pieces certifies live GPU migration. Re-Gear still never attempts to
move a running workload between GPUs.
