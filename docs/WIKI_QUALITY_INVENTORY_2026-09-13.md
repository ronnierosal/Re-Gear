# Wiki quality inventory — 2026-09-13

This bounded inventory compares merged source `da60e2127c4bd66e368918d3d83c1829087287a5`
with separate Wiki commit `80b7b25737c52ba7bc72513ae8146333b8023216`.
It records a documentation review, not a release or hardware assessment.
The `primary-wiki` hub stream owns sequencing; existing implementation claims and
historical drafts remain intact. Final source/publication commits and live readback
belong in hub task `wiki-quality-template-example`.

## Inventory and navigation

There are **25 public pages plus `_Sidebar.md`**. `wiki/README.md` is source-only.
The sidebar already links every public page. Local page targets and linked
`blob/main` repository paths resolve; no page orphans were found. Preserve slugs,
especially `How-HDM-Works`, and the useful existing sidebar groups.

| Group | Existing pages |
|---|---|
| Entry and status | Home; Getting Started; Manual Installation; Current State; Feature Roadmap |
| Features | Command Center; eGPU and Docking; Performance and Power; Controllers; Offline Readiness |
| Help and evidence | Supported Hardware; Confirmed Hardware Testing; Safety and eGPU Handling; Troubleshooting; FAQ; Help Improve Re-Gear; Diagnostics and Privacy |
| Contributors | Project Overview; How Re-Gear Works (`How-HDM-Works`); Development; Issues Fixed |
| Device-specific records | Ally X and GPD G1 Automatic Recovery Checkpoint; Ally X and GPD G1 Troubleshooting; Raikiri II Troubleshooting; Ally X and GPD G1 Docking Incident |

Home provides feature descriptions; sidebar provides complete navigation. No new
index or page renaming is warranted. Navigation pages do not need artificial
technical sections. Before this pass, no page used the requested explicit
player/technical split.

## Reusable authoring work

[Information architecture](WIKI_INFORMATION_ARCHITECTURE.md) already separates
README introduction, Wiki explanation and engineering authority.
[The troubleshooting template](templates/WIKI_TROUBLESHOOTING_TEMPLATE.md) has
useful symptom, evidence and verification questions; retain it as an investigation
checklist, not nine required headings for every guide.

[The concise feature/guide template](templates/WIKI_FEATURE_TEMPLATE.md) now
establishes the two audience sections. [Diagnostics and Privacy](../wiki/Diagnostics-and-Privacy.md)
is the representative page: real preview/copy/save labels, expected outcomes,
plain-language terms, technical interfaces and explicit validation limits.

## Publication drift and preserved drafts

| Page/work | Observed difference | Disposition |
|---|---|---|
| eGPU and Docking | Live-only September 12 connection safeguards and powered software reconnect testing hold after unusual dock heat | Preserve live text. Active eGPU primary owns source path; coordinate reconciliation before any sync. The hold is not proof an installed action is disabled, damage occurred or a cause was established. |
| Confirmed Hardware Testing | Source-only additional September 9 software-removal/RPC/restore observations and failed gates | Retain dated source evidence; verify linked records before a separately scoped publication. |
| Issues Fixed | Source-only four additional September 9 runtime-discovered guard defects and lessons | Retain source; publish only after checking references and the distinction between implemented fixes and hardware proof. |
| Command Center draft `claude/wiki-command-center` at `af835e0` | Unmerged draft with useful tile and unknown-state explanations | Preserve checkout. Re-review before reuse: draft clearance language and Auto TDP module status conflict with newer source. |

All other public page contents and the sidebar match the fetched live Wiki at
this baseline. Existing documentation worktrees and stream ownership are unchanged.
The reviewed source directory is not automatic publication; follow
[Wiki synchronization](../wiki/README.md#maintaining-the-published-wiki).

## Prioritized scoped cleanup

| Order | Scope and acceptance | Sequencing / remaining evidence |
|---|---|---|
| 1 | Template and Diagnostics example: player clarity, exact labels, technical links, preview/render checks and separate Wiki readback | Current bounded task; no installed support journey asserted |
| 2 | Reconcile live/source eGPU hold and the two historical source-only pages without overwriting either side | eGPU primary retains its source claim; review historical records independently |
| 3 | Command Center and Performance and Power: remove stale future/PR-status wording only where merged evidence supports replacement | Coordinate UI and Auto TDP primaries; retain approved presentation and distinguish unmerged candidates |
| 4 | Getting Started, Manual Installation, Help Improve and Troubleshooting: apply audience split, preserve actual steps, link shared diagnostics | Reconcile availability across Home, FAQ and Current State together; do not promote release readiness |
| 5 | Remaining feature/contributor guides, then evidence pages where the split helps | One bounded feature at a time; historical incidents keep dates and original results; exact devices belong in evidence tables |

Do not blindly rewrite every page or refresh dates without rechecking claims.
No product behavior, release artifact, device state, README or Discussion is
changed by this inventory.
