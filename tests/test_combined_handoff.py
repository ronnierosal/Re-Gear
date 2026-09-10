from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.combined_handoff import (  # noqa: E402
    CombinedHandoffEvidence,
    CombinedHandoffState,
    HandoffFact,
    assess_combined_handoff,
)
from regear.domain.models import GameState  # noqa: E402


def fact(value=True, verified=True, generation="generation-1", sample_id="sample-1"):
    return HandoffFact(value, verified, generation, sample_id)


def evidence(**changes):
    value = CombinedHandoffEvidence(
        attachment_binding="opaque-attach-1",
        generation="generation-1",
        sample_id="sample-1",
        game_state=GameState.IDLE,
        external_display_active=fact(),
        external_render_gpu=fact(),
        external_audio_active=fact(),
        external_controller_active=fact(),
        portable_display_rollback=fact(),
        portable_audio_rollback=fact(),
        builtin_controller_rollback=fact(),
    )
    return replace(value, **changes)


class CombinedHandoffTests(unittest.TestCase):
    def assess(self, value):
        return assess_combined_handoff(
            value,
            expected_attachment_binding="opaque-attach-1",
            expected_generation="generation-1",
            expected_sample_id="sample-1",
        )

    def test_complete_fresh_verified_evidence_is_non_authorizing_eligible(self):
        result = self.assess(evidence())

        self.assertEqual(result.state, CombinedHandoffState.ELIGIBLE)
        self.assertEqual(result.code, "handoff.eligible")
        self.assertEqual(result.eligibility.observed_generation, "generation-1")

    def test_incomplete_stale_and_contradictory_evidence_fails_closed(self):
        cases = (
            (evidence(external_audio_active=fact(None, False)), "handoff.external_audio_unverified"),
            (
                evidence(external_controller_active=fact(sample_id="other-sample")),
                "handoff.observation_stale_or_inconsistent",
            ),
            (
                evidence(external_render_gpu=fact(False, True)),
                "handoff.display_render_contradictory",
            ),
        )
        for value, code in cases:
            with self.subTest(code=code):
                result = self.assess(value)
                self.assertEqual(result.state, CombinedHandoffState.INELIGIBLE)
                self.assertEqual(result.code, code)
                self.assertIsNone(result.eligibility)

    def test_inactive_external_and_game_running_are_ineligible(self):
        for value, code in (
            (
                evidence(
                    external_display_active=fact(False, True),
                    external_render_gpu=fact(False, True),
                ),
                "handoff.external_display_inactive",
            ),
            (evidence(game_state=GameState.RUNNING), "handoff.game_running"),
        ):
            with self.subTest(code=code):
                result = self.assess(value)
                self.assertEqual(result.state, CombinedHandoffState.INELIGIBLE)
                self.assertEqual(result.code, code)

    def test_partial_attempt_requires_rollback_instead_of_eligibility(self):
        result = self.assess(
            evidence(
                external_audio_active=fact(False, True),
                handoff_attempted=True,
            )
        )

        self.assertEqual(result.state, CombinedHandoffState.ROLLBACK_REQUIRED)
        self.assertEqual(result.code, "handoff.rollback_required")
        self.assertIsNone(result.eligibility)

    def test_unknown_game_or_changed_attachment_is_never_eligible(self):
        for value, code in (
            (evidence(game_state=GameState.UNKNOWN), "handoff.game_state_unknown"),
            (evidence(attachment_binding="opaque-attach-2"), "handoff.attachment_changed"),
        ):
            with self.subTest(code=code):
                result = self.assess(value)
                self.assertEqual(result.state, CombinedHandoffState.INELIGIBLE)
                self.assertEqual(result.code, code)


if __name__ == "__main__":
    unittest.main()
