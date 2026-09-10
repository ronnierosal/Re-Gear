# Documentation reconciliation and follow-ups — 2026-09-08

## Latest source review

Ronnie requested a generic overall-project README, detailed module Wiki guides,
future actual Command Center screenshots, and consistency with internal notes.
This review uses merged main `de90cd412885c7069a19823de68dbc3e3c770db6` (0.3.58).
GitHub source and PR states were checked on September 8. No device was contacted;
no installed build, archive or new hardware result is verified here.

README now summarizes the project and links feature guides. The Wiki explains
Command Center, eGPU/docking, power, controllers and Offline Readiness. Internal
PRODUCT/ROADMAP statements saying Offline has no collector/UI or that power
delivery is only isolated work are reconciled against current source. Older
operator and device reports remain dated history, with a current navigation note.

### Evidence reviewed

| Work | Verified source / PR | Documentation disposition and limits |
|---|---|---|
| Hub foundation, coordination and publication | #138 / `227cb81`, #139 / `5b18edf`; current AGENTS and DOCUMENTATION_WORKFLOW | Contributor workflow links; no player capability promotion. Covers hub-foundation, coordination-hardening and coordination-publication |
| Holder scan | #137 / `5591a7a` | Merged-source correction in Wiki; historical clear scans retain gaps. Covers egpu-holder-scan-evidence |
| Active display grading | #142 / `9c49bc6` | Active-state evidence must be fresh; device reachability #143 remains. Covers egpu-display-active-grading |
| Quick Access navigation | #129 / `ed47965` | Existing navigation merged; complete Command Center remains in development. Covers qa-section-wiring |
| Removal plan revalidation | #145 / `5c218be` | Merged implementation; no independent hardware promotion. Covers egpu-plan-revalidation-contract |
| Removal tool | #148 / `547d095`, incorporating #122 | Operator software-removal source exists; runtime/player path #146 remains open. Covers egpu-removal-tool-landing |
| Filter ownership record and retirement | #150 / `7c29bc8`, then #155 / `de90cd4` | Duplicate model was removed; existing filter stack still needs integration. Covers egpu-filter-ownership-record and egpu-retire-duplicate-ownership |
| Interrupted removal record | #152 / `6410250` | Pure model and storage port, not durable adapter/runtime completion. Covers egpu-removal-transaction-record |
| Gyro research | #154 / `62dc3dd`, open and unmerged | Public guide labels research only. Working-support/detail promotion deferred until reviewed implementation and exact-device evidence; continue through #154. Covers controller-gyro-compatibility |
| TDP and Auto TDP | #49 / `0ded4cd`; `main.py` RPCs and `src/index.tsx` controls | Implemented development source; #132 guard changes remain open, provider/device acceptance pending |
| Offline Readiness | `main.py`, `src/offline-confidence.ts`, `src/offline-confidence-session.ts`, `src/offline-test-memory.ts`, `src/offline-readiness-panel.tsx`, focus/badge delivery | Current confidence labels and session-limited player attestation documented; no automatic offline test or launch guarantee |

### Remaining owner integration and evidence gates

- **CURRENT_STATE.md:** open PR #82 owns this file. Its historical content is
  preserved. Owner/integrator follow-up: add a short opening link to this review
  and [the earlier snapshot](STATUS_SNAPSHOT_2026-09-08.md), explicitly saying the
  retained dated entries do not establish current installation. INDEX and
  OPERATOR_HANDOFF provide that navigation in the meantime. No ownership transfer
  or completion of this follow-up is claimed.
- **Build and live disconnect:** #116, #146, #147, #143, #136 and #105 remain
  separate integration, contract or device-evidence gates. No documentation
  change turns merged components into safe live physical unplug.
- **UI and screenshots:** #153 is a draft foundation; #144 is the asset proposal.
  Real Command Center screenshots await native implementation and validation.
  The README reserves a comment location; no invented screenshot is published.
- **Controller research:** #154 and the existing rumble/LED/player-order hub
  tasks continue under their owners. Source API possibilities are not installed
  support; the Wiki states the boundary without publishing internal inbox text.

### Additional requested documentation scope

Dedicated Ally X/GPD G1 and Raikiri II troubleshooting guides use the repository
template and link original evidence. Raikiri PC-mode source/activation leads are
not promoted to repeatable SteamOS menu-delivery proof. Public prose uses Re-Gear;
the installed directory compatibility note and exact historical paths remain.

The [identity migration plan](IDENTITY_MIGRATION_PLAN.md) is documentation-only here;
repository implementation is now authorized in a separate task/worktree/PR. GitHub API
confirmed v0.3.57 and v0.3.58 development-candidate releases (their prerelease flag
is false, so the flag alone is not a readiness signal). This corrects any broad
“no public release” wording without claiming general availability. Ronnie reports only his own recent legacy test installs; the plan uses a clean
cutover with one controlled supervised migration/rollback check. No runtime identity,
package layout, script, artifact or installed system changed.

### Verification and publication record

This file records source review, not its own future merge or Wiki publication.
The `docs-project-consolidation` hub task and associated documentation PR hold
the final check results, source revision, separate Wiki commit and readback.
The previous Wiki head was `21052c2`; direct Git comparison found one substantive
source/publication mismatch: Offline Readiness's source-review link still used
an older development branch. Web search returned cached older pages, so direct
Wiki Git readback is required before claiming synchronization.

The review covers the 12 completed engineering items listed above. No public
Discussion announcement is needed for this consolidation. Historical completed
task notes remain immutable; this linked review records the current disposition.

## Historical cleanup inventory

The sections below preserve the earlier pass and its original findings. Statements
about then-pending cleanup/publication are historical; current dispositions are
above and in the linked hub/PR evidence.

## Reconciliation pass — September 8

Ronnie assigned the documentation owner to take over the existing reconciliation
scope. Its unpublished draft was reviewed and adapted in a separate cleanup
worktree; the original checkout and PR #82's `CURRENT_STATE.md` scope are preserved.
Older draft changes to coordination rules were not imported over the merged policy.

- README now identifies the dated 0.3.58 source baseline and the reconciled main
  lineage. Archive naming follows the merged build script. Its lengthy experiment
  diary and validation table are replaced with short limits and Wiki/evidence links.
- Wiki Home/Current-State link technical evidence directly. The hardware ledger
  distinguishes operator reports from independently captured proof; a stale branch
  link now points to merged evidence. No new hardware success is claimed.
- Wiki maintenance follows the shared standing routine-publication delegation;
  obsolete future-renaming wording is removed and compatibility slugs are retained.
- The dated [source/evidence snapshot](STATUS_SNAPSHOT_2026-09-08.md) records exact
  provenance and limitations. It is a fixed reconciliation checkpoint, not a new
  rolling source of truth.

These are repository source changes. Main integration and separate Wiki publication
require recorded revisions and live readback; neither is established by this file.
Remaining follow-ups: broader module/visual presentation, the CURRENT_STATE owner's
integration, live Wiki comparison/sync, and Discussion topic inventory. No Discussion
is warranted solely by this factual cleanup. Preserve the approved UI direction in
[the Wiki plan](WIKI_INFORMATION_ARCHITECTURE.md) without implying it is implemented.

## Original findings and follow-ups

Rows below retain the original observations; the pass above records what was addressed.

| Finding | Evidence and next action |
|---|---|
| Stale release story in README | README's candidate badge/status says 0.3.55 and main 0.2.0; `package.json` says 0.3.58 and `docs/CURRENT_STATE.md` records release-line reconciliation. Recheck merged ancestry and release path, then correct the landing summary. Do not infer installation from metadata. |
| Existing cleanup draft | Workspace `docs-reconcile` on `codex/docs-reconcile-2026-09-08` already holds unpublished edits; its handoff is `docs-reconcile-handoff/HANDOFF.md`. Reuse/review with its owner; do not duplicate or overwrite it. It covers README, status/handoff docs and Wiki pages. |
| Status document ownership | The existing handoff leaves `docs/CURRENT_STATE.md` to PR #82's owner. Coordinate before edits; a chronological log is not a freshly verified deployment snapshot. |
| README/Wiki overlap | README contains placement/capability/hardware tables, transition detail and a dated September 8 resource-release section. Current-State, Confirmed-Hardware-Testing and safety Wiki guides repeat related summaries. Retain short README summaries; deeper explanations belong in Wiki, exact dated records in docs. |
| Reversed status links | Wiki Home/Current-State and `wiki/README.md` direct candidate/version details back to README. During reconciliation, point deep public guides at verified technical evidence; README remains a summary. |
| Publication drift | Repository Wiki source contains a September 8 update. The web-visible Current-State snapshot returned a September 6 update (page edited September 7). Cached web results cannot prove the current Wiki Git head: compare the separate Wiki repository before syncing. Main-repo edits do not publish it. |
| Old naming and page inventory | `wiki/README.md` still discusses a future repository rename; the repository is already Re-Gear. `WIKI_INFORMATION_ARCHITECTURE.md` describes the initial 14-guide set, while navigation has grown. `How-HDM-Works` is a compatibility slug with a Re-Gear title; distinguish legacy identifiers/history from stale public branding before renaming. |
| Module story and visuals | README already says docking is not the product boundary, but its introduction/tables remain docking-heavy. Later work should foreground the broader platform, approved imagery and module links. Record proposed visuals as mockups, not shipped screenshots. |
| UI direction | Approved Command Center / module-page structure is recorded in `WIKI_INFORMATION_ARCHITECTURE.md`. Reconcile public roadmap/module descriptions only against actual implementation evidence; no UI is built by this task. |
| Scattered release/history material | Dated `docs/RELEASE_*`, disconnect records, CURRENT_STATE, ROADMAP and Wiki Issues-Fixed contain different evidence layers. No root CHANGELOG was found. Link these sources rather than copying an engineering diary into README or creating another rolling status file. |
| Discussion inventory gap | Public Discussions index exposed Announcements, General, Ideas, Polls, Q&A and Show and tell categories, but failed to load topics. Direct #91 fetch also failed; browser tab creation was restricted. Inventory existing threads/categories in a working session before a first update; no absence-of-posts conclusion. |
| Older Wiki approval wording | `wiki/README.md` and the separate reconciliation draft contain blanket publication approval text. `AGENTS.md` and DOCUMENTATION_WORKFLOW now provide standing routine-doc delegation. Reconcile the old wording with that draft's owner during its integration, preserving the separate Wiki sync/readback procedure. |

Public inspection entry points:
[Wiki Home](https://github.com/ronnierosal/Re-Gear/wiki),
[Wiki Current State](https://github.com/ronnierosal/Re-Gear/wiki/Current-State),
[Discussions](https://github.com/ronnierosal/Re-Gear/discussions).

The shared `documentation-cleanup` task tracks this pass. Its scope is review and
reconciliation after coordination with existing owners, not hardware investigation,
roadmap promises or a license change. Refresh all time-sensitive facts before edits.
