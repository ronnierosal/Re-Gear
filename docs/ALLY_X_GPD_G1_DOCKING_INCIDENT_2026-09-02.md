# Ally X and GPD G1 automatic docking incident

> Historical record: HDM was Re-Gear's former name; original wording is retained.

**Date:** 2026-09-02<br>
**Hardware:** ASUS ROG Ally X, GPD G1 (RX 7600M XT), TV connected to the G1<br>
**Outcome:** automatic TV picture and external rendering hardware validated once;
direct TV-audio selection hardware validated; automatic audio handoff remains
implemented and simulated pending installation and a watched cycle

This record explains the multi-stage failure that initially looked like “HDM
does not see the G1.” It is a diagnostic record, not a certification statement.
Current capability and deployment truth remain in [Current state](CURRENT_STATE.md).

## Player-visible symptoms

The session exposed four distinct symptoms in sequence:

1. HDM reported that the eGPU link needed verification even though the G1 was
   connected and its TV input was selected.
2. After exact G1/TV evidence became available, automatic docking stopped on a
   journal acknowledgement that no visible workflow could acknowledge.
3. Later attempts restarted Gamescope: the Ally panel went dark briefly and the
   TV detected a signal, but the TV stayed black and HDM recovered to the Ally.
4. After the TV transition succeeded, Steam appeared on the TV and rendering
   used the RX 7600M XT, but audio initially remained on the Ally.

These symptoms did not share one root cause. Fixing detection alone could not
fix journal routing, launch authorization, file access, or audio routing.

## The evidence boundary that mattered

A DRM connector with status `connected` proves only that a display is attached.
It does not prove that Gamescope is scanning out to that display. Likewise, a
USB4 device proves neither an exact G1 topology nor a usable external GPU.

The successful transition required one fresh, internally consistent observation
containing all of the following:

- exact Ally X host profile;
- exact GPD G1 profile, including its required bridge, GPU, and audio functions;
- authorized USB4 topology and an observed-Up link;
- exactly one EDID-ready external display;
- known Gamescope state;
- Idle game state;
- no foreign or unresolved transition journal.

After restart, success required live evidence that the TV was active, the Ally
panel was inactive, and the external GPU was selected. The black-TV attempts
failed this postcondition and therefore correctly recovered to Portable.

## Root-cause chain and fixes

### 1. SteamOS PCIe link evidence was rejected

SteamOS exposed negotiated link width in a valid bare form that the parser did
not accept. HDM consequently kept link readiness unknown and failed closed.

Commit `f7d0bf2` accepts the observed representation while retaining strict
validation. This enabled exact profile readiness; it did not by itself authorize
a display transition.

### 2. Automatic docking did not yet invoke the proven transition mechanism

The useful eGPUBridge behavior was the launch sequence, not its architecture:
select the exact output and GPU for the next Gamescope session, restart
`gamescope-session.target`, then verify the resulting live state. HDM integrated
that mechanism behind its existing transition, rollback, journal, game-state,
and exact-profile gates.

Commit `898d9c8` added an off-by-default automatic coordinator and a manual
fallback. It tolerates USB4 enumeration settling but submits only once per
attachment and only after complete exact evidence becomes ready.

### 3. A shared terminal journal was attributed to the wrong owner

The coordinator found a terminal shared journal and displayed a generic
acknowledgement requirement. Both the presentation and process-release services
reported that it belonged to another workflow, so the UI could not provide the
correct action. Deleting or bypassing the journal would have violated recovery
and audit guarantees.

Commit `7227e73` added categorical journal ownership, exact-owner
acknowledgement, honest foreign-workflow labeling, and coordinator re-arming
after acknowledgement. The owner routing and retry were observed on the Ally.

### 4. Writer and Gamescope shim calculated different launch bindings

The root service wrote the launch config with a binding derived from the raw
boot ID and exact G1 identity. The Gamescope-side shim instead combined an
already-hashed boot ID with the G1 identity. Those values could never match, so
the shim safely ignored the external target and selected the internal panel.
That produced the characteristic sequence: Ally panel dark, TV signal present
but black, then verified Portable recovery.

Commit `22e1944` keeps the raw boot ID only in memory for private binding
revalidation and serializes only its SHA-256 value. A writer-to-shim regression
test covers the formerly mismatched calculation.

### 5. The Gamescope user could not read the root-created config

The next supervised attempt still selected the internal panel. The binding and
unprivileged hardware revalidation now passed, which isolated a second launch
failure: `presentation.json` was root-owned with mode `0600`. Gamescope runs as
the `deck` user, could not read the file, and correctly behaved as though no
external launch target existed.

Commit `0d66127` writes this bounded, identity-minimized launch config as
root-owned mode `0644`. It contains no raw boot ID or stable G1 identity, and
the shim must still revalidate exact live hardware before using it.

With `0d66127` installed, a watched attach succeeded: the TV became the only
active display, Gamescope selected the RX 7600M XT, Steam was visibly present on
the TV, and the presentation journal committed.

### 6. Display success did not imply audio success

The installed display build had no live PipeWire handoff, so the internal
SteamOS loopback sink remained default. Read-only inspection associated the
G1's exact HDMI-audio PCI function with one external SteamOS loopback sink. On
this SteamOS version `wpctl set-default` accepted the current numeric PipeWire
node ID, not the stable sink name. That ID is transient and must never be stored.

A supervised, freshly resolved numeric-node selection moved sound to the TV,
and the player confirmed it audibly. Commit `80bd8d4` converts that proof into a
guarded child of the presentation transition:

- capture the current Portable default in root-only state before attach;
- revalidate the exact G1 topology and derive its audio PCI function;
- use `pw-dump` to resolve exactly one matching SteamOS loopback sink;
- pass only its freshly resolved numeric node ID to `wpctl`;
- switch only after the Gamescope restart is durably queued;
- verify the new default with bounded retries;
- restore the captured Portable sink on presentation rollback or return.

Missing rollback state, ambiguous sinks, changed G1 evidence, command failure,
or failed verification remains fail-closed. The automatic path is locally
tested but was not installed during this record; only the direct supervised TV
selection has hardware proof.

## Verification performed

The display-success build was installed with the G1 disconnected and exercised
through one watched attach. Player-visible TV output, active-display evidence,
external render selection, and a committed journal agreed.

For the guarded audio change at `80bd8d4cfd6665387e806a548cfa040d508a5bd9`:

- architecture check passed;
- 788 backend tests passed, with 5 expected Windows symlink skips;
- Python compile check passed;
- TypeScript typecheck passed;
- 64 frontend tests passed;
- Rollup and package checks passed;
- clean package metadata embedded the full source revision.

Those checks establish implementation and simulation evidence, not automatic
audio hardware validation.

## Reusable diagnostic method

When a future system reports “connected but not docked,” find the earliest
divergence instead of repeatedly restarting or broadening permissions:

1. Record the installed build identity. A ZIP name is not provenance.
2. Separate USB4 presence, exact eGPU identity, link readiness, connector
   readiness, active output, render GPU, game state, and journal ownership.
3. Inspect the transition stage and first public failure code.
4. If the TV reports signal but stays black, inspect what the new Gamescope
   process actually selected. Do not infer activity from DRM connection.
5. Validate a launch handoff end to end: writer input, serialized config,
   ownership/mode, reader access, binding calculation, and live revalidation.
6. Treat audio as an independent transaction. Resolve ephemeral PipeWire IDs
   immediately before use and preserve a verified rollback target.
7. Confirm recovery on the Ally before another attempt.

Do not solve a failed handoff by hard-coding DRM card numbers, connector
suffixes, PCI bus addresses, or PipeWire node IDs. Do not delete an unknown
journal or allow the Decky UI to supply a command target.

## Safety and remaining work

- Installation, Decky restart, and Gamescope restart are performed only in the
  supervised workflow. Do not install a new build with the G1 attached.
- Physical G1 removal is not live-safe. Shut down, wait for the fan to stop,
  then disconnect; charging LEDs alone are not proof that the Ally is running.
- Automatic TV audio and exact Portable-audio restoration still need one
  watched hardware cycle using the guarded audio build.
- The cold-start built-in-controller failure was observed but deliberately
  deferred so it would not be conflated with the G1 display incident.
- Repeated connect, return, shutdown/disconnect, sleep/recovery, reconnect, and
  gameplay cycles remain required before the end-to-end journey is certified.

## Follow-up: observed idle live pull and native recovery

A later player-directed test physically removed the G1 while the successful TV
Docked session was idle. HDM did not authorize the pull. The external DRM path
disappeared immediately, the Ally panel backlight returned with a black image,
and Gamescope and Steam were absent while the operating system, SSH, and Decky
plugin remained responsive. The post-loss snapshot retained incomplete
USB4/PCI evidence, so the G1 profile correctly became Unknown rather than
claiming verified removal.

SteamOS then relaunched Gamescope on the internal panel and restarted Steam
without an HDM mutation. The observed interval from connector loss to the new
internal Gamescope session was approximately 80 seconds. The player confirmed
that the Steam interface and built-in controller worked after recovery.

This is useful recovery evidence, but it is not proof that G1 live removal is
safe. The test did not establish clean PCIe/AER/kernel teardown evidence,
running-game survival, repeatability, audio restoration, or recovery from every
failure stage.

The follow-up implementation therefore supervises rather than races the native
path. It arms only from an exact, idle TV-Docked observation, recognizes the
specific correlated degraded interval, waits at most 120 seconds, and accepts
success only after a fresh observation verifies Portable. It does not restart
Gamescope or authorize removal. After verified Portable recovery, it may
restore only the root-captured Portable audio sink; that restoration no longer
depends on the disappeared G1 audio identity. Unknown game state, missing
internal-path evidence, uncorrelated samples, or timeout becomes Action
Required without display mutation.

Related contracts: [Safety invariants](SAFETY_INVARIANTS.md),
[Architecture](ARCHITECTURE.md), [Peripheral handoff](PERIPHERAL_HANDOFF.md),
[Roadmap](ROADMAP.md), and [Operator handoff](OPERATOR_HANDOFF.md).
