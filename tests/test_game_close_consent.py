from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.game_close_consent import (  # noqa: E402
    ConsentDecision,
    GameClosePreference,
    InterruptIntent,
    RunningGame,
    decide_game_close,
)
from regear.domain.game_compatibility import GameSaveCapability  # noqa: E402


#: The common case by a wide margin: a game that is running and that nobody has
#: submitted a reviewed save test for.
UNTESTED = RunningGame("1145360", "Hades", GameSaveCapability.UNTESTED)
AUTOSAVES = replace(
    UNTESTED, save_capability=GameSaveCapability.VERIFIED_TRIGGERABLE_AUTOSAVE
)
LOSES_PROGRESS = replace(
    UNTESTED, save_capability=GameSaveCapability.MANUAL_SAVE_REQUIRED
)

AGREED = GameClosePreference(
    "1145360", InterruptIntent.DISCONNECT, skip_confirmation=True
)


class NoGameTests(unittest.TestCase):
    def test_no_game_running_has_nothing_to_close(self) -> None:
        prompt = decide_game_close(InterruptIntent.DISCONNECT, None)

        self.assertIs(prompt.decision, ConsentDecision.NOTHING_TO_CLOSE)
        self.assertTrue(prompt.may_proceed_without_asking)
        self.assertIsNone(prompt.game)

    def test_nothing_to_close_offers_no_checkbox_to_remember(self) -> None:
        prompt = decide_game_close(InterruptIntent.SLEEP, None)

        self.assertFalse(prompt.remember_offered)
        self.assertFalse(prompt.relaunch_offered)

    def test_a_scan_that_did_not_finish_is_never_read_as_an_empty_screen(self) -> None:
        # The fail-open this codebase has already had to remove twice, in
        # another guise: not finding a game is only evidence when the looking
        # finished.
        prompt = decide_game_close(
            InterruptIntent.DISCONNECT, None, AGREED, scan_complete=False
        )

        self.assertIs(prompt.decision, ConsentDecision.CONFIRM)
        self.assertEqual(prompt.code, "game_close.scan_incomplete")
        self.assertFalse(prompt.may_proceed_without_asking)

    def test_an_unfinished_scan_offers_nothing_to_remember_or_reopen(self) -> None:
        prompt = decide_game_close(
            InterruptIntent.SLEEP, None, scan_complete=False
        )

        self.assertFalse(prompt.remember_offered)
        self.assertFalse(prompt.relaunch_offered)
        self.assertIsNone(prompt.game)

    def test_a_named_game_is_unaffected_by_the_scan_flag(self) -> None:
        # The game was found; whatever else the scan could not reach cannot
        # change what closing this one costs.
        prompt = decide_game_close(
            InterruptIntent.DISCONNECT, UNTESTED, AGREED, scan_complete=False
        )

        self.assertIs(prompt.decision, ConsentDecision.REMEMBERED)


class ConfirmationTests(unittest.TestCase):
    def test_a_running_game_is_confirmed_by_default(self) -> None:
        prompt = decide_game_close(InterruptIntent.DISCONNECT, UNTESTED)

        self.assertIs(prompt.decision, ConsentDecision.CONFIRM)
        self.assertFalse(prompt.may_proceed_without_asking)
        self.assertEqual(prompt.game, UNTESTED)

    def test_an_untested_game_says_the_catalog_does_not_know(self) -> None:
        # The default must not read as reassurance. A game nobody has tested is
        # a game Re-Gear cannot vouch for.
        prompt = decide_game_close(InterruptIntent.DISCONNECT, UNTESTED)

        self.assertFalse(prompt.save_known)
        self.assertFalse(prompt.progress_at_risk)

    def test_a_player_may_still_opt_out_for_a_game_nobody_has_tested(self) -> None:
        # Not knowing is not evidence of harm, and it is the player's game and
        # their save. Withholding the checkbox here would make the feature
        # useless until the community catalog fills up.
        prompt = decide_game_close(InterruptIntent.DISCONNECT, UNTESTED)

        self.assertTrue(prompt.remember_offered)

    def test_both_intents_ask_the_same_way(self) -> None:
        disconnect = decide_game_close(InterruptIntent.DISCONNECT, UNTESTED)
        sleep = decide_game_close(InterruptIntent.SLEEP, UNTESTED)

        self.assertEqual(disconnect.decision, sleep.decision)
        self.assertEqual(disconnect.remember_offered, sleep.remember_offered)
        self.assertEqual(disconnect.relaunch_offered, sleep.relaunch_offered)
        self.assertIs(disconnect.intent, InterruptIntent.DISCONNECT)
        self.assertIs(sleep.intent, InterruptIntent.SLEEP)


class IdentityTests(unittest.TestCase):
    def test_an_unidentified_game_is_always_confirmed(self) -> None:
        prompt = decide_game_close(
            InterruptIntent.DISCONNECT, replace(UNTESTED, identity_exact=False), AGREED
        )

        self.assertIs(prompt.decision, ConsentDecision.CONFIRM)
        self.assertEqual(prompt.code, "game_close.identity_unverified")

    def test_an_unidentified_game_is_not_offered_a_relaunch(self) -> None:
        # Reopening needs an app id that was actually established. Offering a
        # relaunch that cannot happen is a promise broken after the fact.
        prompt = decide_game_close(
            InterruptIntent.DISCONNECT, replace(UNTESTED, identity_exact=False)
        )

        self.assertFalse(prompt.relaunch_offered)

    def test_an_unidentified_game_cannot_be_remembered(self) -> None:
        prompt = decide_game_close(
            InterruptIntent.DISCONNECT, replace(UNTESTED, identity_exact=False)
        )

        self.assertFalse(prompt.remember_offered)


class RememberedConsentTests(unittest.TestCase):
    def test_a_standing_answer_for_this_game_skips_the_prompt(self) -> None:
        prompt = decide_game_close(InterruptIntent.DISCONNECT, UNTESTED, AGREED)

        self.assertIs(prompt.decision, ConsentDecision.REMEMBERED)
        self.assertTrue(prompt.may_proceed_without_asking)

    def test_a_stored_preference_that_was_not_ticked_still_asks(self) -> None:
        prompt = decide_game_close(
            InterruptIntent.DISCONNECT,
            UNTESTED,
            replace(AGREED, skip_confirmation=False),
        )

        self.assertIs(prompt.decision, ConsentDecision.CONFIRM)

    def test_consent_for_one_game_never_closes_another(self) -> None:
        # The failure this prevents: a player agrees once for a game with an
        # autosave, then loses an hour of a different game a week later.
        other = replace(UNTESTED, steam_app_id="220", title="Half-Life 2")

        prompt = decide_game_close(InterruptIntent.DISCONNECT, other, AGREED)

        self.assertIs(prompt.decision, ConsentDecision.CONFIRM)
        self.assertEqual(prompt.code, "game_close.preference_game_mismatch")

    def test_consent_to_sleep_is_not_consent_to_disconnect(self) -> None:
        # The two cost the player different things. Agreeing to the cheaper one
        # is not agreeing to the dearer one.
        prompt = decide_game_close(
            InterruptIntent.DISCONNECT,
            UNTESTED,
            replace(AGREED, intent=InterruptIntent.SLEEP),
        )

        self.assertIs(prompt.decision, ConsentDecision.CONFIRM)
        self.assertEqual(prompt.code, "game_close.preference_intent_mismatch")

    def test_a_mismatched_preference_carries_none_of_its_answers(self) -> None:
        # Not a near miss to be partially honoured: the relaunch box was ticked
        # about a different game.
        other = replace(UNTESTED, steam_app_id="220")

        prompt = decide_game_close(
            InterruptIntent.DISCONNECT,
            other,
            replace(AGREED, relaunch_after=True),
        )

        self.assertFalse(prompt.relaunch_requested)

    def test_a_remembered_relaunch_is_carried_through(self) -> None:
        prompt = decide_game_close(
            InterruptIntent.DISCONNECT,
            UNTESTED,
            replace(AGREED, relaunch_after=True),
        )

        self.assertIs(prompt.decision, ConsentDecision.REMEMBERED)
        self.assertTrue(prompt.relaunch_requested)


class ProgressAtRiskTests(unittest.TestCase):
    """The one case that overrides the player, and why.

    A prompt for a game with reviewed evidence of losing progress is not there
    to collect consent. It is there because it carries something the player has
    to act on at that moment -- save first -- and a box ticked last week cannot
    carry it.
    """

    def test_a_game_known_to_lose_progress_is_always_confirmed(self) -> None:
        prompt = decide_game_close(
            InterruptIntent.DISCONNECT, LOSES_PROGRESS, AGREED
        )

        self.assertIs(prompt.decision, ConsentDecision.CONFIRM)
        self.assertEqual(prompt.code, "game_close.progress_at_risk")
        self.assertTrue(prompt.progress_at_risk)

    def test_the_do_not_ask_again_box_is_not_offered_for_it(self) -> None:
        # If it cannot be offered it cannot be stored, so the stored skip above
        # can only be stale or written around this rule.
        prompt = decide_game_close(InterruptIntent.DISCONNECT, LOSES_PROGRESS)

        self.assertFalse(prompt.remember_offered)

    def test_a_game_with_no_reviewed_evidence_is_not_called_at_risk(self) -> None:
        # Untested is the absence of knowledge. Presenting it as danger would
        # train players to click through the warning that matters.
        prompt = decide_game_close(InterruptIntent.DISCONNECT, UNTESTED)

        self.assertFalse(prompt.progress_at_risk)

    def test_unsafe_unknown_counts_as_reviewed_evidence_of_loss(self) -> None:
        game = replace(UNTESTED, save_capability=GameSaveCapability.UNSAFE_UNKNOWN)

        prompt = decide_game_close(InterruptIntent.DISCONNECT, game, AGREED)

        self.assertIs(prompt.decision, ConsentDecision.CONFIRM)
        self.assertTrue(prompt.progress_at_risk)

    def test_a_game_verified_to_save_may_be_skipped(self) -> None:
        prompt = decide_game_close(InterruptIntent.DISCONNECT, AUTOSAVES, AGREED)

        self.assertIs(prompt.decision, ConsentDecision.REMEMBERED)
        self.assertTrue(prompt.save_known)
        self.assertFalse(prompt.progress_at_risk)

    def test_every_reviewed_save_outcome_lands_on_exactly_one_side(self) -> None:
        # A capability added later must be classified deliberately rather than
        # falling through to whichever branch happens to catch it.
        from regear.domain.game_close_consent import PROGRESS_AT_RISK, PROGRESS_SAFE

        self.assertEqual(PROGRESS_AT_RISK & PROGRESS_SAFE, frozenset())
        unclassified = (
            set(GameSaveCapability) - PROGRESS_AT_RISK - PROGRESS_SAFE
        )
        self.assertEqual(
            unclassified,
            {
                GameSaveCapability.UNTESTED,
                GameSaveCapability.MANUAL_SAVE_RECOMMENDED,
            },
        )


class RecommendedSaveTests(unittest.TestCase):
    def test_a_recommended_save_is_advice_not_a_veto(self) -> None:
        # The catalog says saving first is wise, not that closing destroys
        # progress. A player may still opt out of being asked.
        game = replace(
            UNTESTED, save_capability=GameSaveCapability.MANUAL_SAVE_RECOMMENDED
        )

        prompt = decide_game_close(InterruptIntent.DISCONNECT, game, AGREED)

        self.assertIs(prompt.decision, ConsentDecision.REMEMBERED)
        self.assertTrue(prompt.remember_offered)
        self.assertFalse(prompt.progress_at_risk)
        self.assertTrue(prompt.save_known)


if __name__ == "__main__":
    unittest.main()
