from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.sleep_relaunch_eligibility import (  # noqa: E402
    ObservedGameSessionState,
    RelaunchPreference,
    SleepRelaunchEvidence,
    SleepRelaunchFact,
    SleepRelaunchOutcome,
    assess_sleep_relaunch_eligibility,
)


def fact(value, generation="generation-1", sample_id="sample-1", verified=True):
    return SleepRelaunchFact(value, verified, generation, sample_id)


def evidence(
    *,
    game=ObservedGameSessionState.STOPPED,
    generation="generation-1",
    sample_id="sample-1",
):
    return SleepRelaunchEvidence(
        "sleep-incident-binding",
        generation,
        sample_id,
        fact(True, generation, sample_id),
        fact(True, generation, sample_id),
        fact(True, generation, sample_id),
        fact(True, generation, sample_id),
        fact(False, generation, sample_id),
        fact(False, generation, sample_id),
        fact(False, generation, sample_id),
        fact(False, generation, sample_id),
        game,
    )


class SleepRelaunchEligibilityTests(unittest.TestCase):
    def assess(self, value=None, preference=RelaunchPreference.UNKNOWN):
        return assess_sleep_relaunch_eligibility(
            value or evidence(),
            expected_incident_binding="sleep-incident-binding",
            expected_generation="generation-1",
            expected_sample_id="sample-1",
            preference=preference,
        )

    def test_verified_recovery_prompts_on_first_eligible_use(self):
        result = self.assess()

        self.assertEqual(SleepRelaunchOutcome.PROMPT_PREFERENCE, result.outcome)
        self.assertEqual("sleep_relaunch.preference_required", result.code)
        self.assertFalse(result.authorizes_action)

    def test_verified_recovery_with_opt_in_is_future_flow_only(self):
        result = self.assess(preference=RelaunchPreference.OPTED_IN)

        self.assertEqual(
            SleepRelaunchOutcome.ELIGIBLE_FOR_FUTURE_RELAUNCH, result.outcome
        )
        self.assertFalse(result.authorizes_action)

    def test_opt_out_means_no_relaunch(self):
        result = self.assess(preference=RelaunchPreference.OPTED_OUT)

        self.assertEqual(SleepRelaunchOutcome.NO_RELAUNCH, result.outcome)

    def test_incomplete_handheld_recovery_is_explained_not_eligible(self):
        for name in ("handheld_display", "handheld_input", "handheld_audio"):
            with self.subTest(name=name):
                value = replace(evidence(), **{name: fact(False)})
                result = self.assess(value, RelaunchPreference.OPTED_IN)
                self.assertEqual(SleepRelaunchOutcome.EXPLAIN_RECOVERY, result.outcome)
                self.assertIn(name.removeprefix("handheld_").replace("input", "input"), result.code)

    def test_unknown_or_running_game_blocks_relaunch(self):
        for game in (ObservedGameSessionState.UNKNOWN, ObservedGameSessionState.RUNNING):
            with self.subTest(game=game):
                result = self.assess(evidence(game=game), RelaunchPreference.OPTED_IN)
                self.assertEqual(SleepRelaunchOutcome.EXPLAIN_RECOVERY, result.outcome)

    def test_each_risk_and_unknown_risk_blocks_relaunch(self):
        for name in (
            "update_risk",
            "cloud_sync_risk",
            "launch_risk",
            "repeat_failure_risk",
        ):
            for value, verified in ((True, True), (None, False)):
                with self.subTest(name=name, value=value):
                    result = self.assess(
                        replace(evidence(), **{name: fact(value, verified=verified)}),
                        RelaunchPreference.OPTED_IN,
                    )
                    self.assertEqual(SleepRelaunchOutcome.EXPLAIN_RECOVERY, result.outcome)

    def test_stale_changed_or_contradictory_evidence_blocks_relaunch(self):
        stale = replace(evidence(), generation="generation-old")
        self.assertEqual("sleep_relaunch.evidence_stale", self.assess(stale).code)

        changed = replace(evidence(), incident_binding="other-incident")
        self.assertEqual("sleep_relaunch.incident_binding_changed", self.assess(changed).code)

        inconsistent = replace(evidence(), handheld_audio=fact(True, sample_id="other-sample"))
        self.assertEqual("sleep_relaunch.evidence_inconsistent", self.assess(inconsistent).code)

    def test_unverified_sleep_recovery_blocks_relaunch(self):
        value = replace(evidence(), interrupted_docked_sleep=fact(None, verified=False))
        result = self.assess(value, RelaunchPreference.OPTED_IN)

        self.assertEqual(SleepRelaunchOutcome.EXPLAIN_RECOVERY, result.outcome)
        self.assertEqual("sleep_relaunch.interrupted_sleep_unverified", result.code)


if __name__ == "__main__":
    unittest.main()
