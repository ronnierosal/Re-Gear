"""Replayable FPS-target APU power proposals; no collector, timer or actuator.

The caller supplies already-resolved bounds and one game-bound observation.
Values are configured watts, never measurements of consumed package power.
This policy supports internal rendering only. Delivery owns collection and writes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .models import GameState


def _positive(value: float) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        return False


@dataclass(frozen=True, slots=True)
class AutoTdpPolicy:
    minimum_watts: int
    maximum_watts: int
    target_fps: float
    deadband_fps: float = 2.0
    step_watts: int = 1
    settling_ms: int = 5_000
    maximum_sample_age_ms: int = 2_000
    missed_target_samples: int = 3
    stable_target_samples: int = 5

    def __post_init__(self) -> None:
        integers = (
            self.minimum_watts, self.maximum_watts, self.step_watts,
            self.settling_ms, self.maximum_sample_age_ms,
            self.missed_target_samples, self.stable_target_samples,
        )
        if any(type(value) is not int or value <= 0 for value in integers):
            raise ValueError("Auto TDP policy needs positive integer bounds")
        if self.minimum_watts > self.maximum_watts:
            raise ValueError("Auto TDP power bounds are reversed")
        if not _positive(self.target_fps) or not _positive(self.deadband_fps):
            raise ValueError("Auto TDP FPS values must be finite and positive")
        if self.deadband_fps >= self.target_fps:
            raise ValueError("Auto TDP deadband exceeds target")


@dataclass(frozen=True, slots=True)
class AutoTdpObservation:
    # Opaque workload/session identity, not an AppID or game title.
    context_key: str
    sampled_at_ms: int
    fps: float | None
    configured_watts: int | None
    game_state: GameState
    internal_render_verified: bool
    controller_owned: bool
    thermal_ready: bool
    power_source_ready: bool


@dataclass(frozen=True, slots=True)
class AutoTdpState:
    context_key: str = ""
    last_sample_ms: int = -1
    last_change_ms: int | None = None
    configured_watts: int | None = None
    missed_samples: int = 0
    stable_samples: int = 0
    increase_baseline_fps: float | None = None
    ineffective_increases: int = 0
    held_fps: float | None = None
    held_change_fps: float | None = None
    held_change_samples: int = 0


@dataclass(frozen=True, slots=True)
class AutoTdpDecision:
    state: AutoTdpState
    code: str
    proposed_watts: int | None = None

    @property
    def authorizes_action(self) -> bool:
        return False


def propose_auto_tdp(
    policy: AutoTdpPolicy,
    state: AutoTdpState,
    sample: AutoTdpObservation,
    *,
    now_ms: int,
) -> AutoTdpDecision:
    """One proposal from fresh samples; repeated/stale evidence never builds quorum.

    A proposal clears its streak and starts a settling window, but is not an
    acknowledgement. The caller must verify application separately. Observed
    setting changes also reset settling, including changes by another owner.
    """
    reset = AutoTdpState()
    if sample.game_state is not GameState.RUNNING:
        return AutoTdpDecision(reset, "auto_tdp.game_not_running")
    for ready, reason in (
        (sample.internal_render_verified, "render_unverified"),
        (sample.controller_owned, "ownership_unverified"),
        (sample.thermal_ready, "thermal_unverified"),
        (sample.power_source_ready, "power_source_unverified"),
    ):
        if ready is not True:
            return AutoTdpDecision(reset, f"auto_tdp.{reason}")
    if not sample.context_key or not isinstance(sample.context_key, str):
        return AutoTdpDecision(reset, "auto_tdp.context_unknown")
    if (
        type(now_ms) is not int or type(sample.sampled_at_ms) is not int
        or sample.sampled_at_ms < 0
        or not 0 <= now_ms - sample.sampled_at_ms <= policy.maximum_sample_age_ms
    ):
        return AutoTdpDecision(reset, "auto_tdp.sample_stale")
    if sample.fps is None or not _positive(sample.fps):
        return AutoTdpDecision(reset, "auto_tdp.fps_unavailable")
    watts = sample.configured_watts
    if type(watts) is not int or not policy.minimum_watts <= watts <= policy.maximum_watts:
        return AutoTdpDecision(reset, "auto_tdp.readback_invalid")
    baseline = AutoTdpState(sample.context_key, sample.sampled_at_ms, now_ms, watts)
    if sample.context_key != state.context_key:
        return AutoTdpDecision(baseline, "auto_tdp.context_settling")
    if sample.sampled_at_ms <= state.last_sample_ms:
        # Preserve the sample watermark, but break any decision streak.
        return AutoTdpDecision(
            replace(state, missed_samples=0, stable_samples=0),
            "auto_tdp.sample_repeated",
        )
    if watts != state.configured_watts:
        return AutoTdpDecision(baseline, "auto_tdp.readback_changed")
    if sample.sampled_at_ms - state.last_sample_ms > policy.maximum_sample_age_ms:
        return AutoTdpDecision(baseline, "auto_tdp.sample_gap")
    next_state = replace(state, last_sample_ms=sample.sampled_at_ms)
    if state.last_change_ms is None or now_ms < state.last_change_ms:
        return AutoTdpDecision(baseline, "auto_tdp.clock_reset")
    if now_ms - state.last_change_ms < policy.settling_ms:
        return AutoTdpDecision(
            replace(next_state, missed_samples=0, stable_samples=0),
            "auto_tdp.settling",
        )
    missed = sample.fps < policy.target_fps - policy.deadband_fps
    if state.held_fps is not None:
        if missed and abs(sample.fps - state.held_fps) <= policy.deadband_fps:
            return AutoTdpDecision(replace(next_state, missed_samples=0, stable_samples=0,
                                           held_change_fps=None, held_change_samples=0),
                                   "auto_tdp.no_performance_gain")
        count = state.held_change_samples + 1 if state.held_change_fps is not None and abs(sample.fps - state.held_change_fps) <= policy.deadband_fps else 1
        if count < policy.missed_target_samples:
            return AutoTdpDecision(replace(next_state, held_change_fps=sample.fps,
                                           held_change_samples=count), "auto_tdp.no_performance_gain")
        # Sustained changed evidence must still settle and earn a fresh streak.
        next_state = replace(next_state, held_fps=None, increase_baseline_fps=None,
                             ineffective_increases=0, missed_samples=0, stable_samples=0,
                             held_change_fps=None, held_change_samples=0, last_change_ms=now_ms)
        return AutoTdpDecision(next_state, "auto_tdp.context_settling")
    next_state = replace(
        next_state,
        missed_samples=state.missed_samples + 1 if missed else 0,
        stable_samples=0 if missed else state.stable_samples + 1,
    )
    proposed = None
    if next_state.missed_samples >= policy.missed_target_samples:
        ineffective = state.ineffective_increases
        if state.increase_baseline_fps is not None:
            ineffective = ineffective + 1 if sample.fps <= state.increase_baseline_fps + policy.deadband_fps else 0
        if ineffective >= 2:
            return AutoTdpDecision(replace(next_state, missed_samples=0, stable_samples=0,
                                           ineffective_increases=ineffective, held_fps=sample.fps),
                                   "auto_tdp.no_performance_gain")
        next_state = replace(next_state, increase_baseline_fps=sample.fps, ineffective_increases=ineffective)
        proposed = min(policy.maximum_watts, watts + policy.step_watts)
    elif next_state.stable_samples >= policy.stable_target_samples:
        next_state = replace(next_state, increase_baseline_fps=None, ineffective_increases=0, held_fps=None)
        proposed = max(policy.minimum_watts, watts - policy.step_watts)
    if proposed is None:
        return AutoTdpDecision(next_state, "auto_tdp.observing")
    next_state = replace(next_state, missed_samples=0, stable_samples=0, last_change_ms=now_ms)
    if proposed == watts:
        return AutoTdpDecision(next_state, "auto_tdp.at_bound")
    return AutoTdpDecision(next_state, "auto_tdp.proposal_requires_verification", proposed)
