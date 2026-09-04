# Offline Readiness delivery workstream

**Current execution contract:** [remote completion plan](OFFLINE_COMPLETION_PLAN.md).
The maintainer now requests remote completion with hands-on validation only at
the end. That plan supersedes the older operator-presence assumptions below.

## Mission and ownership

Help a player understand whether a game needs attention before leaving Wi-Fi.
This workstream owns Offline Readiness evidence research, narrow read-only
adapters, tests, and delivery guidance. The Ally/G1 driver retains connection,
disconnect, sleep, recovery, deployment, and hardware transitions. The UI driver
retains broad Quick Access design.

## Workspace

- Branch: `codex/offline-readiness-delivery`
- Base: `75f441f` (current main when this work began, 2026-09-03).
- Worktree: `C:/Users/SLDD/.codex/worktrees/offline-readiness-delivery/Handheld-Docked-Mode-SteamOS`
- Older `codex/offline-readiness` at `73dc3da` is historical foundation;
  do not resume it or merge its old tree over current main.
- Main had unrelated research/index and UI-preview edits. They remain untouched.

## Plan and acceptance

1. Inspect classifier, source-admission, UI, and primary upstream evidence.
2. Record a source decision, privacy boundaries, and unsupported evidence.
3. Implement the smallest justified source/delivery slice with synthetic
   failure, stale, identity-minimization, and game-admission tests.
4. Record verification and the precise remaining production gate here; link
   this checkpoint from the queue and operator handoff.

No whole-library scan, background polling, network/account queries, credential
reads, saves/configuration writes, game launches, or automatic Offline Mode.
An installed game is not proof of entitlement, cloud sync, or offline launch.
No live source can self-declare a benchmark from synthetic test timing.

## Checkpoint: guarded request and reason delivery implemented locally

- Research decision and links: [source review](OFFLINE_EVIDENCE_SOURCE_REVIEW.md).
  Prefer exact local Steam overview evidence; Protontricks and Ludusavi are
  references, not dependencies. Valve documents why installation and enabled
  cloud settings cannot establish readiness.
- First commit: `03946d2` adds the candidate source projection and research.
- Second commit: `0bfbf8f` adds guarded request and categorical reason delivery.
- Change: a candidate adapter minimizes one privately bound base-game overview
  into existing categorical evidence. Explicit updates/downloads and cloud
  conflicts can report attention; no favorable overview can report offline-ready.
- The new application request service admits before reading and rechecks the
  private selection/session generation, game state, timestamp, and actual cost
  before public serialization. It performs one injected local-memory read, with
  no scheduler, cache, retries, or production reader construction.
- The existing UI sanitizer now preserves only known bounded reason codes and
  shows fixed next-step guidance. Cloud conflicts take priority over updates.
  No broad layout or hardware journey behavior changed.
- Independent review found and fixed an observation-type hole that allowed
  malformed evidence to appear ready. A regression covers the reproduced case.
- Verification: 825 backend tests passed (5 skipped); 80 frontend tests passed;
  architecture, full Python compilation, TypeScript, frontend build, package,
  and whitespace checks passed. Source maps/bundle were regenerated locally.
- During verification, Node required explicit TypeScript import extensions;
  no-emit checking and Rollup now share extension-aware configuration. A copy
  regression restored the existing explicit offline-play-not-guaranteed wording.
- Hardware evidence: none. No remote capture, install, Steam calls, or transition.
- Remaining gates: live schema/source review, production game/session binding,
  trustworthy source timestamps, measured reader cost, on-request RPC transport,
  and selected-game UI context with response invalidation. Production snapshot
  delivery remains unconstructed; this milestone is not yet a usable live check.
- Next safe task: inspect the local Steam/Decky cached-state access path and
  design one selected-game request with invalidation and cleanup. Confirm its
  local-only behavior before wiring a reader. Do not label request time as the
  freshness timestamp of cached data.

## Latest source evidence and required input

Upstream implementation inspection now verifies that the exact-AppID lookup
reads a map, the local-client getter selects the local reserved client ID, and
native overview callbacks populate the cache. It does not establish trustworthy
sample age or installed-client equivalence. The pinned URL, artifact hash,
privacy/serialization implication, and next gate are in the source-review doc.

The maintainer has been asked for the current Ally SSH host. The operator
handoff requires a current maintainer-provided host: do not reuse stale captures,
guess an address, scan the network, or ask another workstream to make a hardware
transition. No remote call has been attempted. When supplied, inspect only
bounded installed client/source provenance first. Remote debugging activation,
observer deployment, and forced refresh are outside current authority.

### Resume evidence — 2026-09-04

The maintainer supplied the current host and read-only SSH succeeded. The prior
missing-host blocker is resolved. Installed static-source inspection verified
the exact-AppID map lookup and local-client getter; artifact details and limits
are in `OFFLINE_EVIDENCE_SOURCE_REVIEW.md`. No installation was needed.

No remote task remains running. Runtime cache data, callback timestamps,
selection binding, and reader cost remain unmeasured. Next: identify an already
available read-only runtime observation surface; do not enable debugging,
install an observer, trigger refresh, or interfere with the G1 driver. The
feature remains incomplete and undeployed. This resumed turn made progress;
the former missing-host blocked audit no longer applies.

## Completion audit

## Five-task completion plan — resumed 2026-09-04

The maintainer explicitly authorized proceeding with all five next steps.
The app rejected creation of a second goal because the earlier goal is unfinished;
its status remains blocked in the app and no resume operation is exposed by the
goal tool. Continue the existing objective here; do not falsely complete it to
clear that tool constraint.

| Task | Current evidence/status | Remaining acceptance |
| --- | --- | --- |
| 1. Inspect existing live read-only access | **Verified:** existing loopback Steam debugging endpoint, protocol 1.3, shared context, initialized appStore, and exact lookup function. Runtime evaluation enforced `throwOnSideEffect`; no debugging activation. | Complete for identifying access; production use still needs its own design. |
| 2. Validate selected-game local evidence and freshness | **In progress:** no selected-game route was present in the inspected targets. Maintainer asked to open one game's details page and keep the game closed. | Exact local fields, game/session binding, evidence age; categorical output only. |
| 3. Measure collection cost | Pending task 2. | Actual bounded reader timings; no claim from source parsing, SSH latency, or synthetic tests. |
| 4. Wire on-demand check and invalidation | Guarded service and reason text locally tested; live transport/context unconstructed. | Selected-game request, clear status/reasons, discard on context change/expiry; no background polling. |
| 5. Test/build/review before installation | Prior local gate: 825 backend tests (5 skipped), 80 frontend tests, architecture/typecheck/build/package passed. | Re-run affected gates for final changes; review final artifact. No deployment authorized. |

Runtime probe returned only capability booleans. CDP target IDs stayed transient;
no titles, AppIDs, account data, cache records, or destination addresses were
persisted. The probe connection closed after each read. No remote task remains.
Next action: after the player selects a game, inspect the current route/context
without a library scan. Do not infer game identity from most-recent-played data.

Research/source choices, conservative projection, request gates, actionable
categorical presentation, local verification, and continuation documentation
have evidence. A usable selected-game check still lacks a reviewed live reader
and request/UI binding. Resume the goal when its input is available; do not mark completion from the
local tests or enable collection merely by setting admission flags to true.

## Resume

Latest checkpoint (2026-09-04): executed the reused app-details helper remotely
for one bounded installed-game sample after verified Idle, and verified Idle
again afterward. Received details in 28.2 ms, one registration/one removal,
stable app object. Installation folder known; display status 19; cloud status 1;
cloud unavailable, account-cloud enabled, app-cloud disabled, third-party updater
false. No identity exported. Added the corresponding conservative callback-field
projector; 39 focused offline tests, architecture, and compilation passed.

This measures one request only, not a general benchmark. Native metadata callback
receipt is not proof of server sync or launch authorization. Next implementation
work is the async reader/selected-game flow and bounded repeated cost checks.
No player presence is required for those development steps. Bazzite/updater
research found no direct substitute in inspected source; see source review.

Latest remote sample (2026-09-04): the user is away from the Ally and asked us to
continue remotely. Source validation does not require the user to select a game;
we can inspect a bounded sample without claiming it is the selected-game UI.
The normal MobX map iterator was rejected under `throwOnSideEffect`. Keeping
that safeguard enabled, inspection of its native backing map found one locally
installed base game in the first entry (maximum 16 entries, 16 clients each).
Categorical output: local client, installed, platform available, not streaming,
display status 19 (UpdateQueued), cloud status unavailable. No game identity was
exported. This is current cache content, not verified source age, cloud sync, or
offline readiness. No game launch, navigation, subscription, or settings change.
Internal MobX backing fields are inspection-only and must not become a production
API dependency. Next: measure/review the intended production reader and resolve
freshness; selected-game UI binding remains a later delivery requirement.

Latest reuse checkpoint (2026-09-04): added an attributed adaptation of Storage
Cleaner's single-game detail request helper. See `THIRD_PARTY_NOTICES.md` and
`src/steam-app-details-request.ts`. Six callback/timeout/abort/error tests and
TypeScript passed. It is not wired to Steam: native subscription behavior and
freshness still need review, and this async helper does not fit the existing
synchronous read-local port. A user-selected page is not required for bounded
source investigation; it remains required context for the eventual player flow.

Read this file, `OFFLINE_EVIDENCE_SOURCE_REVIEW.md`, `OFFLINE_READINESS_UI.md`,
and current `git status`/diff in the worktree above. Continue only this mission.
Update this checkpoint after each meaningful verified slice, preserving the
distinction between synthetic tests, source research, and live verification.
