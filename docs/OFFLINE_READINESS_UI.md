# Offline Readiness UI

Status: **Implemented locally: one-game picker, native Steam details request,
Python classification RPC, and reason guidance. Not installed or controller
validated. Library-tile badge designed; native tile integration pending.**

## Library-tile direction — user reference, 2026-09-04

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

Next implementation gate: inspect a maintained Decky tile-badge integration and
the current Steam tile component, review licensing and patch/unpatch behavior,
then implement the smallest reversible integration. The photo is a visual
reference, not evidence of a supported Steam extension API.

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
