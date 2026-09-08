# Documentation cleanup inventory — 2026-09-08

This is a bounded follow-up inventory, not product work or an assertion of
current installed behavior. The original inventory inspected `e73f57d` (product
base `8de0ed4`). The reconciliation below reviewed merged main `5b18edf`.

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
