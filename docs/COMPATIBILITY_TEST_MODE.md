# Compatibility Test Mode

## Exact external-render evidence

The dormant test policy can now consume bounded exact DRM engine activity for
the eGPU-handoff dimension. The collector requires the same Steam AppID as the
recorded internal-GPU baseline, observed engine-counter growth on the exact G1,
and Docked-eGPU placement from that evidence snapshot. Idle, missing, raced, or
non-docked evidence stops the session in Action Required and disables temporary
diagnostics.

Successful collection records only the hashed evidence generation and the
categorical external-render result. It does not complete or review the session.
Simulation still cannot promote a catalog record; a hardware result still
requires trusted-runner authorization, explicit finish, and human review. No
Decky UI or production plugin construction exists. An application-only
lifecycle owns one ephemeral session and applies its temporary-diagnostics
directives exactly; it cannot trigger a collector, catalog write, or hardware
transition. It may call its injected baseline collector with a backend-owned
user context; missing or failed observer evidence stops the session and turns
temporary diagnostics off. Trusted hardware-test authorization remains an
injected backend boundary rather than frontend-supplied data.

An identity-free status mapper is ready for future controller-first delivery. It
contains only categorical stage, code, selected dimensions, recorded outcomes,
and Action Required/review flags. It exposes no session ID, AppID, profile ID,
evidence generation, clock value, or authorization state, and is not yet wired
to a Decky RPC or UI.

Compatibility Test Mode is currently a dormant session policy, simulator, and
read-only baseline/external-render evidence collector. A baseline requires a
stable exact Steam session before and after active internal-GPU evidence; idle,
unknown, raced, or external-placement evidence does not create a baseline. It
uses the same exact-session bracket around external-GPU evidence, so a session
race cannot record a false eGPU result. It does not dock, undock, close a game,
save, relaunch, signal a process, request sleep, or publish a catalog result.

The save/exit dimension can additionally record **Graceful Exit Verified**
through a read-only bracket: Re-Gear must first observe the exact active Steam AppID
and later observe a fresh exact idle sample after the player exits it. It cannot
close a game, trigger a save, or claim that progress was preserved. A different
game, stale sample, unknown state, missing observer, or missing prior watch
stops the test in Action Required. This collector is simulated only until a
supervised procedure proves it on the certified hardware profile.

The entry criteria, pass/fail conditions, retained evidence, and recovery rules
for that future supervised proof are in [Compatibility hardware
validation](COMPATIBILITY_HARDWARE_VALIDATION.md). It must not be run from the
remote harness.

## Session flow

1. Require explicit player confirmation and select at least one test dimension.
2. Enable temporary diagnostics for the bounded session.
3. Capture a baseline generation, placement, game state, optional Steam AppID,
   and observed rendering GPU.
4. Record each requested result only from a fresh observation generation.
5. Require external-render evidence for a Verified eGPU result and internal
   render evidence for an iGPU-fallback result.
6. Disable temporary diagnostics before presenting results for review.
7. Require explicit human review to create evidence.

The session expires after at most two hours. Expiry, cancellation, stale
evidence, mismatched render evidence, or out-of-order events disable temporary
diagnostics and stop the session.

## Publication boundary

Reviewed simulation produces simulation evidence, which the catalog promotion
gate rejects. A future supervised hardware session may produce hardware-test
evidence, but the result still does not publish or promote itself; a separate
intentional catalog action must consume it. Telemetry never becomes Verified
automatically.

The evidence kind is backend-owned. Hardware-test evidence additionally
requires explicit trusted-runner authorization that must never be exposed as a
frontend boolean or general RPC argument. Immutable stage validation rejects a
reviewable record without its baseline, fresh generation history, and every
requested result.

Reviewed evidence is bound to the session's backend-owned catalog game identity
and the exact baseline Steam AppID, preventing a result from being reused for a
different title.

No production plugin construction, Decky RPC, or UI is enabled. A dormant
fixed-path atomic catalog store is available only for already domain-validated
records; a backend-only transaction service can write through it only after the
existing domain promotion gates pass. Neither is constructed by the production
plugin, and neither can promote simulation or unreviewed results.
