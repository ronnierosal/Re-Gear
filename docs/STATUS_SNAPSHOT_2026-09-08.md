# Status reconciliation — September 8, 2026

This dated documentation snapshot reconciles the source and operational records.
It supplements [current state](CURRENT_STATE.md); it is not a fresh device
inspection, a release manifest, or permission to resume an old hardware procedure.

| Question | Verified source or recorded evidence | Limit |
| --- | --- | --- |
| Source baseline | GitHub main and the reviewed local commit are `5b18edfa9b99d87069057216ec6f3734abf68574`; package metadata declares 0.3.58 | Later commits must be checked independently |
| Release-line reconciliation | PR #117 integrated the 0.3.55 release lineage into main; the older README's 0.2.0/main split is obsolete | Main ancestry does not include every separate candidate |
| Reported installed version | The September 8 operator account reports 0.3.58 | No fresh installed SHA or package checksum was verified in this review |
| Resource release and software removal | The operator reported a clear holder result under a device filter, then source-driven removal/rescan | No archived before/live/after capture; scan gaps and filter lifetime remain blockers |
| Separate graphics trial | PR #82 records the 0.3.56 trial candidate | Staged, not installed or hardware validated by this record |
| Physical disconnect | Live unplug remains unsupported | Follow shutdown-before-disconnect and verify physical power-off |

The [September 8 summary](DISCONNECT_PROGRESS_2026-09-08.md) and
[engineering account](DEVICE_FILTER_RELEASE_2026-09-08.md) retain the operator's
observations and their limits. Neither a clear scan nor a Portable display is
independent evidence of safe physical removal.

The coordination and documentation workflows landed through PRs #138 and #139.
They change agent ownership and evidence handoffs, not product behavior or hardware
validation. This is a dated reconciliation record, not another rolling status ledger.

## Workstreams and continuation

Quick Access navigation, Auto TDP, and eGPU connection/release use separate
worktrees and issue claims. At this snapshot, PRs #129, #132, #122, #124, #137, and #82
remain open. This list is a dated checkpoint, not a live ownership registry.
Follow [agent coordination](AGENT_COORDINATION.md), inspect current issue claims
and changed paths, and preserve each stack's intended base before editing.

Historical directives in [the operator handoff](OPERATOR_HANDOFF.md), current-state
entries, or shared agent notes apply to their original sessions. They do not
establish today's attached/detached state, running workload, or execution approval.
Obtain fresh read-only evidence through the reviewed diagnostic path before a
separately authorized supervised operation.

## Documentation integration

`CURRENT_STATE.md` is claimed by PR #82. Its owner/integrator should link this
snapshot above the retained historical entries when reconciling that PR. This
follow-up leaves the claimed file untouched. Wiki source changes need their own
reviewed publication and readback under [the Wiki workflow](../wiki/README.md);
editing the source directory does not update the live Wiki.
