from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.models import (  # noqa: E402
    Confidence,
    DisplayKind,
    DisplayObservation,
)
from regear.domain.saved_tv import (  # noqa: E402
    DEFAULT_MAX_ATTEMPTS,
    SavedTvProfile,
    SavedTvState,
    decide_saved_tv,
)


#: The TV a previous dock succeeded against, identified by its own EDID.
PROFILE = SavedTvProfile(
    display_stable_id="display:9f2c41ab77e0d135",
    edid_identified=True,
    label="Living room TV",
)

#: That same panel, on and corroborated.
TV = DisplayObservation(
    stable_id="display:9f2c41ab77e0d135",
    kind=DisplayKind.EXTERNAL,
    connector="HDMI-A-1",
    connected=True,
    active=False,
    edid_ready=True,
    confidence=Confidence.VERIFIED,
)

#: The handheld's own panel, always present and never the saved TV.
PANEL = DisplayObservation(
    stable_id="internal-panel",
    kind=DisplayKind.INTERNAL,
    connector="eDP-1",
    connected=True,
    active=True,
    edid_ready=True,
    confidence=Confidence.VERIFIED,
)


def decide(**over):
    request = {
        "profile": PROFILE,
        "displays": (PANEL, TV),
        "scan_complete": True,
    }
    request.update(over)
    return decide_saved_tv(**request)


class ReadyTests(unittest.TestCase):
    def test_the_saved_tv_present_and_verified_may_continue(self) -> None:
        decision = decide()

        self.assertIs(decision.state, SavedTvState.READY)
        self.assertTrue(decision.may_continue)
        self.assertEqual(decision.display_stable_id, PROFILE.display_stable_id)

    def test_no_saved_tv_is_not_a_failure(self) -> None:
        decision = decide(profile=None)

        self.assertIs(decision.state, SavedTvState.NONE)
        self.assertFalse(decision.may_continue)

    def test_the_decision_names_the_display_it_is_about(self) -> None:
        # A caller must not be able to act on a different display than the one
        # that was matched.
        for decision in (decide(), decide(displays=(PANEL,))):
            self.assertEqual(decision.display_stable_id, PROFILE.display_stable_id)
            self.assertEqual(decision.label, "Living room TV")


class WaitingTests(unittest.TestCase):
    def test_a_tv_not_yet_present_waits_with_the_egpu_half_already_done(self) -> None:
        decision = decide(displays=(PANEL,))

        self.assertIs(decision.state, SavedTvState.WAITING)
        self.assertEqual(decision.code, "saved_tv.awaiting_display")
        self.assertFalse(decision.may_continue)

    def test_a_connector_present_but_tv_switched_off_waits(self) -> None:
        decision = decide(displays=(PANEL, replace(TV, connected=False)))

        self.assertIs(decision.state, SavedTvState.WAITING)

    def test_another_tv_does_not_satisfy_the_saved_one(self) -> None:
        other = replace(TV, stable_id="display:0000000000000000")

        decision = decide(displays=(PANEL, other))

        self.assertIs(decision.state, SavedTvState.WAITING)


class BlindSwitchTests(unittest.TestCase):
    """Unknown, degraded or uncorroborated observation never switches a display."""

    def test_an_unreadable_connection_does_not_switch(self) -> None:
        decision = decide(displays=(PANEL, replace(TV, connected=None)))

        self.assertFalse(decision.may_continue)
        self.assertEqual(decision.code, "saved_tv.connection_unverified")

    def test_merely_observed_is_not_enough_to_switch(self) -> None:
        # OBSERVED is a reading nobody corroborated.
        for grade in (Confidence.OBSERVED, Confidence.UNKNOWN):
            with self.subTest(grade=grade):
                decision = decide(displays=(PANEL, replace(TV, confidence=grade)))

                self.assertFalse(decision.may_continue)
                self.assertEqual(decision.code, "saved_tv.connection_unverified")

    def test_a_saved_identity_reporting_as_internal_is_a_contradiction(self) -> None:
        decision = decide(displays=(PANEL, replace(TV, kind=DisplayKind.INTERNAL)))

        self.assertFalse(decision.may_continue)
        self.assertEqual(decision.code, "saved_tv.identity_contradicted")

    def test_a_connector_derived_profile_never_resumes_by_itself(self) -> None:
        # The identity names an HDMI socket, so a different TV plugged into it
        # would wear the same one. Present and verified is not enough.
        weak = replace(PROFILE, edid_identified=False)

        decision = decide(profile=weak)

        # Settled, not waiting: this is a property of the saved profile, so no
        # number of further looks can change it and pretending otherwise is the
        # endless "connecting..." this module exists to avoid.
        self.assertIs(decision.state, SavedTvState.SETTLED)
        self.assertEqual(decision.code, "saved_tv.identity_not_verifiable")
        self.assertFalse(decision.may_continue)

    def test_an_unverifiable_identity_settles_on_the_very_first_look(self) -> None:
        weak = replace(PROFILE, edid_identified=False)

        for attempts in (0, 1, DEFAULT_MAX_ATTEMPTS, DEFAULT_MAX_ATTEMPTS * 100):
            with self.subTest(attempts=attempts):
                decision = decide(profile=weak, attempts=attempts)

                self.assertIs(decision.state, SavedTvState.SETTLED)
                self.assertIsNot(decision.state, SavedTvState.WAITING)
                self.assertEqual(decision.code, "saved_tv.identity_not_verifiable")


class BoundedWaitingTests(unittest.TestCase):
    def test_waiting_settles_after_the_budget_rather_than_looping(self) -> None:
        decision = decide(displays=(PANEL,), attempts=DEFAULT_MAX_ATTEMPTS)

        self.assertIs(decision.state, SavedTvState.SETTLED)
        self.assertEqual(decision.code, "saved_tv.not_found")
        self.assertFalse(decision.may_continue)

    def test_one_look_short_of_the_budget_is_still_waiting(self) -> None:
        decision = decide(displays=(PANEL,), attempts=DEFAULT_MAX_ATTEMPTS - 1)

        self.assertIs(decision.state, SavedTvState.WAITING)

    def test_settling_keeps_the_reason_it_was_not_a_plain_absence(self) -> None:
        # "Did not find it" would be a lie about a contradicted identity, and
        # the player needs the real reason to act on it.
        decision = decide(
            displays=(PANEL, replace(TV, kind=DisplayKind.INTERNAL)),
            attempts=DEFAULT_MAX_ATTEMPTS,
        )

        self.assertIs(decision.state, SavedTvState.SETTLED)
        self.assertEqual(decision.code, "saved_tv.identity_contradicted")

    def test_a_settled_search_still_recognises_the_tv_when_it_appears(self) -> None:
        # Settling stops the looking, not the answering. A caller that reads
        # again with the TV present gets to continue.
        decision = decide(attempts=DEFAULT_MAX_ATTEMPTS * 10)

        self.assertIs(decision.state, SavedTvState.READY)


class UnfinishedLookTests(unittest.TestCase):
    def test_an_unfinished_look_is_not_an_absent_tv(self) -> None:
        decision = decide(scan_complete=False)

        self.assertIs(decision.state, SavedTvState.UNOBSERVABLE)
        self.assertEqual(decision.code, "saved_tv.display_scan_incomplete")
        self.assertFalse(decision.may_continue)

    def test_an_unfinished_look_cannot_settle_the_search(self) -> None:
        # Otherwise a reader that keeps failing exhausts the budget and gives
        # up on a TV that was there the whole time.
        decision = decide(scan_complete=False, attempts=DEFAULT_MAX_ATTEMPTS * 10)

        self.assertIs(decision.state, SavedTvState.UNOBSERVABLE)
        self.assertIsNot(decision.state, SavedTvState.SETTLED)


class ContractTests(unittest.TestCase):
    def test_only_ready_may_continue(self) -> None:
        decisions = [
            decide(),
            decide(profile=None),
            decide(displays=(PANEL,)),
            decide(scan_complete=False),
            decide(displays=(PANEL,), attempts=DEFAULT_MAX_ATTEMPTS),
            decide(profile=replace(PROFILE, edid_identified=False)),
            decide(displays=(PANEL, replace(TV, connected=None))),
        ]

        for decision in decisions:
            self.assertEqual(
                decision.may_continue,
                decision.state is SavedTvState.READY,
                decision.code,
            )

    def test_no_code_names_a_dock_or_a_television_model(self) -> None:
        # Nothing here is allowed to hard-code a product.
        decisions = [
            decide(),
            decide(profile=None),
            decide(displays=(PANEL,)),
            decide(scan_complete=False),
            decide(displays=(PANEL,), attempts=DEFAULT_MAX_ATTEMPTS),
            decide(profile=replace(PROFILE, edid_identified=False)),
            decide(displays=(PANEL, replace(TV, kind=DisplayKind.INTERNAL))),
        ]

        for decision in decisions:
            for word in ("gpd", "samsung", "sony", "bravia"):
                self.assertNotIn(word, decision.code.lower(), decision.code)


if __name__ == "__main__":
    unittest.main()
