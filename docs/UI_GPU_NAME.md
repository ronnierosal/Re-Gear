# Dynamic GPU presentation

The optional `model_name` originates only from the existing DRM card's
`device/product_name` attribute. This is a bounded read during the existing
inventory scan, not a new polling loop or subprocess. Kernel documentation:
https://www.kernel.org/doc/html/v6.11/gpu/amdgpu/driver-misc.html

Missing, unreadable, invalid, non-printable, placeholder, or oversized names
produce an empty string. Drivers/cards without this optional attribute therefore
show `eGPU`; there is no bundled model lookup or enclosure-brand inference.

The field passes through GpuObservation and snapshot serialization as optional
presentation data. Old snapshots remain accepted. It does not participate in
GPU equality, identity, support, inference, readiness, or transition decisions.
Default domain serialization excludes it, keeping transition generations/sample
hashes unchanged. Only application snapshot reporting opts into presentation data.
The public payload still excludes executable hardware IDs and stable IDs.

The live UI selects a name only when fresh evidence has exactly one present
non-internal candidate, classified external with verified identity. Failed,
stale, disconnected, ambiguous, or unnamed evidence uses `eGPU`. Both the popup
and quick readiness panel consume the same live store. Popup detection/footer
copy is generic, never a hard-coded dock model. React renders names as text.

This does not promise that every driver supplies a marketing model name or
that a detected model is certified. Actual Ally name availability remains
unverified; no hardware access, installation or release was done for this change.
