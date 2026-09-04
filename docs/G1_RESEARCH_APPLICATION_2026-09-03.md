# G1 research application — 2026-09-03

## Active mission and current evidence

Improve the exact Ally X/GPD G1 attach, TV/audio, Portable return and reconnect
journey. Preserve the known-good Gamescope selector path and shutdown-before-
disconnect boundary. This review made no remote changes or hardware transitions.

Installed build `1981259840ce` was observed with only the internal GPU before
later reporting the external GPU and a connected, inactive TV. The saved
`capture-20260904T014056Z.json` reports Steam and Gamescope running, internal
display active, and external display inactive. Its unprivileged render-selector
and client evidence is incomplete; its standalone sleep-guard status does not
describe the Decky-owned inhibitor.

Bounded plugin journal inspection found this sequence (timeline-relative ms):

- `topology.egpu_attached`: 433386
- `attach.ready_stabilizing`: 433674
- `attach.ready_idle`: 434537
- `connection.tv_transition_started`: 434538
- `journal.acknowledgement_required`: 434572

Exact attach to request took approximately 1.15 seconds in this log sequence.
The request was rejected by the journal gate, not proven to have restarted Steam.
These timestamps do not establish the physical insertion time or explain the
earlier enumeration delay. The current journal's exact prior outcome has not yet
been inspected; do not assume it was successful or automatically discard it.

## Reference review and disposition

Reviewed Cardwire at `db92fe8540aecdf9860df087485666a03b0c00ad`:

- [Display monitor](https://github.com/OpenGamingCollective/cardwire/blob/db92fe8540aecdf9860df087485666a03b0c00ad/crates/cardwire-daemon/src/tasks/monitor_display.rs)
  coalesces DRM events, settles for 250 ms, reconciles every five seconds with
  skipped missed ticks, and separates persisted intent from temporary overrides.
- [DRM node resolution](https://github.com/OpenGamingCollective/cardwire/blob/db92fe8540aecdf9860df087485666a03b0c00ad/crates/cardwire-daemon/src/core/gpu/display.rs)
  resolves initialized card/render nodes under the exact PCI parent with bounded
  retries. Its `is_gpu_active` uses connector-connected evidence, not active pixels.

HDM already has a fresh-observation readiness watch, four stable ready samples,
and separate desired/observed state. Do not replace its stronger output/render
postconditions with Cardwire's connected test. No external source code was copied.
An event-driven wakeup/coalescing adapter is a future measured improvement, not a
justification to replace the observer or add blocking retries inside discovery.
The observed journal rejection is independent of event-monitor latency.

Other-chat findings about boot_vga bind mounts/display-manager restart and
NVIDIA-specific PCI/module overrides are reference-only, not implemented or
independently validated here. None establishes safe G1 removal or resolves the
shutdown/controller anomaly.

## Implemented locally: preserve intent through partial enumeration

Code review found `AutomaticDockCoordinator.update` cleared its one-shot latch
whenever the exact eGPU profile was unavailable. A temporary unknown identity
could therefore re-arm a request or undo the hold established after Portable
disconnect preparation. This is a reproduced policy defect, not a proven cause
of the current hardware failure; downstream journal gates can still block it.

The latch now clears through observation only when the host is exact, profile
resolution reports absence, and no link, disconnect-client, or sleep-presence
evidence remains. Explicit opt-out and owner acknowledgement paths are unchanged.
This classification is not authorization for physical removal.

Regression coverage exercises partial GPU identity, transport-only evidence,
client evidence, sleep-presence evidence, unknown host and missing GPU inventory,
for both a consumed failed attempt and Portable-return suppression. Existing
tests retain ordinary absent/reconnect and explicit re-arm behavior. The new
partial-GPU cases failed before the fix and pass afterward.

## Next decisions / backlog

- Inspect the exact pending journal outcome before choosing acknowledgement or
  any narrower automatic successful-result finalization rule. The current code
  requires acknowledgement for all terminal presentation outcomes, including
  success. Do not change this by deleting journals, blanket-clearing on startup,
  or retrying repeatedly. Preserve failed/interrupted/foreign operations and
  Portable-return suppression across any future completion change.
- Add finer bounded PCI/driver/DRM stage diagnostics before claiming a cause or
  optimization for delayed enumeration. Existing journey logs now distinguish
  readiness delay from the journal gate in this session.
- Measure observer cost before event-driven reconciliation work. Events should
  prompt fresh evidence, never authorize a transition directly.
- Repeat supervised attach, audio both ways, return and reconnect on a packaged
  candidate. Local tests do not certify any new hardware behavior.

## Verification

Targeted automatic-dock, attach-readiness and supervised-transition tests passed.
Final backend gate: 839 tests ran successfully with five skips; architecture,
compileall and diff checks passed. This change is not installed, packaged or
hardware-tested.
