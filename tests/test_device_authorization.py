"""When a Game Mode authorization prompt is honest, and when it is not.

Every branch is a refusal except one, so most of these are about which refusal
wins and why that order is right. The precedence matters more than it looks:
the prompt asks a player to grant a device direct access to system memory, so
anything unresolved has to lose to the refusal that names it.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.device_authorization import (  # noqa: E402
    DeviceAuthorizationAvailability,
    assess_device_authorization,
)


def assess(**overrides):
    """A newly attached, named, unauthorized, unenrolled device."""
    facts = {
        "device_present": True,
        "identity_resolved": True,
        "authorized": False,
        "already_enrolled": False,
        "already_offered": False,
    }
    facts.update(overrides)
    return assess_device_authorization(**facts)


class TheCaseWorthAsking(unittest.TestCase):
    def test_a_new_named_unauthorized_device_is_offered(self):
        result = assess()
        self.assertIs(
            result.availability, DeviceAuthorizationAvailability.OFFERED
        )
        self.assertEqual(result.code, "device_authorization.available")
        self.assertTrue(result.offered)


class NothingToAskAbout(unittest.TestCase):
    def test_no_device_is_not_a_question(self):
        self.assertEqual(
            assess(device_present=False).code, "device_authorization.no_device"
        )

    def test_an_authorized_device_needs_nothing(self):
        self.assertEqual(
            assess(authorized=True).code,
            "device_authorization.already_authorized",
        )

    def test_an_enrolled_device_is_boltds_business_not_a_second_enrolment(self):
        """Stored-but-unauthorized is real, and enrolling again does not fix it."""
        self.assertEqual(
            assess(already_enrolled=True).code,
            "device_authorization.already_enrolled",
        )


class AnUnnamedDeviceIsNeverOffered(unittest.TestCase):
    def test_unresolved_identity_refuses(self):
        """'Only authorize devices you trust' is unusable without a name."""
        self.assertEqual(
            assess(identity_resolved=False).code,
            "device_authorization.identity_unresolved",
        )

    def test_identity_outranks_every_later_refusal(self):
        """If we cannot say what it is, no other fact about it is worth showing."""
        result = assess(
            identity_resolved=False,
            authorized=None,
            already_enrolled=True,
            already_offered=True,
        )
        self.assertEqual(result.code, "device_authorization.identity_unresolved")

    def test_an_absent_device_still_outranks_an_unnamed_one(self):
        result = assess(device_present=False, identity_resolved=False)
        self.assertEqual(result.code, "device_authorization.no_device")


class UnreadableIsNotUnauthorized(unittest.TestCase):
    def test_none_refuses_rather_than_inventing_a_prompt(self):
        """None means the file could not be read. It is not a denial."""
        self.assertEqual(
            assess(authorized=None).code,
            "device_authorization.state_unreadable",
        )

    def test_unreadable_is_distinct_from_unauthorized(self):
        self.assertNotEqual(assess(authorized=None).code, assess().code)
        self.assertTrue(assess().offered)
        self.assertFalse(assess(authorized=None).offered)

    def test_unreadable_outranks_the_latch_and_enrolment(self):
        result = assess(
            authorized=None, already_enrolled=True, already_offered=True
        )
        self.assertEqual(result.code, "device_authorization.state_unreadable")


class OncePerAttachment(unittest.TestCase):
    def test_a_spent_offer_does_not_nag(self):
        self.assertEqual(
            assess(already_offered=True).code,
            "device_authorization.already_offered",
        )

    def test_the_latch_is_the_last_word(self):
        """Every refusal above it is more informative."""
        for overrides, expected in (
            ({"device_present": False}, "device_authorization.no_device"),
            (
                {"identity_resolved": False},
                "device_authorization.identity_unresolved",
            ),
            ({"authorized": None}, "device_authorization.state_unreadable"),
            ({"authorized": True}, "device_authorization.already_authorized"),
            (
                {"already_enrolled": True},
                "device_authorization.already_enrolled",
            ),
        ):
            with self.subTest(overrides=overrides):
                self.assertEqual(
                    assess(already_offered=True, **overrides).code, expected
                )

    def test_declining_does_not_blacklist_only_the_caller_can_re_arm(self):
        """The latch is the caller's; a fresh attachment clears it and asks again."""
        self.assertFalse(assess(already_offered=True).offered)
        self.assertTrue(assess(already_offered=False).offered)


class Purity(unittest.TestCase):
    def test_the_same_facts_always_give_the_same_answer(self):
        self.assertEqual(assess(), assess())

    def test_the_assessment_is_frozen(self):
        result = assess()
        with self.assertRaises(Exception):
            result.code = "device_authorization.tampered"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
