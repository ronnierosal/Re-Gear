"""Pure, bounded assessment of one Re-Gear overhead measurement.

This is not a collector, a scheduler, a performance tuner, or proof that Re-Gear
has no game impact.  A future owner supplies one already-observed measurement.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import GameState
from .telemetry import (
    TelemetryAdmissionKind,
    TelemetryCollectionContract,
    TelemetryConsumer,
    admit_telemetry_collection,
)


MAX_MEASUREMENT_AGE_MS = 60_000


class OptionalObserverState(StrEnum):
    NOT_REQUESTED = "not_requested"
    OBSERVED = "observed"
    UNAVAILABLE = "unavailable"


class PerformanceMeasurementStatus(StrEnum):
    OBSERVED = "observed"
    DEFERRED = "deferred"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    STALE = "stale"


class GameImpactAssessment(StrEnum):
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class RegearOverheadObservation:
    """One identity-free timing sample from existing read-only work."""

    observed_at_monotonic_ms: int
    snapshot_cost_ms: int
    optional_observer_state: OptionalObserverState
    optional_observer_cost_ms: int | None = None

    def __post_init__(self) -> None:
        if self.observed_at_monotonic_ms < 0 or self.snapshot_cost_ms < 0:
            raise ValueError("performance observation time is invalid")
        if self.optional_observer_state is OptionalObserverState.OBSERVED:
            if self.optional_observer_cost_ms is None or self.optional_observer_cost_ms < 0:
                raise ValueError("observed optional cost is invalid")
        elif self.optional_observer_cost_ms is not None:
            raise ValueError("absent optional observer cannot expose a cost")

    @property
    def total_cost_ms(self) -> int:
        return self.snapshot_cost_ms + (self.optional_observer_cost_ms or 0)


@dataclass(frozen=True, slots=True)
class PerformanceMeasurementAssessment:
    status: PerformanceMeasurementStatus
    code: str
    total_cost_ms: int | None = None
    game_impact: GameImpactAssessment = GameImpactAssessment.UNKNOWN

    def __post_init__(self) -> None:
        if self.status is PerformanceMeasurementStatus.OBSERVED:
            if self.total_cost_ms is None:
                raise ValueError("observed performance assessment needs a cost")
        elif self.total_cost_ms is not None:
            raise ValueError("non-observed performance assessment cannot expose a cost")

    @property
    def authorizes_action(self) -> bool:
        """Measured overhead cannot authorize tuning, process, or device action."""
        return False


def assess_regear_overhead(
    observation: RegearOverheadObservation,
    contract: TelemetryCollectionContract,
    *,
    game_state: GameState,
    now_monotonic_ms: int,
) -> PerformanceMeasurementAssessment:
    """Assess one fresh caller-supplied sample under the existing budget gate."""

    if contract.consumer is not TelemetryConsumer.PLAYER_DIAGNOSTICS:
        return _insufficient("performance_measurement.consumer_not_diagnostics")
    admission = admit_telemetry_collection(contract, game_state)
    if admission.kind is TelemetryAdmissionKind.DEFER:
        return PerformanceMeasurementAssessment(
            PerformanceMeasurementStatus.DEFERRED, admission.reason
        )
    if admission.kind is TelemetryAdmissionKind.REJECT:
        return _insufficient(admission.reason)
    age_ms = now_monotonic_ms - observation.observed_at_monotonic_ms
    if age_ms < 0 or age_ms > MAX_MEASUREMENT_AGE_MS:
        return PerformanceMeasurementAssessment(
            PerformanceMeasurementStatus.STALE, "performance_measurement.stale"
        )
    if observation.optional_observer_state is OptionalObserverState.UNAVAILABLE:
        return _insufficient("performance_measurement.optional_observer_unavailable")
    if observation.total_cost_ms > contract.measured_collection_cost_ms:
        return _insufficient("performance_measurement.cost_exceeds_declared")
    return PerformanceMeasurementAssessment(
        PerformanceMeasurementStatus.OBSERVED,
        "performance_measurement.observed",
        observation.total_cost_ms,
    )


def performance_measurement_to_public_dict(
    assessment: PerformanceMeasurementAssessment,
) -> dict[str, object]:
    """Expose categorical result and Re-Gear cost only; never game or device identity."""

    payload: dict[str, object] = {
        "schema_version": 1,
        "status": assessment.status.value,
        "code": assessment.code,
        "game_impact": assessment.game_impact.value,
    }
    if assessment.total_cost_ms is not None:
        payload["total_cost_ms"] = assessment.total_cost_ms
    return payload


def _insufficient(code: str) -> PerformanceMeasurementAssessment:
    return PerformanceMeasurementAssessment(
        PerformanceMeasurementStatus.EVIDENCE_INSUFFICIENT, code
    )
