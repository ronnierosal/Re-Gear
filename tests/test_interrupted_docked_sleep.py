from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.interrupted_docked_sleep import (  # noqa: E402
    MAX_CHECKPOINT_AGE_MS,
    DockedSleepCheckpoint,
    EvidenceState,
    InterruptedDockedSleepFact,
    PostWakeEvidence,
    assess_interrupted_docked_sleep,
)


class InterruptedDockedSleepTests(unittest.TestCase):
    def checkpoint(self, *, captured_at_ms=100):
        return DockedSleepCheckpoint("sleep-incident-1", captured_at_ms, True)

    def test_complete_post_wake_evidence_is_the_only_restored_handheld_claim(self):
        result = assess_interrupted_docked_sleep(
            self.checkpoint(),
            PostWakeEvidence(
                EvidenceState.ABSENT,
                EvidenceState.ABSENT,
                EvidenceState.VERIFIED,
                EvidenceState.VERIFIED,
                EvidenceState.VERIFIED,
            ),
            now_ms=101,
        )
        self.assertEqual(
            result.facts,
            (
                InterruptedDockedSleepFact.G1_MISSING_AFTER_SLEEP,
                InterruptedDockedSleepFact.GAME_SESSION_NOT_RUNNING,
                InterruptedDockedSleepFact.HANDHELD_RESTORED,
            ),
        )

    def test_missing_audio_or_input_never_claims_handheld_restored(self):
        result = assess_interrupted_docked_sleep(
            self.checkpoint(),
            PostWakeEvidence(
                EvidenceState.ABSENT,
                EvidenceState.UNKNOWN,
                EvidenceState.VERIFIED,
                EvidenceState.UNKNOWN,
                EvidenceState.VERIFIED,
            ),
            now_ms=101,
        )
        self.assertIn(InterruptedDockedSleepFact.G1_MISSING_AFTER_SLEEP, result.facts)
        self.assertIn(InterruptedDockedSleepFact.RECOVERY_INCOMPLETE_OR_UNKNOWN, result.facts)
        self.assertNotIn(InterruptedDockedSleepFact.HANDHELD_RESTORED, result.facts)

    def test_nonmatching_or_stale_checkpoint_is_not_an_incident(self):
        no_loss = assess_interrupted_docked_sleep(
            self.checkpoint(),
            PostWakeEvidence(*([EvidenceState.UNKNOWN] * 5)),
            now_ms=101,
        )
        self.assertEqual(no_loss.facts, ())
        stale = assess_interrupted_docked_sleep(
            self.checkpoint(),
            PostWakeEvidence(*([EvidenceState.ABSENT] * 5)),
            now_ms=100 + MAX_CHECKPOINT_AGE_MS + 1,
        )
        self.assertTrue(stale.stale)
        self.assertEqual(stale.facts, ())


if __name__ == "__main__":
    unittest.main()
