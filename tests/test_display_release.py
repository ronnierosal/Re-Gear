from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.display_release import (  # noqa: E402
    DisplayReleaseDecision,
    DisplayReleaseEvidence,
    DisplayReleaseState,
    decide_display_release,
)


#: The state the tested Ally X is in after the return to the handheld: the eGPU
#: still driving CRTC 98, the internal panel driving its own, and nothing in
#: userspace holding the eGPU's card node.
HARDWARE = DisplayReleaseEvidence(
    external_committed=(98,),
    external_complete=True,
    internal_committed=True,
    client_holders=(),
    client_scan_complete=True,
)


class HardwareCaseTests(unittest.TestCase):
    def test_the_console_held_display_may_be_released_when_approved(self) -> None:
        decision = decide_display_release(HARDWARE, approved=True)

        self.assertIs(decision.state, DisplayReleaseState.PERMITTED)
        self.assertTrue(decision.permitted)
        self.assertEqual(decision.crtcs, (98,))
        self.assertFalse(decision.blocks_removal)

    def test_without_approval_the_substantive_facts_are_still_reported(self) -> None:
        """An operator running a plan needs to know what would have happened."""
        decision = decide_display_release(HARDWARE, approved=False)

        self.assertIs(decision.state, DisplayReleaseState.NOT_APPROVED)
        self.assertFalse(decision.permitted)
        self.assertEqual(decision.crtcs, ())

    def test_a_permitted_decision_names_exactly_the_committed_crtcs(self) -> None:
        evidence = replace(HARDWARE, external_committed=(98, 102))
        self.assertEqual(decide_display_release(evidence, approved=True).crtcs, (98, 102))


class ClientTests(unittest.TestCase):
    """The fact the whole safety argument rests on."""

    def test_a_client_holding_the_card_refuses_even_with_approval(self) -> None:
        """A committed mode with a client may be a player watching something."""
        evidence = replace(HARDWARE, client_holders=("gamescope-session.service",))
        decision = decide_display_release(evidence, approved=True)

        self.assertIs(decision.state, DisplayReleaseState.CLIENT_PRESENT)
        self.assertFalse(decision.permitted)
        self.assertTrue(decision.blocks_removal)

    def test_an_empty_holder_list_from_an_unfinished_scan_is_not_permission(
        self,
    ) -> None:
        """The fail-open this project removed elsewhere must not reappear here."""
        evidence = replace(HARDWARE, client_scan_complete=False)
        decision = decide_display_release(evidence, approved=True)

        self.assertIs(decision.state, DisplayReleaseState.EVIDENCE_INCOMPLETE)
        self.assertEqual(decision.code, "display_release.client_scan_incomplete")
        self.assertFalse(decision.permitted)

    def test_the_client_reason_is_reported_ahead_of_a_missing_approval(self) -> None:
        evidence = replace(HARDWARE, client_holders=("steam.service",))
        decision = decide_display_release(evidence, approved=False)
        self.assertIs(decision.state, DisplayReleaseState.CLIENT_PRESENT)


class EvidenceTests(unittest.TestCase):
    def test_an_unreadable_external_card_is_unknown_not_nothing_to_do(self) -> None:
        """Checked before the empty case, so it cannot read as not_needed."""
        evidence = replace(HARDWARE, external_complete=False, external_committed=())
        decision = decide_display_release(evidence, approved=True)

        self.assertIs(decision.state, DisplayReleaseState.EVIDENCE_INCOMPLETE)
        self.assertEqual(decision.code, "display_release.external_state_unknown")

    def test_a_card_driving_nothing_needs_no_release_and_blocks_no_removal(
        self,
    ) -> None:
        evidence = replace(HARDWARE, external_committed=())
        decision = decide_display_release(evidence, approved=True)

        self.assertIs(decision.state, DisplayReleaseState.NOT_NEEDED)
        self.assertFalse(decision.blocks_removal)
        # Nothing was released, so this must not read as a release having run.
        self.assertFalse(decision.permitted)


class InternalDisplayTests(unittest.TestCase):
    def test_the_player_is_never_left_without_a_display(self) -> None:
        for internal in (False, None):
            with self.subTest(internal=internal):
                evidence = replace(HARDWARE, internal_committed=internal)
                decision = decide_display_release(evidence, approved=True)

                self.assertIs(decision.state, DisplayReleaseState.NO_INTERNAL_DISPLAY)
                self.assertFalse(decision.permitted)
                self.assertTrue(decision.blocks_removal)


class InputTests(unittest.TestCase):
    def test_inputs_that_do_not_describe_a_reading_are_refused(self) -> None:
        for evidence, approved in (
            (HARDWARE, "yes"),
            ({"external_committed": (98,)}, True),
            (replace(HARDWARE, external_committed=[98]), True),
            (replace(HARDWARE, external_committed=("98",)), True),
            (replace(HARDWARE, client_holders=["steam"]), True),
            (replace(HARDWARE, client_holders=(98,)), True),
        ):
            with self.subTest(evidence=evidence, approved=approved):
                decision = decide_display_release(evidence, approved=approved)
                self.assertIs(decision.state, DisplayReleaseState.INVALID)
                self.assertFalse(decision.permitted)

    def test_a_decision_cannot_claim_crtcs_it_did_not_permit(self) -> None:
        with self.assertRaises(ValueError):
            DisplayReleaseDecision(DisplayReleaseState.PERMITTED, "code")
        with self.assertRaises(ValueError):
            DisplayReleaseDecision(DisplayReleaseState.CLIENT_PRESENT, "code", (98,))


if __name__ == "__main__":
    unittest.main()
