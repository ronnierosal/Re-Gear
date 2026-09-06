"""Compose existing read-only collectors for Auto TDP collection and dispatch.

Construction does not collect or authorize writes. Delivery must supply verified
internal-render eligibility, a profile-backed sensor policy and measured telemetry
admission before creating an enabled session. No fallback sensor policy exists.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Callable, Protocol

from ..adapters.steamos.gamescope_performance import PerformanceTarget
from ..adapters.steamos.gamescope_performance_target import PerformanceTargetResolution
from ..adapters.steamos.tdp_sensors import TdpSensorInventory
from ..application.auto_tdp_session import AutoTdpEvidence, AutoTdpLiveContext
from ..domain.auto_tdp import AutoTdpObservation
from ..domain.models import GameState
from ..ports.tdp import TdpProvider, TdpReading
from .game_frame_collector import FrameCollection
from .tdp_sensor_readiness import TdpSensorReadinessConfig, assess_tdp_sensor_readiness


@dataclass(frozen=True, slots=True)
class AutoTdpEligibility:
    game_state: GameState
    internal_render_verified: bool

    @property
    def ready(self) -> bool:
        return self.game_state is GameState.RUNNING and self.internal_render_verified is True


class FrameEvidenceSource(Protocol):
    def collect(self) -> FrameCollection: ...
    def reset(self) -> None: ...


@dataclass(frozen=True, slots=True)
class _LiveEvidence:
    target: PerformanceTarget
    reading: TdpReading
    power_source: str

    @property
    def context_key(self) -> str:
        # A power-source transition invalidates the old policy streak and any
        # pending proposal, even when the game and configured watts are unchanged.
        return hashlib.sha256((self.target.context_key + "\0" + self.power_source).encode()).hexdigest()


class AutoTdpEvidenceCollector:
    def __init__(self, *, provider: TdpProvider,
                 frames: FrameEvidenceSource,
                 resolve: Callable[[], PerformanceTargetResolution],
                 sensors: Callable[[], TdpSensorInventory],
                 eligibility: Callable[[], AutoTdpEligibility],
                 sensor_config: TdpSensorReadinessConfig,
                 clock: Callable[[], float], maximum_frame_age_ms: int,
                 provider_eligible: Callable[[TdpReading], bool] = lambda reading: True):
        if not isinstance(sensor_config, TdpSensorReadinessConfig):
            raise ValueError("Explicit sensor configuration is required")
        if type(maximum_frame_age_ms) is not int or maximum_frame_age_ms <= 0:
            raise ValueError("Explicit frame freshness is required")
        self._provider, self._frames, self._resolve = provider, frames, resolve
        self._sensors, self._eligibility = sensors, eligibility
        self._sensor_config, self._clock = sensor_config, clock
        self._maximum_frame_age_ms = maximum_frame_age_ms
        self._epoch: _LiveEvidence | None = None
        self._provider_eligible = provider_eligible

    def reset(self) -> None:
        """Session start calls this while collection is idle."""
        self._epoch = None
        self._frames.reset()

    def _unavailable(self) -> None:
        self.reset()
        return None

    def _eligible(self) -> bool:
        value = self._eligibility()
        return isinstance(value, AutoTdpEligibility) and value.ready

    def _target(self) -> PerformanceTarget | None:
        value = self._resolve()
        return value.target if isinstance(value, PerformanceTargetResolution) and value.ok else None

    def _reading(self) -> TdpReading | None:
        value = self._provider.observe()
        if (value.code != "tdp.ready" or not isinstance(value.reading, TdpReading)
                or self._provider_eligible(value.reading) is not True):
            return None
        return value.reading

    def _live(self) -> _LiveEvidence | None:
        if not self._eligible():
            return None
        target = self._target()
        if target is None:
            return None
        inventory = self._sensors()
        reading = self._reading()
        if reading is None or self._target() != target or not self._eligible():
            return None
        # Assess age after the slower provider/context reads, not at scan return.
        sensor = assess_tdp_sensor_readiness(inventory, self._sensor_config, now=self._clock())
        if sensor.code != "tdp.sensor_evidence_observed":
            return None
        return _LiveEvidence(target, reading, sensor.power_source)

    def collect(self) -> AutoTdpEvidence | None:
        try:
            before = self._live()
            if before is None:
                return self._unavailable()
            if before != self._epoch:
                self.reset()
                self._epoch = before
            frame = self._frames.collect()
            live = self._live()
            if (live != before or not isinstance(frame, FrameCollection)
                    or frame.context_key != before.target.context_key):
                return self._unavailable()
            if isinstance(frame, FrameCollection) and frame.code == "frames.warming":
                return None
            if not isinstance(frame, FrameCollection) or frame.code != "frames.estimated" or frame.sampled_fps is None:
                return self._unavailable()
            now = self._clock()
            if (type(now) not in (int, float) or not math.isfinite(now) or now < 0
                    or type(frame.newest_received_at_ms) is not int
                    or not 0 <= int(now * 1000) - frame.newest_received_at_ms <= self._maximum_frame_age_ms
                    or type(frame.sampled_fps) not in (int, float)
                    or not math.isfinite(frame.sampled_fps) or frame.sampled_fps <= 0):
                return self._unavailable()
            observation = AutoTdpObservation(live.context_key, frame.newest_received_at_ms,
                frame.sampled_fps, live.reading.sustained.current, GameState.RUNNING,
                True, True, True, True)
            return AutoTdpEvidence(observation, live.reading)
        except Exception:
            return self._unavailable()

    def revalidate(self) -> AutoTdpLiveContext | None:
        """Fresh eligibility, identity, sensor and readback checks; no frame query."""
        try:
            live = self._live()
            if live is None or live != self._epoch:
                self.reset()
            return AutoTdpLiveContext(live.context_key, live.reading) if live is not None else None
        except Exception:
            return self._unavailable()
