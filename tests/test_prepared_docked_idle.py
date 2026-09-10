from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.models import GameState  # noqa: E402
from regear.domain.prepared_docked_idle import (  # noqa: E402
    PREPARED_DOCKED_IDLE_MS,
    PreparedDockedIdleEvidence,
    PreparedDockedIdleState,
    assess_prepared_docked_idle,
    begin_prepared_docked_idle,
)


def evidence(**changes):
    value = PreparedDockedIdleEvidence(
        attachment_binding="opaque-attach-1",
        generation="generation-1",
        sample_id="sample-1",
        observed_at_monotonic_ms=10_000,
        game_state=GameState.IDLE,
        combined_handoff_eligible=True,
        evidence_generation="generation-1",
        evidence_sample_id="sample-1",
    )
    return replace(value, **changes)


class PreparedDockedIdleTests(unittest.TestCase):
    def window(self):
        started = begin_prepared_docked_idle(evidence())
        self.assertEqual(started.state, PreparedDockedIdleState.NOT_YET_STABLE)
        return started.window

    def test_just_under_exactly_and_over_five_seconds_are_deterministic(self):
        window = self.window()
        for elapsed, state, code in (
            (
                PREPARED_DOCKED_IDLE_MS - 1,
                PreparedDockedIdleState.NOT_YET_STABLE,
                "prepared_docked_idle.stabilizing",
            ),
            (
                PREPARED_DOCKED_IDLE_MS,
                PreparedDockedIdleState.PREPARED,
                "prepared_docked_idle.ready",
            ),
            (
                PREPARED_DOCKED_IDLE_MS + 1,
                PreparedDockedIdleState.PREPARED,
                "prepared_docked_idle.ready",
            ),
        ):
            with self.subTest(elapsed=elapsed):
                result = assess_prepared_docked_idle(
                    window,
                    evidence(
                        sample_id=f"sample-{elapsed}",
                        evidence_sample_id=f"sample-{elapsed}",
                        observed_at_monotonic_ms=10_000 + elapsed,
                    ),
                )
                self.assertEqual(result.state, state)
                self.assertEqual(result.code, code)

    def test_same_sample_never_becomes_prepared_even_after_interval(self):
        result = assess_prepared_docked_idle(
            self.window(),
            evidence(observed_at_monotonic_ms=20_000),
        )

        self.assertEqual(result.state, PreparedDockedIdleState.NOT_YET_STABLE)
        self.assertEqual(result.code, "prepared_docked_idle.observation_not_fresh")

    def test_activity_uncertainty_stale_evidence_and_binding_changes_invalidate(self):
        window = self.window()
        cases = (
            (evidence(game_state=GameState.RUNNING), "prepared_docked_idle.game_running"),
            (evidence(game_state=GameState.UNKNOWN), "prepared_docked_idle.game_state_unknown"),
            (evidence(combined_handoff_eligible=False), "prepared_docked_idle.evidence_stale_or_inconsistent"),
            (evidence(evidence_sample_id="other"), "prepared_docked_idle.evidence_stale_or_inconsistent"),
            (evidence(attachment_binding="opaque-attach-2"), "prepared_docked_idle.attachment_changed"),
            (evidence(generation="generation-2", evidence_generation="generation-2"), "prepared_docked_idle.generation_changed"),
        )
        for value, code in cases:
            with self.subTest(code=code):
                result = assess_prepared_docked_idle(window, value)
                self.assertEqual(result.state, PreparedDockedIdleState.INVALIDATED)
                self.assertEqual(result.code, code)
                self.assertIsNone(result.eligibility)

    def test_non_idle_evidence_cannot_start_a_window(self):
        result = begin_prepared_docked_idle(evidence(game_state=GameState.RUNNING))

        self.assertEqual(result.state, PreparedDockedIdleState.INVALIDATED)
        self.assertIsNone(result.window)


if __name__ == "__main__":
    unittest.main()
