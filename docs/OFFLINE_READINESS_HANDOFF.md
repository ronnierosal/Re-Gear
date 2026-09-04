# Offline Readiness delivery workstream

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

## Checkpoint: candidate source projection implemented

- Research decision and links: [source review](OFFLINE_EVIDENCE_SOURCE_REVIEW.md).
  Prefer exact local Steam overview evidence; Protontricks and Ludusavi are
  references, not dependencies. Valve documents why installation and enabled
  cloud settings cannot establish readiness.
- Change: a candidate adapter minimizes one privately bound base-game overview
  into existing categorical evidence. Explicit updates/downloads and cloud
  conflicts can report attention; no favorable overview can report offline-ready.
- Verification: 22 focused offline tests passed (7 new adapter tests); architecture
  check, targeted Python compilation, and whitespace checks passed.
- Hardware evidence: none. No remote capture, install, Steam calls, or transition.
- Remaining gates: live schema/source review, exact game/session binding,
  source freshness, measured reader cost, on-request transport, and scoped UI
  context. Production snapshot delivery remains unconstructed.
- Next safe task: inspect the local Steam/Decky cached-state access path and
  design one selected-game request with invalidation and cleanup. Confirm its
  local-only behavior before wiring a reader. Do not label request time as the
  freshness timestamp of cached data.

## Resume

Read this file, `OFFLINE_EVIDENCE_SOURCE_REVIEW.md`, `OFFLINE_READINESS_UI.md`,
and current `git status`/diff in the worktree above. Continue only this mission.
Update this checkpoint after each meaningful verified slice, preserving the
distinction between synthetic tests, source research, and live verification.
