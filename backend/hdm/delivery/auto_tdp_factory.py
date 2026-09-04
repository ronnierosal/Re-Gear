"""Concrete Auto session composition; construction does no collection or writes.

The host supplies current workload/render resolution and a justified sensor
configuration. The collection contract must describe a benchmark of this entire
composition, including dispatch revalidation; no benchmark is inferred here.
"""

from __future__ import annotations

import time
from typing import Callable

from ..adapters.steamos.gamescope_performance import GamescopePerformanceReader
from ..adapters.steamos.gamescope_performance_target import PerformanceTargetResolution
from ..adapters.steamos.tdp_sensors import TdpSensorDiscovery, TdpSensorInventory
from ..application.auto_tdp_session import AutoTdpActuator, AutoTdpSession
from ..domain.frame_time_window import FrameWindowPolicy
from ..domain.telemetry import TelemetryCollectionContract, TelemetryConsumer, TelemetryMetric
from ..ports.tdp import TdpProvider
from .auto_tdp_evidence import AutoTdpEligibility, AutoTdpEvidenceCollector
from .game_frame_collector import GameFrameCollector
from .tdp_sensor_readiness import TdpSensorReadinessConfig


class AutoTdpSessionFactory:
    def __init__(self, *, resolve: Callable[[], PerformanceTargetResolution],
                 eligibility: Callable[[], AutoTdpEligibility],
                 sensor_config: TdpSensorReadinessConfig,
                 contract: TelemetryCollectionContract,
                 frame_policy: FrameWindowPolicy = FrameWindowPolicy(),
                 clock: Callable[[], float] = time.monotonic,
                 performance_reader: GamescopePerformanceReader | None = None,
                 sensors: Callable[[], TdpSensorInventory] | None = None):
        if (not isinstance(contract, TelemetryCollectionContract)
                or contract.consumer is not TelemetryConsumer.AUTO_TDP
                or TelemetryMetric.FPS not in contract.metrics):
            raise ValueError("Auto TDP needs a measured FPS collection contract")
        if not isinstance(sensor_config, TdpSensorReadinessConfig):
            raise ValueError("Auto TDP needs explicit sensor configuration")
        if (not isinstance(frame_policy, FrameWindowPolicy)
                or contract.interval_ms > 60_000
                or contract.interval_ms + contract.measured_collection_cost_ms > frame_policy.maximum_gap_ms):
            raise ValueError("Collection cadence cannot sustain the frame window")
        self._resolve, self._eligibility = resolve, eligibility
        self._sensor_config, self._contract = sensor_config, contract
        self._frame_policy, self._clock = frame_policy, clock
        self._reader, self._sensors = performance_reader, sensors

    def create_evidence(self, provider: TdpProvider) -> AutoTdpEvidenceCollector:
        """Use the same complete composition for read-only benchmarking."""
        frames = GameFrameCollector(resolve=self._resolve,
            reader=self._reader or GamescopePerformanceReader(clock=self._clock),
            clock=self._clock, policy=self._frame_policy)
        return AutoTdpEvidenceCollector(provider=provider, frames=frames,
            resolve=self._resolve,
            sensors=self._sensors or TdpSensorDiscovery(clock=self._clock).scan,
            eligibility=self._eligibility, sensor_config=self._sensor_config,
            clock=self._clock, maximum_frame_age_ms=self._frame_policy.maximum_sample_age_ms)

    def __call__(self, actuator: AutoTdpActuator, provider: TdpProvider) -> AutoTdpSession:
        evidence = self.create_evidence(provider)
        return AutoTdpSession(service=actuator, collect=evidence.collect,
            revalidate=evidence.revalidate, reset_collection=evidence.reset,
            game_state=lambda: self._eligibility().game_state,
            clock_ms=lambda: int(self._clock() * 1000), contract=self._contract)
