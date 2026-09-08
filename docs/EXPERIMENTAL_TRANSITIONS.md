# Guarded experimental transitions

The existing supervised Portable-to-Docked-eGPU path now also accepts an exact,
idle Docked-iGPU source. It uses the same preview, short-lived single-use
approval, durable journal, Gamescope mechanism, verification, acknowledgement,
and interrupted-recovery flow. No production game-exit scheduler or Decky RPC
is enabled.

Docked-iGPU is also a real recovery target. Its boot-scoped config selects the
external TV connector and explicitly selects the exact internal GPU. If G1
promotion cannot verify, recovery can restore that source rather than guessing
Portable. The wrapper still falls back to the internal panel when boot,
connector, or GPU evidence is stale or ambiguous.

A bounded read-only Docked-iGPU game-exit watcher is also implemented. It binds
one exact running Steam game, brackets observations to avoid partial-order
races, and emits only a privacy-safe `promotion_ready` state after verified
natural exit. It cannot issue approval or invoke this transition path. See
[Docked-iGPU workflow](DOCKED_IGPU.md).

An unwired backend facade can pass the watch's private ready generation into the
existing supervised preview. The frontend supplies only the opaque watch ID;
generation drift blocks approval. The watch is consumed only when explicit
confirmation returns an approval token, and execution remains a separate gated
operation.

Hardware validation is a certification gate, not an implementation gate. Re-Gear
may implement an Experimental mechanism before certification when the operation
is exact, observable, bounded, recoverable, and explicitly approved for a
supervised test.

## Runtime profile resolution

The runtime registry resolves capabilities from the complete current snapshot.
It selects the Ally X host profile only from the exact host profile ID and the
GPD G1 profile only when one verified external GPU has the stable identity that
the exact G1 matcher assigned and the complete combination remains Certified.
Unknown or ambiguous evidence receives the unknown profile and no mutation
right. Resolution does not change Experimental capabilities to Verified.

The manual planner derives an ephemeral transition binding containing the exact
host/eGPU profiles and current internal/external GPU and display stable IDs.
This binding is needed by a mechanism but is excluded from the privacy-safe
transition journal and support exports. A mutating plan cannot exist without a
complete binding.

## Experimental approval

Verified capabilities need no experimental exception. An Experimental display
handoff requires a separate backend-issued permit that is:

- based on explicit user confirmation
- valid for at most two minutes
- single use
- bound to the operation, observation generation, target placement, host
  profile, eGPU profile, and ephemeral eGPU identity

The planner rejects a missing, stale, or differently bound permit. This is not
a general `allow_experimental` frontend boolean. No public RPC or automatic
attach path can currently issue or consume the permit.

The observation generation intentionally excludes only `observed_at`. Consent
therefore survives a timestamp-only refresh but not a semantic hardware, game,
session, blocker, or safety-evidence change.
The companion per-scan sample ID includes `observed_at` and is reserved for
workflows that must prove a new collection, such as process release.

## Presentation shim boundary

The plugin package contains an inactive `bin/gamescope` shim and a fixed-path
boot-scoped config store. Packaging is not activation. Only the separately
confirmed preparation RPC may install the reversible systemd override; no
public RPC can restart Gamescope, write a presentation target, or initiate an
automatic attach transition.

For a docked selection, the shim requires the config's exact external connector
and GPU vendor/device pair to remain uniquely present in the current boot. It
never chooses a GPU by DRM card order or PCI address. Invalid or stale config
falls back to a unique connected internal panel when possible and always clears
an inherited Re-Gear eGPU render selector. If a safe output cannot be selected, it
preserves the existing output arguments rather than guessing.

Future activation must be reversible, must refuse conflicts with another
user-service `PATH` override, and must remain a distinct supervised operation.
The orchestrator must still re-observe and verify the resulting placement; a
successful Gamescope exec is not transition success.

The fixed user-service command boundary derives
the target user only from the one verified Gamescope process owner and requires
the matching passwd home plus a live user bus. There is no `deck`, UID 1000, or
environment fallback. It can verify the fixed service, reload that user's unit
configuration, or queue a non-blocking restart of the fixed Gamescope target;
it cannot accept an executable, unit, path, command, or environment value from
an RPC. Decky preparation uses only daemon-reload and fixed-unit verification;
the restart operation remains behind the unwired transition mechanism.

The reversible drop-in store owns exactly
`90-handheld-dock-mode.conf`, creates only fixed descendants of the verified
user home, and never edits Valve's session script. Activation rejects modified
Re-Gear content, unsafe ownership/symlinks, unknown environment files, and any
other drop-in that can set, pass, or unset `PATH`. In particular, an installed
eGPUBridge path shim is a conflict to resolve explicitly during a supervised
test. Deactivation removes only the byte-exact Re-Gear file and leaves its bounded
state directory for recovery evidence.

The runtime presentation mechanism is implemented and simulated behind the
existing orchestrator port. It does not install its own integration: a separate
supervised action must first make the exact drop-in ready. For each attempt it
revalidates the complete transition binding and Gamescope user, reloads the
fixed user manager, verifies the fixed service, writes the boot-scoped target,
and queues only `gamescope-session.target`. If that queue operation fails, it
immediately restores the config for the still-observed source placement. The
orchestrator remains responsible for fresh placement verification and bounded
recovery after an accepted queue operation.

Integration preparation has its own approval boundary. A short-lived,
single-use token is bound to a verified Portable/idle semantic observation, the
exact Gamescope user, and the shim/drop-in fingerprint. Preparation may install
the fixed reversible drop-in, daemon-reload the exact user manager, and verify
the fixed service, but it never restarts Gamescope. Any evidence change consumes
the token without mutation. A failure after a new install removes the Re-Gear file
and reloads the user manager; failure to complete that rollback is Action
Required. Decky exposes this preparation through a controller-first
preview/confirm flow under troubleshooting details. Actual transition controls
and automatic attach remain absent.

The actual transition is exposed only as one explicitly named, controller-first
**supervised idle TV-switch test**. Its preview issues no authority; the player
must confirm a second time for the backend to issue a real short-lived permit.
Execution consumes that permit, requires the same semantic snapshot and ready
integration, rebuilds the exact plan, and enters the durable orchestrator.
Pending recovery or unacknowledged terminal evidence blocks another attempt.
The player must acknowledge the exact terminal result before a later test.

## Current hardware evidence

The integration-preparation flow has been exercised on the certified handheld
while Portable and idle. It installed Re-Gear's reversible drop-in, reloaded the
verified user manager, and left the existing Gamescope session and internal
display usable. A competing legacy eGPUBridge `PATH` override was removed as a
separate, recoverable cleanup before that preparation; Re-Gear did not overwrite the
competing file.

The first player-watched idle TV-switch attempt with a ready eGPU and TV did
**not** reach the TV. The shim safely fell back to the internal panel. Review
found that the transition mechanism had written its boot-scoped presentation
configuration into the root-only journal state directory, while the prepared
user-service shim reads the verified Gamescope user's fixed state directory.
Commit `8c721fb` corrects that path split: the journal remains root-owned and
the shim-facing launch configuration is written only to the exact prepared
user path.

This is a failed hardware acceptance result, not proof that the corrected path
works. The fixed candidate still requires a new player-watched, idle,
eGPU-and-TV-attached test with before/attempt/after evidence and recovery
observation. It remains Experimental and neither this endpoint nor preparation
authorizes automatic attach, an unattended Gamescope restart, a Docked-iGPU
handoff, sleep, or removal.

This is not an automatic attach path: it is unavailable when a game is running
or unknown, and it does not authorize a Docked-iGPU handoff, live removal, or
any sleep action. The player must watch the handheld screen for the one
Gamescope restart and stop the test on a black display, lost controls, or lost
network access.

## Certification boundary

An approved Experimental plan authorizes one controlled attempt after the
runtime orchestrator and mechanism are available. It does not mark the result
Verified or Certified. Promotion still requires the intentional hardware
review rules in [Hardware support](HARDWARE_SUPPORT.md) and a captured
before/attempt/verification/rollback record.
