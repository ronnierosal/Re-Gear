# Event-driven automatic link recovery

Ronnie requested attach-triggered recovery on 2026-09-11: settle about ten
seconds, try recovery, then consider one more guarded attempt after ten seconds.
The installed 0.3.81 manual path successfully recovered G1 detection and automatic
TV switching; picture, audio and controls were confirmed. That is evidence for
the mechanism, not proof of automatic scheduling or kernel causality.

## Behavior

Existing topology events wake the same observation loop used by polling. They do
not issue commands directly. A separately consented automatic-recovery preference
defaults off. Existing automatic-TV-docking consent alone does not enable it.

The plugin must first observe verified transport absence. A plugin reload with
an already attached dock therefore cannot restart the session again. A uniquely
identified supported transport begins a ten-second settling window. At least
ten seconds of idle evidence are required; running/unknown game state restarts
that wait. A fresh snapshot, exact host, only the verified internal GPU, unique
Gamescope user, and idle durable transition journal are required before execution.

Recovery uses one plain Gaming Mode restart through the shared service. The
worker remains tracked by the existing lifecycle. At most two automatic attempts
are allowed per observed attachment. The second cannot start until the first
finishes and a further ten seconds of idle observation pass. GPU arrival stops
attempts. Missing/ambiguous observations do not reset the budget; only verified
transport absence does. The service also enforces its atomic execution guard.
A manual attempt cannot be extended by the automatic policy.

TV switching still requires independent display/audio/session readiness. A
powered-off or undetected TV is not treated as a usable output. Desktop mirroring
and Re-Gear's stricter display-readiness test remain distinct.

## Consent and test interface

The existing `set_automatic_dock_enabled(enabled, user_confirmed)` RPC accepts
an optional third boolean `recovery_enabled`. Omission preserves the separate
preference. Enabling requires exact boolean consent; disabling automatic docking
stops automatic recovery too. `get_automatic_dock_status` includes a `recovery`
object reporting the preference and bounded policy settings. The dedicated
preference uses the existing fixed-root atomic store with a fixed separate filename.

For the supervised candidate, enable both only after the maintainer has authorized
automatic session restarts, then read back both settings before a detached boot
and attachment. The existing player toggle controls docking; a dedicated player
recovery-preference control is not yet included. Do not call this generally
released or fully player-configurable until that UI is delivered and validated.

## Verification

Policy tests cover settling, cooldown after completion, two-attempt exhaustion,
no overlap, game-state delay, GPU arrival, identity ambiguity, absent evidence,
startup with an attached dock, and separate persisted consent. Integration tests
exercise fresh game and journal rejection and the shared command path.
Native automatic timing and end-to-end TV results remain a supervised gate.
Retain the immutable 0.3.81 manual-recovery ZIP and its evidence for rollback.

0.3.82 local validation: 2,983 backend tests completed with 101 skips; architecture and compileall passed. The prior manual build remains unchanged on the Ally. This candidate's automatic behavior has not yet been exercised on hardware.

