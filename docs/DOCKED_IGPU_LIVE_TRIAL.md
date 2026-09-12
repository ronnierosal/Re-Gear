# Docked-iGPU test-build decision

Status: mechanism investigation; no live-switch candidate produced.

The requested experience is an iGPU-rendered game appearing on the TV connected
to the eGPU. Whether the game must survive the connection determines the
implementation. Game rendering and Gamescope composition must be measured
independently; a compositor GPU selector is not proof of the game's GPU.

## Verified implementation boundary

Re-Gear connector-owner evidence landed in PR #305 (`3a8cb94`). It identifies
which GPU owns the TV connector but does not add a presentation mechanism.

ValveSoftware Gamescope upstream was inspected at
`05949f8149bb5d16b006624d319a76e2433caf4c` on 2026-09-12 UTC:

- [`init_drm`](https://github.com/ValveSoftware/gamescope/blob/05949f8149bb5d16b006624d319a76e2433caf4c/src/Backends/DRMBackend.cpp#L1248-L1280)
  obtains the selected Vulkan device's primary DRM node and opens it as the
  display device.
- [`refresh_state`](https://github.com/ValveSoftware/gamescope/blob/05949f8149bb5d16b006624d319a76e2433caf4c/src/Backends/DRMBackend.cpp#L846-L862)
  enumerates connectors using that device's descriptor.
- [`setup_best_connector`](https://github.com/ValveSoftware/gamescope/blob/05949f8149bb5d16b006624d319a76e2433caf4c/src/Backends/DRMBackend.cpp#L1068-L1096)
  selects among that inventory. Its force-internal setting excludes external
  connectors; it does not open a second GPU.
- The [`GAMESCOPE_DISPLAY_FORCE_INTERNAL` handler](https://github.com/ValveSoftware/gamescope/blob/05949f8149bb5d16b006624d319a76e2433caf4c/src/steamcompmgr.cpp#L7193-L7203)
  changes the preference and requests backend reevaluation. It is a runtime
  control, but its existence is not evidence for cross-device presentation.

Inference from this code: switching an iGPU-backed Gamescope session to a TV
connector owned by a separate eGPU is not established by the existing runtime
toggle. Re-Gear's launch-only output selection is also insufficient for that
cross-device combination. This is a limitation of the inspected implementation,
not a universal impossibility claim. The installed Gamescope version and any
distribution patches still need comparison; no current device readback was
performed in this investigation.

Source credit: ValveSoftware and Gamescope contributors. Research reference
only; no upstream code has been copied into Re-Gear or packaged.

## Two distinct candidate scopes

### Preserve an already-running game

Keep game process/scope, game renderer, Gamescope process and display server
connections alive. The current restart route cannot satisfy this. The next
development milestone would be a separate compositor experiment that can attach
an eGPU display device while retaining the original renderer and internal output
as recovery. It requires cross-device frame transfer, explicit synchronization,
format/modifier compatibility, connector lifecycle and unplug/error containment.
A secondary presenter is another research option, not a proven shortcut.

Acceptance before packaging an actionable candidate:

1. Match the target's actual Gamescope build and verify whether a distribution
   mechanism already exists; do not ship a stock-upstream assumption as support.
2. Demonstrate the cross-device presentation mechanism in a Linux test harness,
   including incompatible frame formats and a vanished output.
3. Keep the original internal path available, and prove timeout/error recovery
   without terminating or replacing the game or its Gamescope session.
4. Add a bounded, confirmed trial through the shared transition engine with
   fresh connector ownership and separate game/compositor GPU evidence.
5. Produce an immutable candidate with exact source, checksum and an explicit
   supervised hardware checklist; no automatic trigger or safe-unplug claim.

This exceeds plugin wiring: the compositor mechanism is a separate architecture
and deployment milestone under AGENTS.md. Preparing a test ZIP is authorized;
replacing the installed system compositor or executing a live trial is not.

### Close and relaunch the game

This may permit Gamescope to restart on the eGPU for TV output while a newly
launched game is explicitly selected to render on the iGPU. That is a different
experiment from selecting iGPU rendering for Gamescope itself. Before coding,
identify a bounded launch mechanism, prove per-game renderer selection and
cross-device frame import, and retain existing consent/relaunch/rollback rules.
Do not silently substitute this route for uninterrupted gameplay.

## Coordination

Current worktree: `docked-igpu-trial`, branch `codex/docked-igpu-trial`.
Task: `docked-igpu-live-test-build`. The original connector-owner task is done.
The active eGPU owner retains `main.py`, release versions, architecture guards
and the disconnect trial. No edits or hardware operations crossed those claims.
Candidate integration and installed Gamescope evidence were requested through
the shared inbox; neither delivery nor silence grants an interface transfer.

The active owner replied on 2026-09-12 UTC (hub message
`a7269c764bdd486ab34defc4a7d3b15c`): no recorded installed Gamescope version or
custom patch establishes this path. Existing device evidence covers idle
session restart and TV picture/audio/controls only. Release and runtime claims
remain with that owner. No device was contacted for the reply.

## Concrete proposed first experiment: local TV mirror

This is a proposal requiring the display-mechanism milestone decision in
AGENTS.md, not an implemented or certified capability.

When built with PipeWire, Gamescope
[initializes a Video/Source stream](https://github.com/ValveSoftware/gamescope/blob/05949f8149bb5d16b006624d319a76e2433caf4c/src/pipewire.cpp#L669-L744).
GStreamer's [kmssink](https://gstreamer.freedesktop.org/documentation/kms/index.html)
can present frames on a selected DRM connector and accept a supplied DRM file
descriptor. These are two component capabilities; their combination on the
target handheld/eGPU has not been demonstrated. GStreamer contributors and
kmssink author Victor Jaquez are research references; no code was copied.

Proposed behavior for the first trial:

- An explicit confirmed start acquires frames only from the exact current
  Gamescope PipeWire stream and presents them locally on the verified TV.
- The game and its renderer remain untouched. The handheld display remains
  active as recovery; this trial mirrors rather than disables the panel.
- Input stays with the original gaming session. TV audio, HDR, VRR, resolution
  optimization and automatic connection triggers are outside the first trial.
- A short lease bounds the helper lifetime. Stop or timeout ends only the owned
  presenter; it never restarts Gamescope, signals the game or removes the eGPU.
- Before starting, verify the installed capture/sink dependencies, exact stream
  ownership, DRM ownership and connector identity, absence of conflicting
  transitions, and the game/compositor generations. Unknown evidence refuses.
- Do not launch a sink against an arbitrary card or the driver's default GPU.
  Bind a verified descriptor and connector, recheck before acquisition, and
  preserve the prior TV mode for bounded recovery.
- Cap queues and measure frame age; stop on sustained stalled delivery. The
  experiment must disclose measured latency before any regular-use claim.

Software gates: integration tests for the real helper lifecycle and command
boundary; substituted stream/device, stale generations, absent dependencies,
second-start collision, sink failure, timeout and cancellation; no signal to
the original game/session; private identifiers excluded from public output.
Linux dependency/capture tests precede packaging. Hardware gates then require
watched before/live/after render activity, unchanged game/session identity,
visible moving TV frames, input continuity and verified stop/recovery.

The first artifact would therefore be an explicitly supervised **local mirror
trial**, not a native Gamescope cross-device switch. Its approach must be
accepted before adding a new display writer or publishing an actionable ZIP.
