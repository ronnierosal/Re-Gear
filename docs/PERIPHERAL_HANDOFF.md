# Controller and audio handoff foundation

Re-Gear treats controller and audio handoff as child work of the authoritative
transition transaction. They are not a second mutation engine.

## Current implementation boundary

R7a implements a pure, delivery-independent planning foundation:

- schema-versioned controller/audio observations
- one semantic generation plus an independent per-scan sample ID
- independent complete and exact identity gates for controller and audio
- private opaque controller and audio-output bindings
- categorical blockers and privacy-safe public traces
- a composite ordered plan in which every step requires fresh verification

R7b adds a bounded read-only SteamOS sysfs inventory for gamepad-capable input
nodes and sound cards. It hashes node paths into private opaque bindings and
retains no names or paths. By default every controller identity remains
unmapped and audio's current default output remains unobserved, so the adapter
cannot authorize a handoff. A mapping can be supplied only as explicit,
intentional, reviewed supervised-hardware evidence bound to the complete opaque
inventory fingerprint. Any inventory change makes that mapping stale for both
subsystems. Even a current mapping never claims input verification or
audio-output verification.

The adapter hashes the complete private inventory into a semantic generation
and issues a distinct sample ID on every collection. Timestamp-only collection
does not invalidate a plan, but any candidate, mapping, completeness, or
categorical-error change does.

R7c adds one narrow live audio mechanism as a child of the already approved
presentation transition. It is limited to the exact Ally X + GPD G1 profile and
does not accept a sink name or numeric node ID from Decky. While Portable, the
automatic-dock owner records the current PipeWire default sink in root-only
private state. At transition time the adapter freshly revalidates the complete
G1 topology, takes its exact HDMI-audio PCI function, resolves the single
SteamOS loopback sink attached to that function, changes the ephemeral numeric
node ID, and verifies PipeWire's current default. A missing portable rollback,
ambiguous sink, changed G1 identity, unavailable command, or failed verification
stops the transition. Audio changes only after the journaled Gamescope restart is
durably queued, so an interruption enters the existing source-placement recovery
path. Controller mutation remains unavailable.

The host audio-handoff capability remains Experimental until automatic docking
and Portable restoration both pass a watched hardware cycle. The direct
supervised G1 HDMI selection is hardware exercised; deterministic tests cover
identity failure, ambiguity, selection, rollback, and restoration.

A pure logical-action router now maps a future controller Safe Undock chord,
Decky action, or device-button action to the same typed `UNDOCK` request intent
with only the delivery source differing. It has no Decky route, hotkey listener,
transition executor, or mechanism authority. Performance-profile actions remain
explicitly unavailable rather than being misrouted into an undock request.

The pure shortcut policy now defines the default Safe Undock chord as holding
**Guide + Y** for 1.2 seconds. It accepts only delivery-provided verified input
evidence and an exact chord, then emits the same logical action routed above.
It has no input listener, device binding, Decky RPC, or detach authority. The
implemented dormant delivery relay accepts only an already verified opaque event
ID, remembers a bounded set of matched events, and calls one injected logical-
action sink at most once. It cannot listen for input, bind a controller, create
a transition, or retry an uncertain dispatch. A future platform adapter must
still verify/debounce physical events and bind that sink to the canonical request
facade; this relay cannot create a parallel Safe Undock path.

The separate presentation contract exposes only categorical readiness for that
future chord: delivery-not-connected, awaiting verified input, input mismatch,
or later request revalidation. It intentionally omits opaque event identity and
does not imply that Re-Gear owns, listens to, disables, or remaps a controller. See
[Controller Safe Undock presentation](CONTROLLER_SHORTCUT_PRESENTATION.md).

The optional troubleshooting overlay can request a separate identity-free
status payload. It displays only mapped/unmapped state and categorical evidence
codes; it never receives private bindings, inventory paths, device names, or
handoff controls.

## Ordering and recovery rules

Dock plans order eligible work as:

1. promote the exact external controller
2. select the exact external audio output
3. optionally suppress the built-in controller

Suppression is omitted unless external input, built-in input, and the exact
built-in restore path are verified. A future executor must observe and verify
each preceding step before advancing; a static plan is never proof that a
change succeeded.

Undock plans order eligible work as:

1. restore the exact built-in controller
2. promote it to primary input
3. restore the exact portable audio output
4. optionally disconnect or power off the external controller

External-controller power-off is used only when independently Verified. It may
fall back to disconnect only when that separate capability is Verified.

One subsystem may expose safe work while another has a non-destructive blocker.
Such a plan is `partial`, not fully `ready`. An incomplete or inexact subsystem
produces no steps for that subsystem. Stale shared evidence, a repeated sample,
or a changed semantic generation produces no steps at all.

## Privacy boundary

Bindings exist only in the private plan. The public trace contains schema,
status, direction, typed step codes, and blocker codes. It omits bindings,
generation, sample ID, device names, addresses, paths, account identity, and
audio node identity.

## Required follow-on

1. Add fixture parsers for SteamOS input/audio variants and a separate,
   controller-visible supervised mapping workflow. Persisted mapping use must
   remain private and require fresh inventory matching.
2. Add controller chord delivery only as an adapter to the typed logical-action
   router/canonical request facade; it must never implement a parallel Safe
   Undock path.
3. Re-plan from the same semantic generation and a new sample immediately
   before each step.

## Deterministic execution foundation

The planning layer now has a dormant injected runner for a future unified
transition child. It accepts only a complete `Ready` plan, revalidates the same
plan with a new sample before every step, requires a separate fresh verification
after every apply, and reverses only already verified steps in reverse order on
failure. Changed plans, stale samples, mechanism rejection, unavailable ports,
or unverified rollback end in Action Required rather than claiming recovery.

The generic runner still has no production wiring and remains simulated. The
profile-specific PipeWire child is wired only through the authoritative
presentation mechanism; it does not create a second request path or expose a
Decky audio RPC. A future general peripheral integration must add durable child
substeps and independently verified controller support.
4. Execute one typed step through the shared transition journal.
5. Observe and verify the exact target.
6. On failure, restore the exact rollback binding and verify recovery.
7. Add privacy-safe diagnostics before supervised hardware experiments.

Implementation and simulation do not verify controller ordering, built-in
suppression, Bluetooth disconnect/power-off, automatic TV audio selection, or
portable audio recovery on physical hardware. Direct supervised TV audio
selection has one player-confirmed proof on the certified profile.
