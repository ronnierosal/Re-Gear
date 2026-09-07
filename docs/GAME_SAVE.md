# Verified game-save child

Re-Gear is save-aware; it does not claim universal autosave. A catalog label or a
successful mechanism call is never enough to tell the player that progress was
saved.

## Authority boundary

The guarded save child can prepare only while the canonical sleep transaction
is in its consented `closing_game` step and the capability bound when that
request began is `verified_triggerable_autosave`.

Preparation requires all of:

- one exact active Steam AppID and bounded exact scope set
- the exact host and eGPU profiles bound by the parent sleep request
- one backend-owned recipe matching that AppID/profile tuple
- an intentional, reviewed hardware-evidence identity for the recipe
- an exact independent save-proof baseline

The recipe registry, proof source, and mechanism are narrow injected ports.
They do not accept a command, path, key sequence, AppID, recipe ID, or proof
claim from the frontend. A future production registry must contain only
reviewed game-specific recipes; similarity or passive telemetry cannot create
one.

Consent to close the running game is also consent to attempt its verified save
recipe. The child still issues a short-lived, single-use internal execution
token so authority cannot survive changed game, proof, profile, recipe, or
parent-operation evidence. It does not require a second player dialog on the
happy path.

## Execution and verification

Execution follows:

```text
fresh exact game + unchanged recipe + fresh unchanged proof baseline
    -> persist identity-free substep_started
    -> request the typed save recipe
    -> poll fresh game and proof observations inside a deadline
    -> require a new proof generation with state Verified
    -> persist substep_verified
    -> unlock graceful close for the same sleep request
```

Changed/unknown game identity, changed proof before the attempt, missing or
changed recipe, mechanism refusal, wait/rescan failure, proof timeout, journal
failure, or parent rejection fails closed into Action Required. Mechanism
acceptance is not save proof.

Steam AppID, scope names, recipe/evidence/profile identity, approval tokens,
proof values, commands, and paths never enter the transition journal.

## Current boundary

The pure contracts, approval store, guarded application service, canonical
sleep gate, proof-verification loop, journal composition, privacy tests, and
capacity tests are implemented and simulated. There is no production recipe,
recipe registry, game-specific proof adapter, save mechanism, Decky RPC, or
hardware-verified game entry. Therefore this code cannot currently trigger or
claim a real save.

Every future recipe requires its own intentional supervised validation on the
exact game, Re-Gear version, SteamOS version, host profile, eGPU profile, and game
version where relevant.
