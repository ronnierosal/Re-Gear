# Auto TDP independent work

Requested 2026-09-05: complete all five items while the maintainer is away from
the console. Driver: `codex/tdp-control`, isolated worktree. This plan records the
work even though the app's existing unfinished goal remains marked blocked and
the available goal tools cannot resume or replace it. Device validation is still
part of the original objective; no completion claim is made.

| Item | Acceptance | Status |
| --- | --- | --- |
| Per-mode preferences | Explicit saved FPS and watt range for each stable placement; no fallback or activation of unsupported modes | Model, strict atomic storage, RPCs and expandable editor implemented; Portable load still requires explicit Start |
| Pause/resume | Game, mode, ownership and power evidence loss prevents writes; fresh settling before resume; explicit Stop stays stopped | Existing lifecycle plus new closed-loop replays; UI now explains pause reasons |
| Ineffective increases | Flat sampled FPS does not repeatedly raise watts; noisy spikes cannot release hold; sustained change reassesses | Implemented with two ineffective increases, existing FPS deadband and a fresh changed-sample quorum; synthetic tests pass |
| Replay scenarios | Flat and responsive workload, changed workload, frame rewarming, game exit, eligibility loss, uncertain write | Ten new session/service replays pass; complete integration matrix passes |
| Integration preparation | Preserve registered completed work and current release lineage; name overlaps and gates | Read-only ancestry/conflict audit complete below |

The response heuristic does not classify CPU bottlenecks, frame caps or loading
screens. It retains the current setting when holding; it does not reverse a write
without verification. Only a verified increase can preserve its response baseline
across frame-window rewarming, for at most 30 seconds and with matching live
workload/provider/readback. Readiness loss discards it. Fresh votes and final
dispatch verification remain mandatory. Hardware tuning remains unverified.

Validation: 1,150 backend tests run successfully (15 platform skips), 99 frontend
tests pass, with architecture, compilation, typecheck, build and package checks.
The new preferences editor could not be rendered because the browser tool reports
no available provider. Preview server stopped. Rendered/native checks remain pending.

Preferences use a fixed private `auto-tdp-preferences.json`, separate from thermal,
host and benchmark configuration. Saving does not start or change a session. The
one-instance lock preserves other modes during concurrent saves. Unsupported
placements can retain intent but cannot load into active Auto controls. Loading
Portable values still requires current bounds and every existing admission check
before explicit Start. No automatic profile selection on docking or resume is added.

Temporary loss of admissible game/evidence leaves Auto enabled but waiting, with
fresh settling before adjustment. Explicit Stop/manual takeover/unload invalidates
activation; uncertain writes stop the session. Active transition journal ownership
prevents power dispatch during sleep/mode operations. No unattended sleep, display
or GPU action was introduced. These local results do not validate additional modes.

## Integration preparation

Audit boundary: TDP `841b4da`; new work must be committed/tested before integration.
Inspected ready ledger: `offline-ui` = `4b7c9ea`, `quick-launch-name` = `ee050fd`.
The coordination patches are equivalent, but the ledger requires both ancestries.
The eventual release driver should create a fresh integration checkout from
`refs/regear/ready/offline-ui`, perform a content-neutral normal merge of
`refs/regear/ready/quick-launch-name`, then merge the clean TDP tip. Recheck the
ledger first; these refs may advance. Preserve the current 0.3.x version and
Offline/G1 behavior; do not replace them with this branch's 0.2.0 baseline.

Predicted overlapping conflicts: `THIRD_PARTY_NOTICES.md`, `docs/CURRENT_STATE.md`,
`docs/OPERATOR_HANDOFF.md`, `docs/WORK_QUEUE.md`, `main.py`,
`scripts/check_plugin_package.py`, `src/index.tsx`, `tests/test_decky_contract.py`
and generated `dist/index.js`/map. Resolve source deliberately and regenerate
the bundle. Review auto-merged command runner, backend RPC bindings, product and
index docs semantically. Preserve current compact badges, popup behavior and
one-minute refresh while adding TDP controls; combine all unload cancellation
and public RPC contracts.

Run the full backend/frontend/build/package matrix on the resolved integration.
Register only a clean tested completed tip. Follow `CHAT_COORDINATION.md` before
any packaging, with a plain unused version and immutable ZIP. This audit authorizes
no release, installation or hardware transition and changes no other checkout.
