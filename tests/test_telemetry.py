from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.domain.models import GameState  # noqa: E402
from hdm.domain.telemetry import (  # noqa: E402
    TelemetryAdmissionKind,
    TelemetryCollectionContract,
    TelemetryConsumer,
    TelemetryMetric,
    TelemetryMetricSample,
    TelemetrySample,
    admit_telemetry_collection,
)


def contract(**changes: object) -> TelemetryCollectionContract:
    values: dict[str, object] = {
        "consumer": TelemetryConsumer.MODE_RECOMMENDATION,
        "metrics": (TelemetryMetric.FPS, TelemetryMetric.FRAME_TIME_MS),
        "interval_ms": 30_000,
        "measured_collection_cost_ms": 10,
        "benchmarked": True,
    }
    values.update(changes)
    return TelemetryCollectionContract(**values)  # type: ignore[arg-type]


class TelemetryAdmissionTests(unittest.TestCase):
    def test_auto_tdp_requires_explicit_enable_known_game_and_tighter_measured_budget(self):
        measured = contract(consumer=TelemetryConsumer.AUTO_TDP, interval_ms=1_000)
        for enabled in (False, None, 1, "true"):
            self.assertEqual(admit_telemetry_collection(measured, GameState.RUNNING, auto_tdp_enabled=enabled).kind, TelemetryAdmissionKind.REJECT)
        self.assertEqual(admit_telemetry_collection(measured, GameState.RUNNING, auto_tdp_enabled=True).kind, TelemetryAdmissionKind.ADMIT)
        for game in (GameState.IDLE, GameState.UNKNOWN, "running"):
            self.assertEqual(admit_telemetry_collection(measured, game, auto_tdp_enabled=True).kind, TelemetryAdmissionKind.DEFER)
        for changes in ({"benchmarked": False}, {"measured_collection_cost_ms": 11}):
            value = contract(consumer=TelemetryConsumer.AUTO_TDP, interval_ms=1_000, **changes)
            self.assertEqual(admit_telemetry_collection(value, GameState.RUNNING, auto_tdp_enabled=True).kind, TelemetryAdmissionKind.REJECT)
        self.assertEqual(admit_telemetry_collection(contract(), GameState.RUNNING, auto_tdp_enabled=True).kind, TelemetryAdmissionKind.DEFER)

    def test_contract_rejects_nonfinite_fractional_and_untyped_cost_evidence(self):
        for field in ("interval_ms", "measured_collection_cost_ms"):
            for value in (True, float("nan"), float("inf"), 1.5, "1000"):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    contract(**{field: value})
        for changes in ({"benchmarked": 1}, {"consumer": "auto_tdp"}, {"metrics": ("fps",)}):
            with self.assertRaises(ValueError):
                contract(**changes)

    def test_unbenchmarked_or_expensive_periodic_collection_is_rejected(self):
        unbenchmarked = admit_telemetry_collection(
            contract(benchmarked=False), GameState.IDLE
        )
        self.assertEqual(unbenchmarked.kind, TelemetryAdmissionKind.REJECT)
        self.assertEqual(unbenchmarked.reason, "telemetry.collection_cost_unbenchmarked")

        expensive = admit_telemetry_collection(
            contract(interval_ms=1_000, measured_collection_cost_ms=101), GameState.IDLE
        )
        self.assertEqual(expensive.kind, TelemetryAdmissionKind.REJECT)
        self.assertEqual(expensive.reason, "telemetry.collection_cost_exceeds_budget")

    def test_background_collection_defers_while_game_is_active(self):
        decision = admit_telemetry_collection(contract(), GameState.RUNNING)
        self.assertEqual(decision.kind, TelemetryAdmissionKind.DEFER)
        self.assertEqual(decision.defer_for_ms, 30_000)
        self.assertEqual(decision.reason, "runtime.game_active")

    def test_explicit_player_diagnostics_are_less_delayed_but_not_safety_work(self):
        decision = admit_telemetry_collection(
            contract(consumer=TelemetryConsumer.PLAYER_DIAGNOSTICS), GameState.RUNNING
        )
        self.assertEqual(decision.kind, TelemetryAdmissionKind.DEFER)
        self.assertEqual(decision.defer_for_ms, 5_000)

    def test_bounded_samples_require_unique_finite_non_negative_metrics(self):
        sample = TelemetrySample(
            50,
            (
                TelemetryMetricSample(TelemetryMetric.FPS, 60.0),
                TelemetryMetricSample(TelemetryMetric.POWER_WATTS, 20.0),
            ),
        )
        self.assertEqual(len(sample.metrics), 2)
        with self.assertRaisesRegex(ValueError, "unique"):
            TelemetrySample(
                50,
                (
                    TelemetryMetricSample(TelemetryMetric.FPS, 60.0),
                    TelemetryMetricSample(TelemetryMetric.FPS, 59.0),
                ),
            )
        with self.assertRaisesRegex(ValueError, "non-negative"):
            TelemetryMetricSample(TelemetryMetric.FPS, -1.0)


if __name__ == "__main__":
    unittest.main()
