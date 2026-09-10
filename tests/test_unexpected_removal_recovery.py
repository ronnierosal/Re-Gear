from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.models import GameState  # noqa: E402
from regear.domain.unexpected_removal_recovery import (  # noqa: E402
    GameOutcomeObservation,
    RecoveryFactState,
    UnexpectedRemovalFact,
    UnexpectedRemovalObservation,
    UnexpectedRemovalRecoveryState,
    assess_unexpected_removal_recovery,
)


def fact(value, generation="generation-1", sample_id="sample-1", verified=True):
    return UnexpectedRemovalFact(value, verified, generation, sample_id)


def observation(
    *,
    generation="generation-1",
    sample_id="sample-1",
    bridge=RecoveryFactState.PRESENT,
    topology=RecoveryFactState.PRESENT,
    display=RecoveryFactState.PRESENT,
    input=RecoveryFactState.PRESENT,
    audio=RecoveryFactState.PRESENT,
    game=GameState.IDLE,
    binding="g1-binding",
):
    return UnexpectedRemovalObservation(
        binding,
        generation,
        sample_id,
        fact(bridge, generation, sample_id),
        fact(topology, generation, sample_id),
        fact(display, generation, sample_id),
        fact(input, generation, sample_id),
        fact(audio, generation, sample_id),
        game,
    )


class UnexpectedRemovalRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.before = observation()
        self.after = observation(
            generation="generation-2",
            sample_id="sample-2",
            bridge=RecoveryFactState.ABSENT,
            topology=RecoveryFactState.ABSENT,
        )

    def assess(self, before=None, after=None):
        return assess_unexpected_removal_recovery(
            before or self.before,
            after or self.after,
            expected_attachment_binding="g1-binding",
            expected_generation="generation-1",
            expected_sample_id="sample-1",
        )

    def test_verified_loss_and_handheld_fallback_are_observed_not_actionable(self):
        result = self.assess()

        self.assertEqual(
            UnexpectedRemovalRecoveryState.PORTABLE_FALLBACK_VERIFIED, result.state
        )
        self.assertTrue(result.removal_detected)
        self.assertTrue(result.portable_fallback_verified)
        self.assertEqual(GameOutcomeObservation.STOPPED_OBSERVED, result.game_outcome)
        self.assertFalse(result.authorizes_action)

    def test_removal_is_detected_but_missing_fallback_is_recovery_incomplete(self):
        after = replace(
            self.after,
            internal_audio=fact(RecoveryFactState.ABSENT, "generation-2", "sample-2"),
        )
        result = self.assess(after=after)

        self.assertEqual(UnexpectedRemovalRecoveryState.RECOVERY_INCOMPLETE, result.state)
        self.assertEqual("unexpected_removal.portable_fallback_incomplete", result.code)
        self.assertTrue(result.removal_detected)
        self.assertFalse(result.portable_fallback_verified)

    def test_unknown_game_state_requires_supervised_diagnosis(self):
        result = self.assess(after=replace(self.after, game_state=GameState.UNKNOWN))

        self.assertEqual(
            UnexpectedRemovalRecoveryState.NEEDS_SUPERVISED_DIAGNOSIS, result.state
        )
        self.assertEqual("unexpected_removal.game_state_unknown", result.code)
        self.assertTrue(result.removal_detected)
        self.assertEqual(GameOutcomeObservation.UNKNOWN, result.game_outcome)

    def test_missing_display_input_or_audio_never_claims_portable_fallback(self):
        for name in ("internal_display", "builtin_input", "internal_audio"):
            with self.subTest(name=name):
                after = replace(
                    self.after,
                    **{name: fact(RecoveryFactState.ABSENT, "generation-2", "sample-2")},
                )
                result = self.assess(after=after)
                self.assertEqual(
                    UnexpectedRemovalRecoveryState.RECOVERY_INCOMPLETE, result.state
                )
                self.assertFalse(result.portable_fallback_verified)

    def test_stale_or_changed_generation_requires_supervised_diagnosis(self):
        stale_before = replace(self.before, generation="generation-old")
        stale = self.assess(before=stale_before)
        self.assertEqual("unexpected_removal.before_stale", stale.code)

        unchanged_after = replace(self.after, generation="generation-1")
        unchanged = self.assess(after=unchanged_after)
        self.assertEqual("unexpected_removal.after_not_fresh", unchanged.code)

    def test_changed_attachment_binding_requires_supervised_diagnosis(self):
        result = self.assess(after=replace(self.after, attachment_binding="other-binding"))

        self.assertEqual(
            UnexpectedRemovalRecoveryState.NEEDS_SUPERVISED_DIAGNOSIS, result.state
        )
        self.assertEqual("unexpected_removal.after_binding_changed", result.code)

    def test_contradictory_topology_requires_supervised_diagnosis(self):
        after = replace(
            self.after,
            bridge=fact(RecoveryFactState.ABSENT, "generation-2", "sample-2"),
            external_topology=fact(RecoveryFactState.PRESENT, "generation-2", "sample-2"),
        )
        result = self.assess(after=after)

        self.assertEqual(
            UnexpectedRemovalRecoveryState.NEEDS_SUPERVISED_DIAGNOSIS, result.state
        )
        self.assertEqual("unexpected_removal.topology_contradictory", result.code)


if __name__ == "__main__":
    unittest.main()
