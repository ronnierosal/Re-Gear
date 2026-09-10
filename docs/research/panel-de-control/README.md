# Panel de Control research for Re-Gear

Panel de Control is a useful implementation reference for capability-aware controls,
per-game preferences, configuration ownership, and optional handheld features.
The strongest opportunities for Re-Gear are Battery Care, explicit profile
inheritance, and a small optional performance HUD. Its implementations also supply
valuable failure cases for Re-Gear's existing power, display, controller, and
shutdown contracts.

These are internal research proposals, not accepted architecture, implementation
assignments, hardware-support claims, or a change to the disconnect workstream's
priority. No upstream implementation or assets have been imported into Re-Gear.

## Read the notes

- [Engineering findings and implementation slices](ENGINEERING.md): source-backed
  behaviors, differences from Re-Gear, integration seams, and acceptance tests.
- [Attribution and licensing](ATTRIBUTION.md): inspiration versus adaptation,
  GPL version boundaries, source delivery, and concrete notice templates.
- [Source inventory](SOURCES.md): pinned revisions, source/test coverage, primary
  documentation, and evidence limitations.

## Recommended sequence

| Order | Proposal | Player benefit | First bounded deliverable |
|---|---|---|---|
| 1 | Battery Care | Understand battery condition and reduce unnecessary full-charge time while docked | Read-only battery observation and unsupported/unknown states; charge-limit writes are a separate slice |
| 2 | Per-game and placement profiles | Keep useful settings without reconfiguring each session | Pure inheritance and preview model layered over existing mode/Auto TDP preferences |
| 3 | Small optional HUD | See the information needed to understand performance | Preview and bounded live-source admission; configuration application follows ownership proof |
| 4 | Command Center personalization | Keep frequent controls within reach | Tile ordering/favorites with safety status and recovery access preserved |
| 5 | Launch-options assistant | Understand and safely manage selected compatibility options | Read-only explanation and exact before/after preview; native Steam writing later |
| 6 | Display and audio presets | Adapt to the actual screen and audio destination | Exact output identity and reversible preview before automatic profile application |
| 7 | Download mode | Leave a download running with lower screen/power overhead | Reversible session intent and benchmark plan, not an unconditional minimum-TDP preset |

These priorities are engineering judgments, not measured effort estimates. Battery
Care is a relatively bounded feature candidate; it still needs provider ownership,
identity, persistence policy, and actual-device verification before writes ship.

## Changes worth making to our approach

**Treat background work as a feature with a lifecycle.** A hidden panel is not an
inactive service. Each optional module should declare its subscriptions, storage,
writer ownership, shutdown behavior, and measured collection cost.

**Keep intent, pending application, readback, and recovery separate.** This is
already present in important Re-Gear contracts. Extend it consistently to new
modules rather than introducing a generic success Boolean.

**Use actual resource identity.** Game changes, output switches, AC changes,
controller reconnects, and plugin reloads invalidate different kinds of pending
work. A display preview tied only to an AppID cannot establish that the same
physical display is still being changed.

**Preserve the player's configuration.** Re-Gear should own an exact revision or
an explicit set of fields. Detect intervening edits before replacement or
restoration; retain recovery evidence when ownership is uncertain.

**Adapt narrowly.** Re-Gear already has FPS-target Auto TDP, guarded transitions,
profile intent, telemetry admission, and Command Center components. Their presence
is source evidence, not a claim that every path is installed or hardware tested.
Replacing these with a second control framework would discard useful contracts.

## Attribution decision

Credit Hooandee and Panel de Control when their work informs a delivered feature.
For copied or adapted implementation, credit alone is insufficient: preserve
applicable notices, record the exact source and changes, and meet the relevant
license and source-delivery conditions. Upstream explicitly declares
`GPL-3.0-only`; Re-Gear declares `GPL-3.0-or-later`. Do not relabel imported code
as granting later-version or proprietary/OEM rights. Details and source references
are in [the attribution note](ATTRIBUTION.md).

## Snapshot and limits

The source snapshot was inspected on September 9, 2026, America/Los_Angeles
(September 10 UTC). Panel de Control is pinned at
`c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc` (`package.json` version `0.45.0`).
Re-Gear is pinned at freshly fetched remote main
`c09df57fe03a8d89c69afb0c8d9fb1664d14c741`, which is newer than the local main
used in the initial feature review. Individual worktrees and open PRs can contain
additional work; absence in this baseline is not proof that nobody is implementing
a capability.

The review is static: selected production paths and test assertions were read,
but upstream code, tests, installers, and hardware operations were not executed.
No benchmark, full security audit, release ZIP inspection, or hardware certification
is implied. Documentation disagreements are identified in the detailed notes.
