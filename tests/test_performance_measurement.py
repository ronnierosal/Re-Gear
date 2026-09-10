from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.domain.models import GameState  # noqa: E402
from hdm.domain.performance_measurement import (  # noqa: E402
    GameImpactAssessment,
    RegearOverheadObservation,
    OptionalObserverState,
    PerformanceMeasurementStatus,
    assess_regear_overhead,
    performance_measurement_to_public_dict,
)
from hdm.domain.telemetry import (  # noqa: E402
    TelemetryCollectionContract,
    TelemetryConsumer,
    TelemetryMetric,
)


def contract(**changes):
    values = {
        "consumer": TelemetryConsumer.PLAYER_DIAGNOSTICS,
        "metrics": (TelemetryMetric.CPU_UTILIZATION,),
        "interval_ms": 30_000,
        "measured_collection_cost_ms": 20,
        "benchmarked": True,
    }
    values.update(changes)
    return TelemetryCollectionContract(**values)


def observation(**changes):
    values = {
        "observed_at_monotonic_ms": 100,
        "snapshot_cost_ms": 8,
        "optional_observer_state": OptionalObserverState.OBSERVED,
        "optional_observer_cost_ms": 7,
    }
    values.update(changes)
    return RegearOverheadObservation(**values)


class PerformanceMeasurementTests(unittest.TestCase):
    def assess(self, value=None, policy=None, game=GameState.IDLE, now=101):
        return assess_regear_overhead(
            value or observation(), policy or contract(), game_state=game, now_monotonic_ms=now
        )

    def test_bounded_fresh_existing_work_is_observed_without_game_impact_claim(self):
        result = self.assess()
        self.assertEqual(PerformanceMeasurementStatus.OBSERVED, result.status)
        self.assertEqual(15, result.total_cost_ms)
        self.assertEqual(GameImpactAssessment.UNKNOWN, result.game_impact)
        self.assertFalse(result.authorizes_action)

    def test_unbenchmarked_or_over_budget_cost_is_insufficient(self):
        for policy, code in (
            (contract(benchmarked=False), "telemetry.collection_cost_unbenchmarked"),
            (contract(interval_ms=1_000, measured_collection_cost_ms=101), "telemetry.collection_cost_exceeds_budget"),
            (contract(measured_collection_cost_ms=10), "performance_measurement.cost_exceeds_declared"),
        ):
            with self.subTest(code=code):
                result = self.assess(policy=policy)
                self.assertEqual(PerformanceMeasurementStatus.EVIDENCE_INSUFFICIENT, result.status)
                self.assertEqual(code, result.code)

    def test_running_or_unknown_game_defers_measurement(self):
        for game, reason in ((GameState.RUNNING, "runtime.game_active"), (GameState.UNKNOWN, "runtime.game_state_unknown")):
            with self.subTest(game=game):
                result = self.assess(game=game)
                self.assertEqual(PerformanceMeasurementStatus.DEFERRED, result.status)
                self.assertEqual(reason, result.code)

    def test_stale_and_optional_observer_absence_are_explicit(self):
        stale = self.assess(now=100 + 60_001)
        self.assertEqual(PerformanceMeasurementStatus.STALE, stale.status)

        unavailable = self.assess(
            observation(optional_observer_state=OptionalObserverState.UNAVAILABLE, optional_observer_cost_ms=None)
        )
        self.assertEqual(PerformanceMeasurementStatus.EVIDENCE_INSUFFICIENT, unavailable.status)
        self.assertEqual("performance_measurement.optional_observer_unavailable", unavailable.code)

    def test_non_diagnostic_consumer_cannot_use_the_measurement_report(self):
        result = self.assess(policy=contract(consumer=TelemetryConsumer.HEALTH))
        self.assertEqual(PerformanceMeasurementStatus.EVIDENCE_INSUFFICIENT, result.status)
        self.assertEqual("performance_measurement.consumer_not_diagnostics", result.code)

    def test_public_report_redacts_identity_and_omits_cost_when_not_observed(self):
        observed = performance_measurement_to_public_dict(self.assess())
        self.assertEqual(observed["total_cost_ms"], 15)
        self.assertEqual(observed["game_impact"], "unknown")
        rendered = repr(observed)
        for private in ("appid", "title", "account", "path", "device", "observed_at"):
            self.assertNotIn(private, rendered)

        deferred = performance_measurement_to_public_dict(self.assess(game=GameState.RUNNING))
        self.assertNotIn("total_cost_ms", deferred)


if __name__ == "__main__":
    unittest.main()
