"""Concrete Auto session composition; construction does no collection or writes.

The host supplies current workload/render resolution and a justified sensor
configuration. The collection contract must describe a benchmark of this entire
composition, including dispatch revalidation; no benchmark is inferred here.
"""

from __future__ import annotations

import time
import re
from typing import Callable

from ..adapters.steamos.gamescope_performance import GamescopePerformanceReader
from ..adapters.steamos.auto_tdp_host import AutoTdpHostContext, AutoTdpHostDiscovery
from ..adapters.steamos.gamescope_performance_target import PerformanceTargetResolution
from ..adapters.steamos.tdp_sensors import TdpSensorDiscovery, TdpSensorInventory
from ..application.auto_tdp_session import AutoTdpActuator, AutoTdpSession
from ..domain.frame_time_window import FrameWindowPolicy
from ..domain.telemetry import TelemetryCollectionContract, TelemetryConsumer, TelemetryMetric
from ..ports.tdp import TdpProvider, TdpReading
from .auto_tdp_evidence import AutoTdpEligibility, AutoTdpEvidenceCollector
from .game_frame_collector import GameFrameCollector
from .tdp_sensor_readiness import TdpSensorReadinessConfig


class AutoTdpSessionFactory:
    def __init__(self, *, resolve: Callable[[], PerformanceTargetResolution],
                 eligibility: Callable[[], AutoTdpEligibility],
                 sensor_config: TdpSensorReadinessConfig,
                 host_context_key: str,
                 thermal_evidence_reference: str,
                 contract: TelemetryCollectionContract,
                 frame_policy: FrameWindowPolicy = FrameWindowPolicy(),
                 clock: Callable[[], float] = time.monotonic,
                 performance_reader: GamescopePerformanceReader | None = None,
                 sensors: Callable[[], TdpSensorInventory] | None = None,
                 host_context: Callable[[TdpReading], AutoTdpHostContext] | None = None):
        if (not isinstance(contract, TelemetryCollectionContract)
                or contract.consumer is not TelemetryConsumer.AUTO_TDP
                or TelemetryMetric.FPS not in contract.metrics):
            raise ValueError("Auto TDP needs a measured FPS collection contract")
        if not isinstance(sensor_config, TdpSensorReadinessConfig):
            raise ValueError("Auto TDP needs explicit sensor configuration")
        if not isinstance(host_context_key, str) or re.fullmatch(r"[0-9a-f]{64}", host_context_key) is None:
            raise ValueError("Auto TDP configuration needs an exact host context")
        if (not isinstance(thermal_evidence_reference, str)
                or not 1 <= len(thermal_evidence_reference) <= 256
                or not thermal_evidence_reference.strip()
                or any(ord(char) < 32 for char in thermal_evidence_reference)):
            raise ValueError("Auto TDP sensor policy needs its supporting evidence reference")
        if (not isinstance(frame_policy, FrameWindowPolicy)
                or contract.interval_ms > 60_000
                or contract.interval_ms + contract.measured_collection_cost_ms > frame_policy.maximum_gap_ms):
            raise ValueError("Collection cadence cannot sustain the frame window")
        self._resolve, self._eligibility = resolve, eligibility
        self._sensor_config, self._contract = sensor_config, contract
        self._frame_policy, self._clock = frame_policy, clock
        self._reader, self._sensors = performance_reader, sensors
        self._host_key = host_context_key
        self._thermal_reference = thermal_evidence_reference
        self._host_context = host_context or AutoTdpHostDiscovery().observe

    def _host_eligible(self, reading: TdpReading) -> bool:
        observed = self._host_context(reading)
        return (isinstance(observed, AutoTdpHostContext)
                and observed.code == "auto_tdp.host_context_observed"
                and observed.context_key == self._host_key)

    def create_evidence(self, provider: TdpProvider) -> AutoTdpEvidenceCollector:
        """Use the same complete composition for read-only benchmarking."""
        frames = GameFrameCollector(resolve=self._resolve,
            reader=self._reader or GamescopePerformanceReader(clock=self._clock),
            clock=self._clock, policy=self._frame_policy)
        return AutoTdpEvidenceCollector(provider=provider, frames=frames,
            resolve=self._resolve,
            sensors=self._sensors or TdpSensorDiscovery(clock=self._clock).scan,
            eligibility=self._eligibility, sensor_config=self._sensor_config,
            clock=self._clock, maximum_frame_age_ms=self._frame_policy.maximum_sample_age_ms,
            provider_eligible=self._host_eligible)

    def __call__(self, actuator: AutoTdpActuator, provider: TdpProvider) -> AutoTdpSession:
        evidence = self.create_evidence(provider)
        return AutoTdpSession(service=actuator, collect=evidence.collect,
            revalidate=evidence.revalidate, reset_collection=evidence.reset,
            game_state=lambda: self._eligibility().game_state,
            clock_ms=lambda: int(self._clock() * 1000), contract=self._contract)
