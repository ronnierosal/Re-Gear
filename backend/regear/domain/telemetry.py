"""Pure shared telemetry admission rules, with no collector or tuning authority."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from .models import GameState
from .runtime_budget import (
    RuntimeBudgetDecisionKind,
    RuntimeWorkKind,
    decide_runtime_budget,
)


class TelemetryMetric(StrEnum):
    FPS = "fps"
    FRAME_TIME_MS = "frame_time_ms"
    CPU_UTILIZATION = "cpu_utilization"
    GPU_UTILIZATION = "gpu_utilization"
    MEMORY_MIB = "memory_mib"
    VRAM_MIB = "vram_mib"
    POWER_WATTS = "power_watts"
    TEMPERATURE_C = "temperature_c"


class TelemetryConsumer(StrEnum):
    HEALTH = "health"
    PLAYER_DIAGNOSTICS = "player_diagnostics"
    MODE_RECOMMENDATION = "mode_recommendation"
    AUTO_TDP = "auto_tdp"


class TelemetryAdmissionKind(StrEnum):
    ADMIT = "admit"
    DEFER = "defer"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class TelemetryMetricSample:
    metric: TelemetryMetric
    value: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.value) or self.value < 0:
            raise ValueError("telemetry values must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class TelemetrySample:
    """One bounded sample from a future shared read-only collector."""

    observed_at_monotonic_ms: int
    metrics: tuple[TelemetryMetricSample, ...]

    def __post_init__(self) -> None:
        if self.observed_at_monotonic_ms < 0:
            raise ValueError("telemetry sample time is invalid")
        if not self.metrics or len(self.metrics) > len(TelemetryMetric):
            raise ValueError("telemetry sample metric set is invalid")
        names = tuple(sample.metric for sample in self.metrics)
        if len(names) != len(set(names)):
            raise ValueError("telemetry sample metrics must be unique")


@dataclass(frozen=True, slots=True)
class TelemetryCollectionContract:
    """Declared cost evidence required before any periodic collector is enabled."""

    consumer: TelemetryConsumer
    metrics: tuple[TelemetryMetric, ...]
    interval_ms: int
    measured_collection_cost_ms: int
    benchmarked: bool

    def __post_init__(self) -> None:
        if not isinstance(self.consumer, TelemetryConsumer) or type(self.benchmarked) is not bool:
            raise ValueError("telemetry consumer and benchmark evidence are invalid")
        if any(not isinstance(metric, TelemetryMetric) for metric in self.metrics):
            raise ValueError("telemetry contract metric identity is invalid")
        if not self.metrics or len(self.metrics) > len(TelemetryMetric):
            raise ValueError("telemetry contract metrics are invalid")
        if len(self.metrics) != len(set(self.metrics)):
            raise ValueError("telemetry contract metrics must be unique")
        if type(self.interval_ms) is not int or self.interval_ms < 1_000:
            raise ValueError("telemetry interval must be at least one second")
        if type(self.measured_collection_cost_ms) is not int or self.measured_collection_cost_ms <= 0:
            raise ValueError("telemetry collection cost must be positive")


@dataclass(frozen=True, slots=True)
class TelemetryAdmission:
    kind: TelemetryAdmissionKind
    defer_for_ms: int
    reason: str

    def __post_init__(self) -> None:
        if self.kind is TelemetryAdmissionKind.DEFER and self.defer_for_ms <= 0:
            raise ValueError("deferred telemetry requires a positive delay")
        if self.kind is not TelemetryAdmissionKind.DEFER and self.defer_for_ms:
            raise ValueError("non-deferred telemetry cannot have a delay")


def admit_telemetry_collection(
    contract: TelemetryCollectionContract, game_state: GameState, *,
    auto_tdp_enabled: bool = False,
) -> TelemetryAdmission:
    """Admit only measured, low-cost collection under the shared runtime budget.

    A future scheduler must own time and call this policy before each sample.
    This function does not start a loop, collect a counter, alter TDP, or make
    an optimization decision. A declared measurement budget may be conservative
    but must be independently benchmarked before enabling periodic collection.
    """
    if not contract.benchmarked:
        return TelemetryAdmission(
            TelemetryAdmissionKind.REJECT,
            0,
            "telemetry.collection_cost_unbenchmarked",
        )
    if contract.measured_collection_cost_ms * 10 > contract.interval_ms:
        return TelemetryAdmission(
            TelemetryAdmissionKind.REJECT,
            0,
            "telemetry.collection_cost_exceeds_budget",
        )
    if contract.consumer is TelemetryConsumer.AUTO_TDP:
        # Gameplay control is useful only during a known running workload. It
        # has a separate explicit opt-in; optional diagnostics remain deferred.
        # This admits collection only, never a power change or a scheduler.
        if auto_tdp_enabled is not True:
            return TelemetryAdmission(TelemetryAdmissionKind.REJECT, 0, "telemetry.auto_tdp_disabled")
        if game_state is not GameState.RUNNING:
            return TelemetryAdmission(TelemetryAdmissionKind.DEFER, 5_000, "telemetry.auto_tdp_game_not_running")
        if contract.measured_collection_cost_ms * 100 > contract.interval_ms:
            return TelemetryAdmission(TelemetryAdmissionKind.REJECT, 0, "telemetry.auto_tdp_cost_exceeds_budget")
        return TelemetryAdmission(TelemetryAdmissionKind.ADMIT, 0, "telemetry.auto_tdp_collection_admitted")
    work = (
        RuntimeWorkKind.EXPLICIT_DIAGNOSTICS
        if contract.consumer is TelemetryConsumer.PLAYER_DIAGNOSTICS
        else RuntimeWorkKind.BACKGROUND_TELEMETRY
    )
    budget = decide_runtime_budget(work, game_state)
    if budget.kind is RuntimeBudgetDecisionKind.DEFER:
        return TelemetryAdmission(
            TelemetryAdmissionKind.DEFER,
            budget.defer_for_ms,
            budget.reason,
        )
    return TelemetryAdmission(
        TelemetryAdmissionKind.ADMIT, 0, "telemetry.shared_budget_admitted"
    )
