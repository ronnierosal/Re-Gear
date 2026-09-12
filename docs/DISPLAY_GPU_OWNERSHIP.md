# Display connector GPU ownership

This implements the read-only ownership evidence prerequisite (slice 1) from
[the display/render mode contract](DISPLAY_RENDER_MODE_CONTRACT.md).

`DisplayObservation.owning_gpu_stable_id` links a connector to the exact,
verified GPU in the same discovery inventory. `owning_gpu_confidence` grades
that link separately from connection, active output, and renderer evidence.
DRM card names corroborate membership during collection; they are not stored
as the owner's identity. EDID continues to identify the display, independently
of which GPU it is connected to.

The owner remains empty/Unknown when the GPU role or identity is unverified,
the PCI identity is absent or duplicated, card names or stable identities are
ambiguous, or the connector contradicts its parent card. Duplicate connector
names on one card also withhold ownership. The same connector name on different
cards does not by itself make physical ownership ambiguous.

Private snapshot serialization preserves this evidence, and old snapshots
default to unknown ownership. Public Decky snapshots remove the private owner
identity. The evidence participates in the existing transition observation
fingerprint, so an owner change invalidates stale observation binding.

This does not enable a Docked-iGPU destination, change placement inference,
prove cross-GPU presentation, or switch any display. It describes the current
inventory only; a later action must obtain fresh evidence. Running-game guards
and supervised hardware gates remain in force. Tests cover collection through
the real discovery service with simulated inventories, serialization, public
redaction, and observation binding. No hardware validation is claimed.
