# System power management: proposed boundary

Status: architecture proposal, 2026-09-24. No runtime caller, idle power writer, device validation, or automatic enablement is delivered by this document. The Auto TDP primary owns changes to the power controller, telemetry admission, provider, writer lease, and restoration path. The Game Profile Engine owner owns its profile-side contract. Cross-owner interfaces require recorded agreement before wiring.

## Existing authority and evidence

The current `GameSessionObservationPort` reports `IDLE`, `RUNNING`, or `UNKNOWN`, with an exact Steam AppID only for a resolved running session. It does not establish Steam UI responsiveness, player input, a paused game, loading, shader compilation, or download activity. The existing Auto TDP session has explicit start/stop and one guarded TDP writer path. Its policy accepts a target FPS and fresh game-bound observations, waits for repeated misses or stability, proposes bounded watt changes, and holds after ineffective increases. It does not implement system idle power management or profile-driven activation.

`PerformancePlan` v2 separates the player's requested presentation rate, selected presentation rate, and `base_fps_target` (real game frames), with an opaque frame-generation reference. `GameOptimizationService.prepare_launch()` returns a launch outcome and observation binding, but does not expose a power objective or authorize Auto TDP. A plan is not evidence that settings landed, that a game is running, or that base frames can be measured.

The existing `GameFrameCollector` and `frame_time_window` explicitly estimate **presented-frame FPS**. `AutoTdpEvidenceCollector` passes that estimate into `AutoTdpObservation.fps`. This is not verified base-frame telemetry when frame generation is active. Until a game-bound base-frame source and its provenance are independently validated, no automatic base-FPS Auto TDP admission may be inferred from that collector under frame generation. Multiplying or dividing presented FPS by a nominal multiplier is not a measurement of base frame pacing.

## Proposed state and authority model

| State | Admission evidence | Policy request | Writer authority |
| --- | --- | --- | --- |
| Platform default | Unknown, degraded, disabled, missing telemetry, competing owner, or recovery | Revoke automatic admission and drain its worker. Stop retains the current verified limit; request baseline restoration separately only after journal, writer lease, and provider readback revalidate Re-Gear ownership. Otherwise report recovery-required without a write | Existing TDP owner only |
| UI candidate | Exact no-running-game observation **plus** independently validated UI activity and responsiveness evidence | Conservative UI-efficient request within observed hardware bounds | Future Auto TDP owner extension only |
| Game starting | Trusted launch transition and exact identity; no game-performance telemetry assumed | Request a separately guarded release of any UI restriction promptly, before game demand; report recovery-required without a write if ownership cannot be proved | Existing TDP owner only |
| Game active | Exact running identity, healthy mode, owned power path, valid profile binding, and verified base-frame evidence for the selected strategy | Maintain the admitted base objective; fast increase and slower decrease | Existing Auto TDP path only |
| Game exiting | Confirmed exit, with a settling interval for shutdown/background work | Stop automatic admission, then request separate guarded restoration; withhold any UI-efficient request if restoration is blocked | Existing TDP owner only |

These are policy states, not a second independent writer state machine. A request to restore does not assert that platform default was reached; the guarded operation must report its actual result. `IDLE` from the game-session port means no identified game; it is insufficient by itself to apply a low power limit. `UNKNOWN` is not treated as idle. Paused, background, loading, shader-compilation, download, and docked variants remain observation labels until a reliable source and a reviewed response exist. Do not lower TDP from an unverified pause or quiet scene. A mode change during play leaves graphics and frame-generation configuration for the next launch; the current game must not be restarted or interrupted.

## Small Game Profile Engine contract

The profile side should provide an immutable, read-only snapshot associated with one exact Steam AppID, mode, profile/plan version, context fingerprint, launch sequence, and observation binding. It should contain lifecycle phase, whether the game-owned settings durably landed, selected `target_display_fps`, `base_fps_target`, and opaque frame-generation provider/multiplier. Requested FPS is player intent, not the power target. The engine never commands watts or starts a power session. No snapshot is admitted from a passthrough, conflict, stale binding, unknown context, or untrusted plan.

The Auto TDP side decides whether to consume this snapshot. It must compare identity, mode, context, ownership, launch generation, current power bounds, and **measured base-frame provenance** at dispatch time. A `base_fps_target` is a target, not a measurement. `target_display_fps` and Gamescope presented FPS must not be substituted for base FPS when frame generation is active. Profile lock or a successful configuration write cannot start a stopped Auto TDP session. User opt-out first revokes automatic admission and drains the worker; stopping intentionally retains the current verified limit. Restoring the prior platform limit is a separate serialized `restore_tdp_limit()` or power-control-disable operation, allowed only when the journal, lease, and current provider readback still prove Re-Gear owns the applied state.

## Control policy to validate before implementation

Power-up should respond faster than power-down, while both use explicit dwell times and fresh independent samples. A single slow frame, loading transition, or shader-compilation spike should not teach a new efficiency setting. Treat thermal pressure, power-source changes, an external writer, missing readback, and game/context change as epoch boundaries: revoke automatic admission and reset evidence, then request restoration only if ownership and readback revalidate. An external change or uncertain journal/write must report recovery-required without overwriting the current setting. A CPU-bound classification or efficiency knee needs comparable measurements across scenes and real package/system power data. Configured watts are a limit, not consumed watts; do not infer total battery draw from APU TDP. Battery/AC may choose different reviewed objectives but AC is not automatic maximum power. Do not alter brightness, radios, refresh rate, or Gamescope limits in this slice.

No universal idle wattage, headroom value, base-FPS threshold, or polling frequency is justified yet. A future controller should take platform-observed legal bounds and reviewed policy parameters, reserve a UI responsiveness floor, and measure its own CPU, memory, wakeups, and battery cost. Process failure or writer-lease loss cannot itself restore a baseline. A recovery path must reacquire the lease, drain any worker, and fully revalidate the journal and provider readback before a restoration write; if it cannot, it reports recovery-required and writes nothing. This behavior must be demonstrated before any live low-power mode.

## Verification and release gates

Pure fake-clock tests should cover exact idle versus unknown, UI pressure and fast release on game start, slow power reduction, transient versus sustained demand, game exit, user disable, source/telemetry failure, writer failure, and context changes. Game tests must distinguish base 40 FPS from generated/presented 60 FPS; an FG plan with only presented telemetry must withhold automatic power tuning. Tests for CPU-bound and efficiency-knee decisions require explicit evidence inputs, not invented heuristics.

Supervised hardware validation is a later, separate gate: record the stock SteamOS menu and game baselines; measure UI responsiveness and total system draw; try one conservative UI limit with a separately verified restoration path; then separately evaluate game Auto TDP in quiet and demanding scenes. Review latency, frame pacing, thermal response, suspend/crash recovery, and controller overhead before considering unattended operation. No hardware power limit or configuration is changed by this architecture work.

## Sources and local contracts

- Re-Gear: `docs/AUTOMATIC_GAME_OPTIMIZATION.md`, `docs/AUTO_TDP_INDEPENDENT_PLAN.md`, `backend/regear/domain/auto_tdp.py`, `backend/regear/application/auto_tdp_session.py`, `backend/regear/delivery/auto_tdp_evidence.py`, `backend/regear/domain/frame_time_window.py`, `backend/regear/domain/performance_plan.py`, and `backend/regear/ports/game_session.py` at `6ef070bd`.
- [Gamescope upstream](https://github.com/ValveSoftware/gamescope): compositor and frame-limiting capability does not establish a Re-Gear game base-FPS source or UI-idle detector.
- [systemd logind session idle hint](https://wiki.freedesktop.org/www/Software/systemd/logind/): a session-provided idle hint; not evidence that SteamOS menus are responsive at a lower TDP or that a game is paused.
