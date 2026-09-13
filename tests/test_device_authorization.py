"""When a Game Mode authorization prompt is honest, and when it is not.

Every branch is a refusal except one, so most of these are about which refusal
wins and why that order is right. The precedence matters more than it looks:
the prompt asks a player to grant a device direct access to system memory, so
anything unresolved has to lose to the refusal that names it.

Three of the inputs are tri-state, and the tests that matter most here are the
ones that pin ``None`` apart from ``False``. Each of those collapses is a
plausible-looking one-line bug -- an unreadable scan read as an empty port, an
unreadable enrolment database read as "not enrolled" -- and each would turn a
failed read into a confident answer given to the player.
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
        "intentional_disconnect": False,
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


class AnUnreadableScanIsNotAnEmptyPort(unittest.TestCase):
    def test_a_failed_scan_refuses_under_its_own_code(self):
        """None means the walk failed, so "nothing is attached" is unsupported."""
        self.assertEqual(
            assess(device_present=None).code,
            "device_authorization.scan_unreadable",
        )

    def test_a_failed_scan_is_distinct_from_an_absent_device(self):
        self.assertNotEqual(
            assess(device_present=None).code, assess(device_present=False).code
        )

    def test_an_unreadable_scan_outranks_absence_and_everything_after_it(self):
        """Nothing downstream is knowable when the scan itself did not happen."""
        result = assess(
            device_present=None,
            intentional_disconnect=True,
            identity_resolved=False,
            authorized=None,
            already_enrolled=None,
            already_offered=True,
        )
        self.assertEqual(result.code, "device_authorization.scan_unreadable")

    def test_an_unreadable_scan_never_offers(self):
        self.assertFalse(assess(device_present=None).offered)


class ADeliberateDisconnectIsNotAFirstPlug(unittest.TestCase):
    def test_a_deauthorized_still_cabled_dock_is_not_offered(self):
        """It reads exactly like a new attachment, and must not be treated as one."""
        self.assertEqual(
            assess(intentional_disconnect=True).code,
            "device_authorization.intentional_disconnect",
        )

    def test_it_is_answered_before_any_fact_about_the_device(self):
        """Identity, state and enrolment cannot change what the answer has to be."""
        for overrides in (
            {"identity_resolved": False},
            {"authorized": None},
            {"authorized": True},
            {"already_enrolled": None},
            {"already_enrolled": True},
            {"already_offered": True},
        ):
            with self.subTest(overrides=overrides):
                self.assertEqual(
                    assess(intentional_disconnect=True, **overrides).code,
                    "device_authorization.intentional_disconnect",
                )

    def test_it_beats_an_unnamed_device(self):
        """The disconnect explains this device better than its missing name does."""
        self.assertEqual(
            assess(intentional_disconnect=True, identity_resolved=False).code,
            "device_authorization.intentional_disconnect",
        )
        self.assertEqual(
            assess(intentional_disconnect=False, identity_resolved=False).code,
            "device_authorization.identity_unresolved",
        )

    def test_presence_still_outranks_it(self):
        """A flag about a device says nothing when there is no device."""
        self.assertEqual(
            assess(intentional_disconnect=True, device_present=False).code,
            "device_authorization.no_device",
        )
        self.assertEqual(
            assess(intentional_disconnect=True, device_present=None).code,
            "device_authorization.scan_unreadable",
        )

    def test_a_cleared_flag_asks_again(self):
        """The refusal belongs to the disconnect, not to the device."""
        self.assertFalse(assess(intentional_disconnect=True).offered)
        self.assertTrue(assess(intentional_disconnect=False).offered)

    def test_the_flag_cannot_be_forgotten(self):
        """Defaulting it to False would offer across a deliberate disconnect."""
        with self.assertRaises(TypeError):
            assess_device_authorization(
                device_present=True,
                identity_resolved=True,
                authorized=False,
                already_enrolled=False,
                already_offered=False,
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
            already_enrolled=None,
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

    def test_unreadable_state_also_outranks_unreadable_enrolment(self):
        result = assess(authorized=None, already_enrolled=None)
        self.assertEqual(result.code, "device_authorization.state_unreadable")


class UnreadableEnrolmentIsNotUnenrolled(unittest.TestCase):
    def test_unknown_enrolment_refuses_under_its_own_code(self):
        self.assertEqual(
            assess(already_enrolled=None).code,
            "device_authorization.enrollment_unreadable",
        )

    def test_unknown_never_falls_through_as_not_enrolled(self):
        """The dangerous collapse: offering to enrol what may already be stored."""
        self.assertTrue(assess(already_enrolled=False).offered)
        self.assertFalse(assess(already_enrolled=None).offered)
        self.assertNotEqual(
            assess(already_enrolled=None).code,
            assess(already_enrolled=False).code,
        )

    def test_unknown_is_distinct_from_known_enrolled(self):
        self.assertNotEqual(
            assess(already_enrolled=None).code,
            assess(already_enrolled=True).code,
        )

    def test_it_outranks_the_latch(self):
        result = assess(already_enrolled=None, already_offered=True)
        self.assertEqual(result.code, "device_authorization.enrollment_unreadable")

    def test_every_earlier_refusal_outranks_it(self):
        for overrides, expected in (
            ({"device_present": None}, "device_authorization.scan_unreadable"),
            ({"device_present": False}, "device_authorization.no_device"),
            (
                {"intentional_disconnect": True},
                "device_authorization.intentional_disconnect",
            ),
            (
                {"identity_resolved": False},
                "device_authorization.identity_unresolved",
            ),
            ({"authorized": None}, "device_authorization.state_unreadable"),
            ({"authorized": True}, "device_authorization.already_authorized"),
        ):
            with self.subTest(overrides=overrides):
                self.assertEqual(
                    assess(already_enrolled=None, **overrides).code, expected
                )


class OncePerAttachment(unittest.TestCase):
    def test_a_spent_offer_does_not_nag(self):
        self.assertEqual(
            assess(already_offered=True).code,
            "device_authorization.already_offered",
        )

    def test_the_latch_is_the_last_word(self):
        """Every refusal above it is more informative."""
        for overrides, expected in (
            ({"device_present": None}, "device_authorization.scan_unreadable"),
            ({"device_present": False}, "device_authorization.no_device"),
            (
                {"intentional_disconnect": True},
                "device_authorization.intentional_disconnect",
            ),
            (
                {"identity_resolved": False},
                "device_authorization.identity_unresolved",
            ),
            ({"authorized": None}, "device_authorization.state_unreadable"),
            ({"authorized": True}, "device_authorization.already_authorized"),
            (
                {"already_enrolled": None},
                "device_authorization.enrollment_unreadable",
            ),
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


class TheWholeOrderAtOnce(unittest.TestCase):
    """Lift one blocker at a time and the refusals must appear in this order.

    Written as a ladder rather than nine separate cases because the order is
    the contract: a reordering that still satisfies every isolated test --
    enrolment answered before authorization, say -- changes what the player is
    told and would pass everything above.
    """

    LADDER = (
        ({"device_present": None}, "device_authorization.scan_unreadable"),
        ({"device_present": False}, "device_authorization.no_device"),
        (
            {"device_present": True},
            "device_authorization.intentional_disconnect",
        ),
        (
            {"intentional_disconnect": False},
            "device_authorization.identity_unresolved",
        ),
        (
            {"identity_resolved": True},
            "device_authorization.state_unreadable",
        ),
        ({"authorized": True}, "device_authorization.already_authorized"),
        (
            {"authorized": False},
            "device_authorization.enrollment_unreadable",
        ),
        (
            {"already_enrolled": True},
            "device_authorization.already_enrolled",
        ),
        ({"already_enrolled": False}, "device_authorization.already_offered"),
        ({"already_offered": False}, "device_authorization.available"),
    )

    def test_each_refusal_uncovers_exactly_the_next_one(self):
        facts = {
            "device_present": None,
            "identity_resolved": False,
            "authorized": None,
            "already_enrolled": None,
            "already_offered": True,
            "intentional_disconnect": True,
        }
        for step, expected in self.LADDER:
            facts.update(step)
            with self.subTest(lifted=step, expected=expected):
                self.assertEqual(assess_device_authorization(**facts).code, expected)

    def test_the_ladder_ends_in_the_only_offer(self):
        self.assertEqual(self.LADDER[-1][1], "device_authorization.available")
        self.assertTrue(assess().offered)

    def test_every_code_is_distinct(self):
        """Two branches sharing a code would make a refusal unreadable in a log."""
        codes = [code for _, code in self.LADDER]
        self.assertEqual(len(codes), len(set(codes)))

    def test_only_the_final_step_is_offered(self):
        facts = {
            "device_present": None,
            "identity_resolved": False,
            "authorized": None,
            "already_enrolled": None,
            "already_offered": True,
            "intentional_disconnect": True,
        }
        for step, _ in self.LADDER[:-1]:
            facts.update(step)
            with self.subTest(lifted=step):
                result = assess_device_authorization(**facts)
                self.assertIs(
                    result.availability,
                    DeviceAuthorizationAvailability.UNAVAILABLE,
                )
                self.assertFalse(result.offered)


class Purity(unittest.TestCase):
    def test_the_same_facts_always_give_the_same_answer(self):
        self.assertEqual(assess(), assess())

    def test_the_assessment_is_frozen(self):
        result = assess()
        with self.assertRaises(Exception):
            result.code = "device_authorization.tampered"  # type: ignore[misc]

    def test_every_fact_is_keyword_only(self):
        """Positional facts are six booleans in a row, which is a bug waiting."""
        with self.assertRaises(TypeError):
            assess_device_authorization(True, True, False, False, False, False)

    def test_no_input_is_mutated_or_retained(self):
        facts = {
            "device_present": True,
            "identity_resolved": True,
            "authorized": False,
            "already_enrolled": False,
            "already_offered": False,
            "intentional_disconnect": False,
        }
        first = assess_device_authorization(**facts)
        second = assess_device_authorization(**facts)
        self.assertEqual(first, second)
        self.assertTrue(second.offered)


if __name__ == "__main__":
    unittest.main()
