# Offline Readiness UI

Status: **Automatic focused-tile badge implemented and mounted in the development
source. Native rendering and controller behavior are not validated; that gate is
[issue 21](https://github.com/ronnierosal/Re-Gear/issues/21). The manual Quick
Access panel exists in source but is not mounted.**

Source of truth for this contract is the code at the revision below, not this
file. Verified against `da60e21` on 2026-09-13. Evidence limits are owned by the
[source review](OFFLINE_EVIDENCE_SOURCE_REVIEW.md); workstream state and
remaining gates are in the [handoff](OFFLINE_READINESS_HANDOFF.md) and the
[completion plan](OFFLINE_COMPLETION_PLAN.md).

## What is mounted today

`startOfflineFocusChecks()` is created once with the plugin in
`src/index.tsx:2378` and stopped in its `onDismount` at `src/index.tsx:2405`.
It is independent of Quick Access rendering
(`src/offline-focus-checks.tsx:25-26`). Nothing imports
`src/offline-readiness-panel.tsx`, so no Offline Readiness section appears in
Quick Access.

The player journey is therefore passive: focus a game tile in Home, Library or
Search with the controller, and a small badge appears on that one tile. There is
no button to press, and the one surface that could explain the result in words
never populates — see below.

### The Quick Access journey row is mounted but never populates

Quick Access does render an "Offline readiness" row through `journeyStatusRows`
(`src/quick-access-ui.ts:101-134`), mounted at `src/index.tsx:913-914` behind the
Troubleshoot disclosure. It is fed from `payload.journey`
(`src/index.tsx:818`), and the backend snapshot emits no `journey` key at all, so
the row always falls through to "Not connected" with the detail "This local
classifier is not yet wired into read-only snapshot delivery", and
`compactJourneyStatusRows` collapses it out of the compact summary
(`src/quick-access-ui.ts:137-146`). The fail-closed wording is correct; treat the
row as unwired rather than as a working status surface. This is planned, not
accidental: `src/backend.ts:156` annotates the field "Optional future read-only
delivery for local journey classifiers". Its state and reason-code presentation
(`src/journey-status-delivery.ts:12,60-71`, `src/offline-readiness-detail.ts`) is
ready for a future snapshot source.

### Discovery and binding

- Navigation windows come from `DFL.getGamepadNavigationTrees()`, deduplicated
  and capped at 16 (`src/offline-focus-checks.tsx:16-23`). Route patches on
  `/library`, `/library/home` and `/search` re-run discovery event-driven, with
  no timer or document scan (`src/offline-focus-checks.tsx:107-113`).
- Each window gets a `focusin` listener and one `MutationObserver` that inspects
  only the active element; library tiles are never enumerated
  (`src/offline-focus-checks.tsx:92-106`). `syncViews` also calls `refresh` on
  each window as it is discovered, so a tile that is already focused when the
  plugin loads is considered immediately and then settles normally
  (`src/offline-focus-checks.tsx:104,113`).
- Tiles are matched by `div[role="tabpanel"] div[role="gridcell"]` and
  `.ReactVirtualized__Grid__innerScrollContainer div[role="listitem"]`
  (`src/offline-tile-badge.ts:5`).
- The AppID is the exact numeric `data-id`; if that is absent, a single
  unambiguous ID parsed from at most eight tile images is accepted, and an
  ambiguous tile yields nothing (`src/offline-tile-badge.ts:14-25`). Our own
  badge is never an identity source (`src/offline-tile-badge.ts:123`).

### Refresh, retry and expiry

| Timing | Value | Source |
| --- | --- | --- |
| Settle before the first check | 450 ms | `src/offline-focus-checks.tsx:12,84` |
| Cadence while the same tile stays focused | 60 000 ms | `src/offline-focus-checks.tsx:13,58,76` |
| Retry after a failed attempt | 5 000 ms for the first two consecutive failures, then back to 60 000 ms | `src/offline-focus-checks.tsx:14,68,76` |
| Native callback budget | 1 000 ms from request start | `src/offline-details-session.ts:47` |
| Result validity after receipt | under 1 000 ms | `src/offline-details-session.ts:52-54` |
| Tile badge lifetime | 65 000 ms | `src/offline-focus-checks.tsx:75` |

A successful check resets the failure counter
(`src/offline-focus-checks.tsx:76`). Ineligible ticks — gameplay or unknown
running state — keep the cadence alive but issue no request
(`src/offline-focus-checks.tsx:78-81`), so checks resume after gameplay without
another focus event.

At 65 000 ms the badge is not removed: its image and label become the neutral
`offline-verify` asset and "Check unavailable"
(`src/offline-focus-checks.tsx:75`, `src/offline-tile-badge.ts:145-154`). This
keeps the affordance while guaranteeing no expired positive claim remains on
screen. The badge is removed outright when the result is invalidated.

### Cancellation and invalidation

`cancel()` bumps the request sequence, clears the timer, invalidates the details
session and stops the badge (`src/offline-focus-checks.tsx:32`). It runs on every
focus change, and the result is additionally discarded when any of the following
stops holding:

- the request is superseded, the tile is disconnected, focus has left it, or its
  AppID changed (`src/offline-focus-checks.tsx:43-44`);
- `window.appStore`, the overview object for that AppID, `display_status`, the
  private account scope, or the idle/running state changed since the observation
  the attempt was bound to (`src/offline-focus-checks.tsx:49-51`);
- `display_status` is 4, or `Router.RunningApps` is non-empty
  (`src/offline-focus-checks.tsx:33-34`);
- the plugin dismounts, which also removes the listeners, observers and route
  patches and clears session-only test memory
  (`src/offline-focus-checks.tsx:114-124`).

Each attempt binds to its own observation rather than the original focus state,
and once invalidated a late response cannot become valid again
(`src/offline-focus-checks.tsx:64-67`). A failed refresh expires to neutral and
never retains a stale positive (`src/offline-focus-checks.tsx:77`).

### Categorical status and confidence label are different things

These are two separate layers and the badge uses both.

**Categorical status** is the backend's conservative classification, returned by
the `classify_offline_details` RPC (`main.py:688`). The frontend admits it
through `offlineReportBadge` (`src/offline-badge-state.ts:6-21`), which accepts
only:

- `needs_attention`,
- `online_check_needed`,
- `unknown` whose reason codes are entirely incomplete-evidence codes.

`ready_to_try_offline` and an internet-required state deliberately produce no
badge from this source (`src/offline-badge-state.ts:19-20`). `offline-required`
artwork has no code path and stays reserved.

**Confidence** is a separate frontend assessment over private preparation clues
(`src/offline-confidence.ts:54-105`). Its four labels are "Needs preparation",
"Likely offline-ready", "Tested offline" and "Unverified".

The mounted path gates on the categorical report existing at all, then takes the
badge asset and accessible label from confidence
(`src/offline-focus-checks.tsx:72-73`):

| Confidence status | Asset | Accessible label |
| --- | --- | --- |
| `needs_preparation` | `offline-attention-compact.svg` | Needs preparation |
| `likely_offline_ready` | `offline-ready-compact.svg` | Likely offline-ready |
| `tested_offline` | `offline-ready-compact.svg` | Tested offline |
| `unverified` | `offline-verify-compact.svg` | Unverified |

Mapping and imports: `src/offline-confidence-session.ts:45-48` and
`src/offline-readiness-badge.tsx:1-6`. The badge `title` adds "Steam report at
check time" (`src/offline-tile-badge.ts:97`).

Two consequences worth stating plainly:

- The positive asset can appear, but only ever labelled "Likely offline-ready"
  or "Tested offline". The mounted UI never says "Ready to try offline", and the
  backend's `ready_to_try_offline` status remains unreachable from this Steam
  report source. In practice a green badge is reached *from* a backend `unknown`
  report: the categorical layer admits it as incomplete evidence, and the
  confidence layer then finds complete local preparation plus explicit
  compatibility facts and the single-player category. That is deliberate and
  documented, not a leak — but it means the green badge is a frontend heuristic,
  never independently verified offline authorization.
- "Tested offline" is currently unreachable in the mounted path.
  `offlineConfidenceForGame` is called there without a confirmation binding
  (`src/offline-focus-checks.tsx:73`), so `offlineTestMemory.confirm` is never
  invoked and `has()` always returns false. The attestation mechanism exists and
  is tested; it has no mounted caller.

### Placement and bounds

The badge is a single pointer-transparent `img` the adapter owns, appended to the
nearest positioned ancestor, defaulting to 24x24 at `bottom:6px;left:6px`
(`src/offline-tile-badge.ts:67,93-101`). When exactly one square native icon sits
in the tile's lower-right quadrant, `offlineBadgeLayout` matches that icon's
height (capped at 24 CSS pixels), keeps `left:6`, centres on the icon's vertical
midpoint and refuses any layout that would overlap the native group
(`src/offline-badge-layout.ts`). Native styles and badges are never altered, and
foreign badges are preserved.

Bounds: with a specific tile bound — the mounted path always binds one — only
that tile is reconciled (`src/offline-tile-badge.ts:52,117`). The 256-tile scan
and 128-record observer cap apply only to the unbound call shape and fail closed
(`src/offline-tile-badge.ts:106-108,118,128`). There is no periodic scan, no
library-wide game-details request, no persistence and no per-tile subscription. A
missing native ID or host simply yields no badge.

### Standing presentation rules

- Shape and accessible text carry the meaning in addition to colour.
- Never label an installed game as offline-ready solely because it is installed,
  launches online, or reports Steam Cloud synchronization. No guaranteed-offline
  claim and no "tested offline" marker without a separately recorded attestation.
- Render only a result bound to that exact local game and current session. Never
  place an unidentified game's result into a whole-device readiness summary.
- Do not require precise pointer interaction with the badge.

## Defined but not mounted

Removing the manual surface was a deliberate product decision, not a regression:
`docs/CURRENT_STATE.md:409-415` records that 0.3.35-offline.1, revision
`c0590e5`, removed the manual Offline Readiness panel, game picker, check button
and manual test confirmation from Quick Access, keeping the plugin-lifecycle
automatic checks and artwork badges, and notes that the manual-panel source is
dormant and tree-shaken from the build.

The consequence is a **deferred explanation surface**: today a player sees a
badge and its accessible label, but has no way to read the detailed preparation
reasons or record a "Tested offline" attestation. Whether to give the automatic
path its own explanation entry point is an open product question for the primary
and the UI owner. It is not licence to restore the old panel layout.

The pieces below exist in source and are covered by tests. Treat them as
available material, not as current player-visible behavior.

- `OfflineReadinessPanel` (`src/offline-readiness-panel.tsx`) — no importer. It
  carries the installed-game picker, an explicit "Check this game" action, "Why
  this result?" reasons, the "I played this build without internet" attestation
  and "Forget this offline test". Its result expires after 30 000 ms
  (`src/offline-readiness-panel.tsx:113`) and its tile badge uses the adapter's
  30 000 ms default, which removes the badge instead of neutralising it
  (`src/offline-tile-badge.ts:36`). Where older notes say "30-second badge
  expiry" or "an explicit panel check can badge the matching visible tile", they
  describe this path, not the mounted one.
- `offlineGameChoices` (`src/offline-native-source.ts:23`),
  `offlineLibraryWindow` (`src/offline-tile-badge.ts:160`),
  `offlineConfirmationBinding` (`src/offline-confidence-session.ts:13`) and the
  `OfflineReadinessBadge` component (`src/offline-readiness-badge.tsx:8`) — dead
  exports in otherwise-live modules, used only by that panel. Of
  `offline-readiness-badge.tsx`, only the sibling `offlineBadgeImages` export
  reaches production.
- The full-size and `-gear` asset variants, and all `offline-required` artwork,
  are resolvable through `rollup.config.js` but imported by no component; only
  the three `-compact` files reach the bundle.

Activating any of this is a separate assigned decision. This document does not
propose an Offline Mode, automatic confirmation, or a new surface.

## Remaining validation

Software behavior above is covered by the frontend suites in
`frontend-tests/offline-*.test.mjs`, which passed at `da60e21` in an independent
read-only baseline review — 68 tests together with `steam-app-details-request`,
plus typecheck. That review is a local agent-coordination record rather than a
repository artifact; its results are summarised here. Those suites transpile the real
focus module but mock the details session, native source, classification,
confidence and badge attachment, so they exercise each module rather than the
combined production journey. There is no React panel-mount test. Known coverage
gaps: native immediate account and session events, navigation-window replacement
and cleanup, startup against a partially initialized native DOM, and real
callback or RPC latency.

No golden behavior ID currently names Offline Readiness. Native rendering,
controller behavior and refresh recovery in Home and Library remain unvalidated
on a device; that is tracked solely by
[issue 21](https://github.com/ronnierosal/Re-Gear/issues/21). Passing frontend
tests are not evidence of native rendering, and no badge state is evidence that a
game will actually launch offline.

## Attribution

Native DOM seam researched in
[Non-Steam Badges observer](https://github.com/sebet/decky-nonsteam-badges/blob/cc620181962f601b713c9db2045e98dd82ecdbf2/src/utils/observer.ts)
and its [capsule implementation](https://github.com/sebet/decky-nonsteam-badges/blob/cc620181962f601b713c9db2045e98dd82ecdbf2/src/feature/addBadgeToCapsule.ts),
BSD-3-Clause. Our adapter is independently implemented: exact data-id binding,
owned nodes only, no periodic scans, no broad identity fallbacks, no native badge
hiding and no style rewrites. ProtonDB Badges' archived implementation patches
game-details routes, not library tiles. See `THIRD_PARTY_NOTICES.md`.

---

## Historical evidence — 2026-09-04

Retained for provenance. These entries describe the state of the work on their
date and are **not** current instructions; where they disagree with the contract
above, the contract above is correct.

### Supplied artwork decision

The maintainer supplied four SVG assets, imported from upstream commits
`3d79706`, `f7506a4`, `2b5e0cf` and `d5a31a5`, and asked for a compact
controller/checkmark-style badge in the lower area of a Steam tile. These
superseded an earlier proposal for an airplane symbol with a state marker and an
earlier intent to give `offline-ready.svg` the literal accessible label "Ready to
try offline". `offline-required.svg` was reserved for a future independently
confirmed internet-required state; the classifier still has no such definitive
category, so nothing maps to it.

### DOM inspection sample

Read-only DOM inspection on the Ally confirmed DFL navigation windows, the
expected library/home selectors, and 23 numeric data IDs in a bounded sample of
32 tiles; all sampled tiles were already positioned. Repeated navigation trees
can reference the same window, so discovery deduplicates them. This was
source/DOM evidence, not a device badge-rendering claim. A local browser preview
exercised the actual adapter and showed the supplied icon legibly at 72x32 beside
a report and on sample artwork. Six adapter regression tests covered recycled
identities, unknown/static tiles, expiry/unmount, foreign badge preservation,
source failure and ancestor-role changes. Frontend suite at that time: 100
passed; typecheck, build, package and whitespace checks passed. Backend unchanged
since the 834-test gate. No installed runtime change, and the badge had only been
visually exercised in a local browser surrogate.

### One-game panel delivery, as built that day

The one-shot native Steam reader was wired to the one-game panel, with raw game
details reduced to seven scalar fields before classification, a 30-second display
expiry, and clearing on selection/view/game or source changes observed during
existing panel refreshes. The optional payload accepted only schema version,
categorical status and public reason codes — no title, AppID, account, path,
timestamp or collector command — and a cloud conflict took precedence over a
pending update. That panel is the dormant module described above; the automatic
focused-tile path replaced it as the mounted delivery.
