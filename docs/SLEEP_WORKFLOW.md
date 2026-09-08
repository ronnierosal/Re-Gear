# Canonical sleep workflow

The canonical sleep reducer and durable application coordinator model one
original player request without directly calling Steam, login1, display, or
eGPU mechanisms. A separate guarded game-close child now defines the exact
identity, consent, durability, mechanism, and verification boundary without a
production close mechanism. This remains an implementation/simulation
foundation, not an enabled live sleep workflow.

Steam-menu and physical-button intents enter the same coordinator. Physical
button intent is accepted only when the resolved host profile declares
interception Experimental or Verified; unknown profiles fail closed. The
snapshot adapter keeps ambiguous eGPU evidence Unknown and never treats a
missing DRM inventory or an unverified external GPU as verified absence.
The session binds the exact present eGPU identity and effective capability
profiles. An identity or host-profile change terminalizes the transaction before
the next directive; after verified removal, the bound capability policy remains
authoritative while the live snapshot proves absence and Portable recovery.

## Entry policy

- Verified eGPU absence retains normal sleep.
- A profile explicitly verified sleep-safe may retain normal sleep.
- Unknown presence, identity, game state, or required evidence keeps the device
  awake and enters Action Required.
- A running game requires explicit close consent. Unverified/manual save
  capability adds a mandatory progress-loss warning.
- A verified triggerable autosave directive is emitted only after consent and
  only from the capability bound when the request began.
- Consent denial cancels the original sleep request and keeps the device awake.

## Client and removal policy

After verified game exit, the reducer requires a complete disconnect scan:

- a game that starts during release invalidates the transition
- storage, game, protected, system, or unknown clients enter Action Required
- eligible ordinary user clients route to the separate preview/approval process
  release workflow
- clearing software clients is not removal readiness

`Safe to disconnect` requires all of:

- an exact eGPU profile with `live_removal_verified`
- a complete client/storage scan with no blockers
- an independent verified render/display removal-readiness result

The current GPD G1 profile has `shutdown_before_disconnect`; it routes to a
shutdown-first instruction and never emits `Safe to disconnect`. The original
sleep request is cancelled on that branch.

## Original-request continuation

For a future live-removal-verified profile, verified physical removal moves the
workflow to portable recovery while the handheld remains awake. The original
sleep request is emitted exactly once only after Portable placement is verified.
Out-of-order events or failed recovery enter Action Required.

Each request has a bounded deadline (15 minutes by default, one hour maximum).
At or after expiry, Re-Gear cancels the request and keeps the device awake instead
of suspending from stale consent or stale hardware evidence.

## Durable journal projection

Every coordinator stage is projected into the shared strict transition journal
and persisted atomically through its injected store before any external caller
could act on a directive. The projection binds the active step to the exact
sleep request and stage and only allows append-only progress. Verification
events for game exit, client release, eGPU removal, and Portable recovery require
a different observation sample from the active step.

On service restart, an incomplete sleep journal never resumes the original
sleep request. Work that had not begun is blocked. A started transition records
recovery as verified only when exact eGPU absence and Portable placement are
both freshly verified; all other restart states require action. Even verified
restart recovery terminates as recovery, not as a committed sleep request.

## Application coordinator status

The reducer, game-save capability vocabulary, conservative snapshot adapter,
durable coordinator, journal projection, exact acknowledgement, source
normalization, freshness rules, request expiry, and no-resume restart recovery
are implemented and simulated. The coordinator is not constructed by Decky.

Guarded process release now composes as a child of the same sleep journal in the
application/simulation layer. The backend injects the active parent identity;
graceful and force evidence cannot cross transactions, and cleared clients
advance only that same sleep request. No second authoritative journal is opened
and pre-signal durability remains intact. Decky sleep delivery is still unwired.

A dormant delivery facade now creates the request ID and binds a fresh semantic
generation entirely in the backend for Steam-menu or physical-button intent.
The frontend never supplies either value. Game-consent grant/deny and cancel
operations must match the opaque active operation ID; status/result payloads
exclude the private request ID and observation generation. The facade can
recover and acknowledge only through the canonical coordinator. It has no
Decky RPC and cannot execute a directive or continue sleep.

Guarded graceful game close also composes as a child of the same sleep journal.
The read-only adapter accepts only one exact Steam AppID and its bounded exact
scope set; ambiguity fails closed. Explicit confirmation issues a bounded,
single-use token tied to the parent sleep operation and exact game observation.
Execution requires a newer matching sample, persists an identity-free
`substep_started` before the injected mechanism, polls to a verified Idle state,
persists `substep_verified`, and advances only the same sleep request. Identity
change, timeout, mechanism refusal, observation failure, or wait failure enters
Action Required. AppID and scope identity never enter the transition journal.

For `verified_triggerable_autosave`, a separate guarded save child must complete
first. It binds an internal single-use token to the same sleep parent, exact
game/profile-specific reviewed recipe, and fresh independent proof baseline. It
persists before the injected mechanism and unlocks close only after a new proof
generation reports Verified. A mechanism success is never treated as save
proof. No production recipes, proof adapters, mechanisms, or Decky delivery are
wired. See [Verified game-save child](GAME_SAVE.md).

Deterministic integration replay now drives the real coordinator, guarded game
close, and guarded process-release services through one in-memory journal. The
data fixture covers the complete ordered flow plus partial ordering, bounded
request and game-close timeouts, stale child observations, unexpected unplug,
controller/display loss, and restart recovery failures. Asynchronous topology
events remain policy-only inputs: they can request recovery but cannot advance
or continue the canonical sleep transaction. Replay assertions inspect only
categorical codes and journal events; process, game, scope, and hardware
identities remain outside the journal.

There is still no production game-close mechanism adapter, game-specific save
recipe/proof/mechanism adapter, removal mechanism, sleep-continuation adapter,
physical-button interception adapter, or Decky sleep workflow RPC. Current
login1 and Steam preflight behavior remains governed by the existing sleep
ADRs.
