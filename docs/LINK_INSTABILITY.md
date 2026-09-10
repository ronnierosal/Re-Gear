# Link-instability evidence

Status: **Implemented (pure two-sample assessment); Hardware Validation Required**

`regear.domain.link_instability` compares exactly two supplied opaque-bound eGPU
link observations. It accepts only fresh same-binding, applicable, observed
Up/Down states. A change is `instability_observed`; equal observed states are
`stable_observed`; stale, changed, unavailable, unobserved, or Unknown facts
are `evidence_insufficient`.

The public result exposes only categorical status, code, and current Up/Down
state. It omits attachment, generation, and sample identities. Neither result
diagnoses cable quality, throughput, bandwidth, link reliability, performance,
safe removal, recovery, or certification, and it has no action authority.

There is no collector, scheduler, watcher, notification wiring, or hardware
validation in this slice. A future owner must use an existing bounded source or
a separately reviewed event-driven/measured cadence, then obtain supervised
hardware evidence before making any operational claim.
