# Safe Undock result presentation

Status: **Implemented (pure contract); Hardware Validation Required**

`regear.domain.safe_undock_presentation` converts only a Stage 1.5
`SafeUndockReadiness` result into a human-facing category. It has no operating
system access, action dispatch, persistence, timer, or device-control path.

The categories are deliberately narrow:

- `evidence_insufficient` — the latest readiness evidence cannot support a
  decision.
- `not_ready` — the observed condition does not meet the Safe Undock gate.
- `revalidate_required` — an acknowledgement is absent, Stage 1.5 invalidated
  the result, or the attachment binding, generation, or sample no longer
  matches.
- `eligible_for_supervised_physical_validation` — a human acknowledged a
  matching, fresh revalidation token. This is only eligibility to begin a
  separately approved, supervised physical-validation procedure.

The last category never means “safe to unplug,” does not start a physical
operation, and does not certify hardware. The supervising operator must rerun
Stage 1.5 immediately before any later physical test and present the matching
new revalidation token with an acknowledgement. Any missing, stale, or changed
token returns `revalidate_required`.

The contract intentionally preserves the independent Stage 1.5 checks for game
state, exact attachment, topology, client scan, display, render GPU, audio, and
controller facts. It does not reinterpret those facts or provide a bypass.
