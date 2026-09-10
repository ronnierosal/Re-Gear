from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.models import GameState  # noqa: E402
from regear.domain.runtime_budget import (  # noqa: E402
    RuntimeBudgetDecision,
    RuntimeBudgetDecisionKind,
    RuntimeWorkKind,
    decide_runtime_budget,
)


class RuntimeBudgetTests(unittest.TestCase):
    def test_safety_player_and_placement_work_remain_available_during_a_game(self):
        for work in (
            RuntimeWorkKind.TRANSITION_SAFETY,
            RuntimeWorkKind.EXPLICIT_PLAYER_REQUEST,
            RuntimeWorkKind.PLACEMENT_WATCH,
        ):
            with self.subTest(work=work):
                decision = decide_runtime_budget(work, GameState.RUNNING)
                self.assertEqual(decision.kind, RuntimeBudgetDecisionKind.RUN)
                self.assertEqual(decision.defer_for_ms, 0)

    def test_background_telemetry_is_deferred_while_game_is_active(self):
        decision = decide_runtime_budget(
            RuntimeWorkKind.BACKGROUND_TELEMETRY, GameState.RUNNING
        )
        self.assertEqual(decision.kind, RuntimeBudgetDecisionKind.DEFER)
        self.assertEqual(decision.defer_for_ms, 30_000)
        self.assertEqual(decision.reason, "runtime.game_active")

    def test_explicit_diagnostics_are_throttled_not_treated_as_safety_work(self):
        decision = decide_runtime_budget(
            RuntimeWorkKind.EXPLICIT_DIAGNOSTICS, GameState.RUNNING
        )
        self.assertEqual(decision.kind, RuntimeBudgetDecisionKind.DEFER)
        self.assertEqual(decision.defer_for_ms, 5_000)

    def test_unknown_game_state_defers_nonessential_work_fail_closed(self):
        decision = decide_runtime_budget(
            RuntimeWorkKind.BACKGROUND_TELEMETRY, GameState.UNKNOWN
        )
        self.assertEqual(decision.kind, RuntimeBudgetDecisionKind.DEFER)
        self.assertEqual(decision.reason, "runtime.game_state_unknown")

    def test_idle_work_runs_without_synthetic_delay(self):
        decision = decide_runtime_budget(
            RuntimeWorkKind.BACKGROUND_TELEMETRY, GameState.IDLE
        )
        self.assertEqual(decision.kind, RuntimeBudgetDecisionKind.RUN)
        self.assertEqual(decision.reason, "runtime.idle")

    def test_budget_contract_rejects_inconsistent_decisions(self):
        with self.assertRaisesRegex(ValueError, "delay"):
            RuntimeBudgetDecision(RuntimeBudgetDecisionKind.RUN, 1, "test")
        with self.assertRaisesRegex(ValueError, "positive"):
            RuntimeBudgetDecision(RuntimeBudgetDecisionKind.DEFER, 0, "test")


if __name__ == "__main__":
    unittest.main()
