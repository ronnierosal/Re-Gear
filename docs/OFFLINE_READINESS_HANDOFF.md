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

## Checkpoint: guarded request and reason delivery implemented locally

- Research decision and links: [source review](OFFLINE_EVIDENCE_SOURCE_REVIEW.md).
  Prefer exact local Steam overview evidence; Protontricks and Ludusavi are
  references, not dependencies. Valve documents why installation and enabled
  cloud settings cannot establish readiness.
- First commit: `03946d2` adds the candidate source projection and research.
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

## Completion audit

Research/source choices, conservative projection, request gates, actionable
categorical presentation, local verification, and continuation documentation
have evidence. A usable selected-game check still lacks a reviewed live reader
and request/UI binding. Keep the goal active; do not mark completion from the
local tests or enable collection merely by setting admission flags to true.

## Resume

Read this file, `OFFLINE_EVIDENCE_SOURCE_REVIEW.md`, `OFFLINE_READINESS_UI.md`,
and current `git status`/diff in the worktree above. Continue only this mission.
Update this checkpoint after each meaningful verified slice, preserving the
distinction between synthetic tests, source research, and live verification.
