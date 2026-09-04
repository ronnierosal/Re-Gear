# Offline Readiness UI

Status: **Implemented locally: one-game picker, native Steam details request,
Python classification RPC, and reason guidance. Not installed or controller
validated. Library-tile badge implemented locally; installed native rendering
and controller validation pending.**

## Library-tile direction — user reference, 2026-09-04

The maintainer's four SVG assets are now available under
`src/assets/offline-readiness/`, imported from upstream commits
`3d79706`, `f7506a4`, `2b5e0cf`, and `d5a31a5`. Use these supplied
controller/status designs instead of the earlier proposed airplane symbol.
`offline-ready.svg` maps to Ready to try offline (provide that exact accessible
label at the component boundary); `offline-attention.svg` maps to Needs attention;
`offline-verify.svg` maps to Online check needed. Reserve `offline-required.svg`
for a future independently confirmed internet-required state: the current
classifier has no such definitive category, so do not map unknown or a launcher
check requirement to this red badge. Attention and verify assets are now embedded
locally by Rollup and rendered by the panel and tile adapter.

### Implemented badge delivery

`offline-tile-badge.ts` uses exact numeric native `data-id` binding on observed
library/home tile selectors. It requires an already-positioned tile, adds only
its own pointer-transparent image at the upper-left, and does not alter native
styles or badges. Position remains provisional pending real Steam rendering.
An explicit panel check can badge the matching visible tile for up to 30 seconds,
including after Quick Access closes. Selection changes, plugin unmount, expiry,
or observed game/source invalidation remove it. Recycled tiles are rebound from
their current native ID; our own badge is never an identity source.

The adapter inspects at most 256 initially rendered tiles and handles changed DOM
nodes through one short-lived MutationObserver. Oversized batches/surfaces fail
closed. There is no periodic scan, library-wide game-details request, persistence,
or new game/session polling. Missing native ID/host yields no tile badge while
the panel can still explain the result. Direct game-details-page explanation
integration remains pending; use the existing Quick Access check surface.

Research seam: [Non-Steam Badges observer](https://github.com/sebet/decky-nonsteam-badges/blob/cc620181962f601b713c9db2045e98dd82ecdbf2/src/utils/observer.ts)
and [capsule implementation](https://github.com/sebet/decky-nonsteam-badges/blob/cc620181962f601b713c9db2045e98dd82ecdbf2/src/feature/addBadgeToCapsule.ts),
BSD-3-Clause. Our bounded adapter is independently implemented. We did not copy
upstream periodic scans, broad identity fallbacks, native badge hiding, or style
rewrites. ProtonDB Badges' archived implementation patches game-details routes,
not library tiles.

Remote read-only DOM inspection on 2026-09-04 confirmed DFL navigation windows,
the expected library/home selectors, and 23 numeric data IDs in a bounded sample
of 32 tiles; all sampled tiles were already positioned. Repeated navigation trees
can reference the same window, so discovery deduplicates them. This is source/DOM
evidence, not a device badge-rendering claim. A local browser preview exercised
the actual adapter and showed the supplied icon legibly at 72x32 beside a report
and on sample artwork. Six adapter regression tests cover recycled identities,
unknown/static tiles, expiry/unmount, foreign badge preservation, source failure,
and ancestor-role changes. Full frontend suite: 100 passed; typecheck/build/package
and whitespace checks passed. Backend unchanged since the 834-test gate.

The maintainer supplied a photo of a compact controller/checkmark badge in the
lower-right of a Steam game tile and requested similar at-a-glance offline
readiness. Make the library tile the intended glanceable entry point; retain
the one-game panel as the explanation/check surface.

- Use a compact airplane/offline symbol with a small state marker, visually
  distinct from Steam's controller/checkmark. Do not replace existing badges
  or cover artwork/title unnecessarily; final placement needs native inspection.
- Ready to try offline: offline symbol with a check, accessible label
  "Ready to try offline". This requires admitted evidence; the current limited
  Steam report cannot produce this positive state.
- Needs attention: offline symbol with an exclamation mark, amber accent.
- Online check needed: offline symbol with a question mark, neutral accent.
- Unknown, unrequested, or expired: no positive badge. Show "Not checked" or
  "Check again" in focused game details; avoid cluttering every tile.
- Shape and accessible text convey meaning in addition to color. Selecting the
  game exposes the reason and check action through controller-accessible UI;
  do not require precise pointer interaction with the badge.
- Never label an installed game as offline-ready solely because it is installed,
  launches online, or reports Steam Cloud synchronization. No guaranteed-offline
  claim and no "tested offline" marker without actual separately recorded proof.
- Render only a result bound to that exact local game and current session.
  Do not run a library-wide scan or subscribe per visible tile. Reuse bounded
  explicit checks; invalidate on observed context changes and expiry.

Next implementation gate: integrate with the newer installed G1 baseline, then
verify native rendering and controller behavior. The photo is a visual reference,
not evidence of a supported Steam extension API.

## Current one-game delivery

Quick Access can present only the existing public Offline Readiness categories:
**Ready to try offline**, **Needs attention**, **Online check needed**, and
**Unknown**. “Ready to try” is deliberately not a promise that a game will
launch or play offline.

The optional payload accepts only schema version, categorical status, and public
reason codes. It has no title, AppID, account, path, timestamp, or collector
command fields. The UI retains only bounded allowlisted reasons and maps them
to fixed player-language guidance. A cloud conflict takes precedence over a
pending update. Unknown strings and oversized reason arrays are discarded;
raw reason text is never rendered. Unknown/missing
delivery remains a fail-closed “Not connected” status.

The one-shot native Steam reader is wired to the one-game panel. It has no
persistence, launch authority, or new polling loop. Raw game details are reduced
to seven scalar fields before classification. Live source timing and cleanup
evidence are recorded in the completion plan.

The async frontend session binds a request to the selected game and checks Idle
context before delivery. The standalone RPC uses the existing Python classifier.
The earlier synchronous application request service remains a separate dormant
port. The display describes Steam's report at check time, expires after 30 seconds,
and clears on selection/view/game changes or source changes observed on existing
panel refreshes. Native immediate session-change hooks remain unverified. Never
put an unidentified game's result into a whole-device readiness summary.

See the [active handoff](OFFLINE_READINESS_HANDOFF.md) for exact implementation,
verification, and remaining production gates.
