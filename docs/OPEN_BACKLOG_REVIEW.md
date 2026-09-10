# Open backlog review

Snapshot: 2026-09-09, main `0014b70e8d851a912e749895b3201e3fef15a80f`.
The maintainer accepted the initial expanded menu and requested work on all open
PRs and issues. This record tracks repository work separately from hardware proof.

## Pull requests

There are 22 open PRs. Twenty are an unmerged experimental eGPU/audio stack;
none of their heads is an ancestor of this main, none of their substantive
patches matches main, and none of their changed files is byte-identical to main.
They must not be closed as already merged. Historical green CI is not current
integration evidence.

| PRs | Disposition and next action |
| --- | --- |
| #53 | Independent graphics-release experiment; review current trial contracts before any integration. |
| #61, #66 | Audio trial/recovery and fresh-context components; review restoration and current ownership contracts. |
| #63 | First unmerged recovery dependency; detailed code review in progress. |
| #64, #65, #67, #68 | Compiler/preparation/evidence/authentication slices; review after recovery dependencies. |
| #70, #71, #72 | Identity, inherited-resource and runtime boundaries; reconcile current scope/authorization before integration. |
| #73, #74, #78 | Persistent ownership and recovery composition; preserve rollback semantics. |
| #75, #76, #77 | Dependency checkpoint, prepared sessions and authenticated server; integrate only reviewed components. |
| #79, #80, #81 | Final checkpoint, bootstrap recovery and fixture archive; retain until prerequisite review completes. Never run mutating fixtures as ordinary tests. |
| #165 | Security owner retains draft. Snapshot hardening is distinct from unresolved loader execution authority. Owner confirmed bounded partial hardening can proceed and is running its own readiness pass; no authority change inferred. |
| #173 | Controller owner retains claim. Requested accepted transfer; review can proceed read-only. Rebuild against current main and preserve disabled display shortcut input so it cannot compete with the menu. |

Dependency spine: #60 → #63 → #64 → #65 → #68 → #72. Additional
branches feed #75/#79; #81 contains the stacked history. This is not a queue of
independent patches that can safely be merged by title or CI color.

## First implementation

Issue #179: ship an explicit allowlist containing the reviewed read-only
`probe_safe_undock_readiness.py`, with package/import smoke checks and exclusion
of deployment/mutating helpers. A dedicated worker owns an isolated worktree.
No version bump, device action, or release is included in this issue fix.

## Boundaries

Physical unplug, sleep/wake, reconnect, transport and controller compatibility
issues remain open until their own evidence is collected. Software implementation,
fixture tests and a merged PR do not satisfy those native acceptance criteria.

Documentation impact: Wiki.

## Issue dispositions

All 26 open issues were inspected at the snapshot above. An implementation
checkbox is not evidence that production calls the new component.

| Issue | Next concrete action / remaining gate |
| --- | --- |
| #16 | Identify absent-eGPU sleep blockers on an exact installed build; supervised battery/charger cases. |
| #17 | Measure transport, enumeration, driver and display discovery timing with one common starting point. |
| #18 | Prepare compatible late-shutdown capture before reproducing the attached shutdown hang. |
| #19 | Compare naturally occurring detached-boot controller failures with healthy provider discovery; do not induce hard power-off. |
| #21 | Complete native Offline Readiness Home/Library refresh, retry and focus validation. |
| #23 | Capture exact-transport Raikiri front-button events; distinguish independent actions from stick clicks. |
| #27 | Add explicit Stop automatic TV connection control; dismissal regression already merged in #217. |
| #28 | Wire merged saved-TV decision/store/search into successful docking and pending observation; add accurate waiting/settled/unobservable status. No production consumer exists yet. |
| #29 | Establish whole-dock release and wake-source evidence before sleep/resume integration. |
| #34 | Reconcile umbrella checkboxes against current child outcomes; retain unresolved controller/eGPU acceptance. |
| #51 | Reconcile recorded resource-release experiment and missing capture through #136/#161. |
| #52 | Review audio components #61/#66 and prove restoration before runtime activation. |
| #54 | Validate installed software-removal/recovery and display/audio/controller behavior; physical-unplug gate remains separate. |
| #55 | Review legacy slices in dependency order; publication alone is complete. |
| #59 | Validate merged TV-return control on device; #62 already merged. |
| #69 | Keep filtered native launch deferred unless measured holders survive current user-manager filtering/restarts. |
| #90 | Refresh phase tracker; separate GPU removal from whole-dock/physical clearance. |
| #105 | Investigate USB-branch ACS errors and peripheral effects separately from GPU removal. |
| #108 | Agree build contract after security CI changes; preserve reproducibility and stale-output refusal. |
| #136 | Capture repeatable redacted before/live/after evidence; historical operator report is not an artifact. |
| #147 | Safety owner must define post-removal physical-clearance evidence; GPU absence alone is insufficient. |
| #161 | Refresh installed revision and bounded supervised session plan. |
| #167 | Verify migrated managed drop-in produces ready display switching on device; software fix #216 is merged. |
| #178 | Already fixed by 6d562c7 in #207. Fresh 29-test restart-plan suite passes. Closed after fresh 29-test verification and eGPU reviewer coordination; Claude retains task reconciliation. |
| #179 | Implement packaged read-only probe and verify archive contract. |
| #201 | Measure post-removal transport/inhibitor and wake source before choosing a sleep-policy change. |

## Recovery slice review

PR #63 remains read-only pending Claude sequencing confirmation.

PR #63 at `384177d525de53de2cec687d81f1794c395fc78f` has eight new files;
its prerequisite modules match current main byte-for-byte. A bounded isolated
review ran 63 tests (two Windows platform skips). No production dispatcher is
added. The known crash window after retention-map unlink but before the final
journal completion write remains unresolved on retry by design: it fails closed,
and this slice does not promise recovery convergence or physical clearance.
