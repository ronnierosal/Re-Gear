"""What may be offered when the eGPU's PCIe link never trains.

The decision is small and every branch of it is a refusal, so the tests are
mostly about which refusal wins and why that order is the right one. The one
case that says yes is the one measured on hardware: transport present, PCI
never completed, readiness spent, nothing running.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.link_training_recovery import (  # noqa: E402
    LinkRecoveryAvailability,
    assess_link_recovery,
)
from regear.domain.models import GameState  # noqa: E402


def assess(**overrides):
    """The measured failure state, with one fact changed per test."""
    state = {
        "readiness_exhausted": True,
        "transport_present": True,
        "pci_complete": False,
        "game_state": GameState.IDLE,
        "attempted": False,
    }
    state.update(overrides)
    return assess_link_recovery(**state)


class TheMeasuredCase(unittest.TestCase):
    def test_offers_when_the_link_never_trained(self):
        """2026-09-11: 150s of no link, session stopped, Link Up 6.7s later."""
        result = assess()
        self.assertIs(result.availability, LinkRecoveryAvailability.OFFERED)
        self.assertEqual(result.code, "link_recovery.available")
        self.assertTrue(result.offered)


class NothingToRecover(unittest.TestCase):
    def test_complete_enumeration_is_not_a_failure(self):
        result = assess(pci_complete=True)
        self.assertFalse(result.offered)
        self.assertEqual(result.code, "link_recovery.pci_complete")

    def test_complete_enumeration_outranks_every_other_refusal(self):
        """A working link is not a game problem or a latch problem."""
        result = assess(
            pci_complete=True,
            transport_present=False,
            readiness_exhausted=False,
            game_state=GameState.RUNNING,
            attempted=True,
        )
        self.assertEqual(result.code, "link_recovery.pci_complete")

    def test_absent_transport_is_an_unplugged_cable_not_a_link_fault(self):
        result = assess(transport_present=False)
        self.assertFalse(result.offered)
        self.assertEqual(result.code, "link_recovery.transport_absent")

    def test_a_link_still_inside_its_window_is_left_alone(self):
        """One boot the same evening trained in 11.7s with no help at all."""
        result = assess(readiness_exhausted=False)
        self.assertFalse(result.offered)
        self.assertEqual(result.code, "link_recovery.readiness_not_exhausted")


class NeverOverAGame(unittest.TestCase):
    def test_a_running_game_refuses(self):
        result = assess(game_state=GameState.RUNNING)
        self.assertFalse(result.offered)
        self.assertEqual(result.code, "link_recovery.game_running")

    def test_unknown_game_state_fails_closed(self):
        result = assess(game_state=GameState.UNKNOWN)
        self.assertFalse(result.offered)
        self.assertEqual(result.code, "link_recovery.game_state_unknown")

    def test_a_running_game_outranks_the_latch(self):
        """The reason shown should be the one the player can act on."""
        result = assess(game_state=GameState.RUNNING, attempted=True)
        self.assertEqual(result.code, "link_recovery.game_running")

    def test_the_game_is_checked_only_once_there_is_a_real_failure(self):
        """Do not tell someone to close a game over a link that is fine."""
        result = assess(game_state=GameState.RUNNING, transport_present=False)
        self.assertEqual(result.code, "link_recovery.transport_absent")


class OncePerAttachment(unittest.TestCase):
    def test_a_spent_attempt_is_not_offered_again(self):
        result = assess(attempted=True)
        self.assertFalse(result.offered)
        self.assertEqual(result.code, "link_recovery.already_attempted")

    def test_the_latch_is_the_last_word_not_the_first(self):
        """Every refusal above it is more informative than the latch."""
        for overrides, expected in (
            ({"pci_complete": True}, "link_recovery.pci_complete"),
            ({"transport_present": False}, "link_recovery.transport_absent"),
            (
                {"readiness_exhausted": False},
                "link_recovery.readiness_not_exhausted",
            ),
            ({"game_state": GameState.RUNNING}, "link_recovery.game_running"),
        ):
            with self.subTest(overrides=overrides):
                self.assertEqual(
                    assess(attempted=True, **overrides).code, expected
                )


class Purity(unittest.TestCase):
    def test_the_same_facts_always_give_the_same_answer(self):
        """No hidden state: the caller owns the latch, not this module."""
        first = assess()
        second = assess()
        self.assertEqual(first, second)
        self.assertTrue(second.offered)

    def test_the_assessment_is_frozen(self):
        result = assess()
        with self.assertRaises(Exception):
            result.code = "link_recovery.tampered"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
