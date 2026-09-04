# Offline Readiness completion goal

## Current authorization — 2026-09-04

Complete Offline Readiness end to end. The maintainer wants remote development,
research, setup, and automated verification without being at the Ally. Reserve
player involvement for the final acceptance session. Do not ask the maintainer
to select a development sample or perform routine manual installation steps.
Use suitable licensed upstream code and investigate Bazzite where it helps.

This supersedes earlier workstream assumptions that every metadata probe needs
a player-selected game page or that a disposable read subscription is forbidden.
The separate Ally/G1 lifecycle remains owned by its driver. Do not restart its
services, replace its installed runtime, or run display/GPU/sleep transitions
without coordination. Scope is Offline Readiness, not all Re-Gear milestones.

The goal tool rejected the requested replacement goal because its old unfinished
record remains blocked. It exposes no resume operation. Do not mark that goal
complete merely to clear the tool error; this plan is the current execution
contract while that app status is unresolved.

## Deliverable

A player can request an offline check for one identified game and see understandable
installation/update/cloud/online-requirement guidance. The result identifies its
scope, reports uncertainty honestly, expires, and is discarded on context changes.
It never promises an offline launch, changes saves/settings, or launches a game.

## Tasks and exit evidence

1. **Live source access — complete.** Existing SSH/Steam inspection works without
   enabling debugging. Installed exact lookup source and real cache shape inspected.
2. **Reader and field validation — in progress.** Reused one-shot details helper
   executed remotely with Idle checks before/after. One registration and one
   removal verified; exact cached app reference remained stable. Real callback
   fields projected by `offline_steam_details.py`, with regression coverage.
   Remaining: final async caller, game/session binding, failure/expiry handling,
   and clear distinction between current Steam reports and independently verified
   offline prerequisites. Receipt time is not cloud-server freshness.
3. **Overhead — in progress.** One measured request took 28.2 ms. This is a sample,
   not a general benchmark or game-impact proof. Gather a small bounded repeated
   sample, retain the timeout, and defer on Running/Unknown before admission.
4. **Player delivery — pending.** Wire the live async reader into a one-game UI
   flow. Keep game identity local to that view and send only categorical evidence
   to backend classification. Preserve the existing Python policy as authority;
   do not accumulate competing classifiers. Cancel on selection change/unmount,
   reject stale responses, and show concrete next steps.
   The private `OfflineDetailsSession` now cancels superseded requests, gates on
   current Idle context before/after, minimizes callback fields, and permanently
   expires result leases after one second or observed context failure. Its four
   regression tests plus six native-helper tests and typecheck pass. The caller
   must invalidate on every selection/session/game-state event; UI/RPC wiring
   is still pending, and no production freshness claim follows from this lease.
5. **Integration and remote preparation — pending.** Run the full relevant
   matrix, review the diff and artifact, integrate with current main preserving
   other work, and coordinate shared runtime ownership before any installation.
   Prepare a rollback-capable reviewed package remotely where authorized.
6. **Final player acceptance — last.** Only once the implementation and automated
   checks are ready, ask for one short controller-driven check of selection,
   wording, responsiveness, and the displayed result. An actual offline launch
   is a separate player action, never an unattended developer test.

## Sources and current workspace

Branch `codex/offline-readiness-delivery`, worktree:
`C:/Users/SLDD/.codex/worktrees/offline-readiness-delivery/Handheld-Docked-Mode-SteamOS`.
See [handoff](OFFLINE_READINESS_HANDOFF.md), [source review](OFFLINE_EVIDENCE_SOURCE_REVIEW.md),
and [third-party notices](../THIRD_PARTY_NOTICES.md).
No installation or G1 lifecycle action has occurred in this workstream.
