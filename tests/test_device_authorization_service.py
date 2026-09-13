"""Spending one prompt per attachment, and enrolling only on an explicit yes.

Three things are protected here.

**The state is re-checked when acting**, not trusted from whenever the dialog
was drawn -- a dock can be unplugged, replaced or trusted by something else
while a prompt sits on screen.

**Nothing but an exact `True` gets past the confirmation**, because what this
grants is direct access to system memory.

**The device is addressed by an opaque attachment token, never a hardware id.**
A router UUID is a hardware unique identifier and `SAFETY_INVARIANTS` #12 keeps
those out of payloads and diagnostics. The token is also what makes "bind the
confirmation to the same device" enforceable: a replug retires it.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.device_authorization import (  # noqa: E402
    DeviceAuthorizationService,
)
from regear.ports.device_authorization import (  # noqa: E402
    DeviceEnrollmentResult,
)


#: Synthetic. Real router UUIDs are hardware unique ids, and #12 keeps those out
#: of the repository as much as out of diagnostics.
UUID = "0a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d"

#: The state a brand-new dock arrives in.
NEW_DOCK = {
    "device_present": True,
    "identity_resolved": True,
    "authorized": False,
    "already_enrolled": False,
}


class FakeCommands:
    def __init__(self, result=None, raising=False):
        self.calls: list[str] = []
        self._result = result or DeviceEnrollmentResult(
            True, "device_authorization.enroll_accepted_unverified"
        )
        self._raising = raising

    def enroll(self, uuid):
        self.calls.append(uuid)
        if self._raising:
            raise OSError("boltctl exploded")
        return self._result


def service(**kwargs):
    commands = FakeCommands(**kwargs)
    return DeviceAuthorizationService(commands), commands


def armed(**kwargs):
    """A service holding a live token for the attached dock, as after a prompt."""
    svc, commands = service(**kwargs)
    return svc, commands, svc.candidate_token(UUID)


class TheOfferIsOncePerAttachment(unittest.TestCase):
    def test_a_new_dock_is_offered(self):
        svc, _ = service()
        self.assertTrue(svc.assess(**NEW_DOCK).offered)

    def test_showing_the_prompt_spends_it(self):
        """Spent by being shown, so declining does not let it reappear."""
        svc, _ = service()
        svc.note_offered()
        self.assertEqual(
            svc.assess(**NEW_DOCK).code, "device_authorization.already_offered"
        )

    def test_the_dock_going_away_re_arms_it(self):
        svc, _ = service()
        svc.note_offered()
        svc.observe_device(False)
        self.assertTrue(svc.assess(**NEW_DOCK).offered)

    def test_the_dock_staying_put_does_not_re_arm_it(self):
        svc, _ = service()
        svc.note_offered()
        svc.observe_device(True)
        self.assertFalse(svc.assess(**NEW_DOCK).offered)


class NothingButAnExactTrue(unittest.TestCase):
    def test_truthy_values_are_not_a_confirmation(self):
        for value in (1, "yes", "true", [1], {"ok": True}, object(), 1.0):
            with self.subTest(confirmed=repr(value)):
                svc, commands, token = armed()
                outcome = svc.enroll(token, confirmed=value, **NEW_DOCK)
                self.assertFalse(outcome.requested)
                self.assertEqual(
                    outcome.code, "device_authorization.confirmation_required"
                )
                self.assertEqual(commands.calls, [])

    def test_falsy_values_are_refused_too(self):
        for value in (False, None, 0, ""):
            with self.subTest(confirmed=repr(value)):
                svc, commands, token = armed()
                self.assertEqual(
                    svc.enroll(token, confirmed=value, **NEW_DOCK).code,
                    "device_authorization.confirmation_required",
                )
                self.assertEqual(commands.calls, [])

    def test_a_refused_confirmation_does_not_spend_the_offer(self):
        """Nothing happened, so the player can still be asked."""
        svc, _, token = armed()
        svc.enroll(token, confirmed=False, **NEW_DOCK)
        self.assertFalse(svc.offered)


class TheStateIsRecheckedWhenActing(unittest.TestCase):
    def _refused(self, expected, **changed):
        svc, commands, token = armed()
        svc.note_offered()
        outcome = svc.enroll(token, confirmed=True, **{**NEW_DOCK, **changed})
        self.assertFalse(outcome.requested)
        self.assertEqual(outcome.code, expected)
        self.assertEqual(commands.calls, [], f"{changed!r} still reached boltd")

    def test_a_dock_unplugged_since_the_prompt_refuses(self):
        self._refused("device_authorization.no_device", device_present=False)

    def test_a_dock_authorized_since_the_prompt_refuses(self):
        """Something else trusted it while the dialog sat there."""
        self._refused("device_authorization.already_authorized", authorized=True)

    def test_a_dock_enrolled_since_the_prompt_refuses(self):
        self._refused(
            "device_authorization.already_enrolled", already_enrolled=True
        )

    def test_an_identity_that_stopped_resolving_refuses(self):
        self._refused(
            "device_authorization.identity_unresolved", identity_resolved=False
        )

    def test_unreadable_state_refuses_rather_than_assuming_untrusted(self):
        self._refused("device_authorization.state_unreadable", authorized=None)

    def test_a_spent_offer_does_not_block_the_act_it_authorized(self):
        """The latch is why we are here; it must not be why we refuse."""
        svc, commands, token = armed()
        svc.note_offered()
        outcome = svc.enroll(token, confirmed=True, **NEW_DOCK)
        self.assertTrue(outcome.requested)
        self.assertEqual(commands.calls, [UUID])


class TheTokenBindsTheConfirmationToOneAttachment(unittest.TestCase):
    def test_it_is_stable_while_the_dock_stays_put(self):
        """A status poll must not make the card change identity."""
        svc, _ = service()
        first = svc.candidate_token(UUID)
        svc.observe_device(True)
        self.assertEqual(svc.candidate_token(UUID), first)

    def test_it_never_contains_the_hardware_id(self):
        svc, _ = service()
        token = svc.candidate_token(UUID)
        self.assertNotIn(UUID, token)
        self.assertNotIn(UUID.replace("-", ""), token)

    def test_a_replug_retires_it_and_mints_a_new_one(self):
        """This is what makes same-device binding enforceable, not hoped for."""
        svc, commands = service()
        stale = svc.candidate_token(UUID)
        svc.observe_device(False)
        fresh = svc.candidate_token(UUID)
        self.assertNotEqual(stale, fresh)
        self.assertEqual(
            svc.enroll(stale, confirmed=True, **NEW_DOCK).code,
            "device_authorization.token_stale",
        )
        self.assertEqual(commands.calls, [])

    def test_a_token_is_single_flight(self):
        """A double press must not enrol twice."""
        svc, commands, token = armed()
        self.assertTrue(svc.enroll(token, confirmed=True, **NEW_DOCK).requested)
        second = svc.enroll(token, confirmed=True, **NEW_DOCK)
        self.assertFalse(second.requested)
        self.assertEqual(second.code, "device_authorization.token_stale")
        self.assertEqual(commands.calls, [UUID])

    def test_a_stale_or_unknown_token_never_reaches_the_executor(self):
        for value in ("", None, 7, "deadbeef", UUID):
            with self.subTest(token=repr(value)):
                svc, commands, _ = armed()
                outcome = svc.enroll(value, confirmed=True, **NEW_DOCK)
                self.assertEqual(
                    outcome.code, "device_authorization.token_stale"
                )
                self.assertEqual(commands.calls, [])


class TheOutcomeIsHonest(unittest.TestCase):
    def test_it_reports_the_executor_result_and_names_the_token(self):
        svc, commands, token = armed()
        outcome = svc.enroll(token, confirmed=True, **NEW_DOCK)
        self.assertTrue(outcome.requested)
        self.assertEqual(
            outcome.code, "device_authorization.enroll_accepted_unverified"
        )
        self.assertEqual(outcome.token, token)
        # The executor still needs the real id; the OUTCOME must not carry it.
        self.assertEqual(commands.calls, [UUID])
        self.assertNotIn(UUID, outcome.token + outcome.code)

    def test_an_executor_failure_is_reported_as_itself(self):
        svc, _, token = armed(
            result=DeviceEnrollmentResult(
                False, "device_authorization.enroll_failed"
            )
        )
        outcome = svc.enroll(token, confirmed=True, **NEW_DOCK)
        self.assertFalse(outcome.requested)
        self.assertEqual(outcome.code, "device_authorization.enroll_failed")

    def test_an_executor_that_raises_is_a_failure_not_a_crash(self):
        svc, _, token = armed(raising=True)
        outcome = svc.enroll(token, confirmed=True, **NEW_DOCK)
        self.assertFalse(outcome.requested)
        self.assertEqual(outcome.code, "device_authorization.enroll_unavailable")

    def test_acting_spends_the_offer_even_when_the_executor_fails(self):
        """A failed enrol should not re-prompt in a loop on the same dock."""
        svc, _, token = armed(
            result=DeviceEnrollmentResult(
                False, "device_authorization.enroll_failed"
            )
        )
        svc.enroll(token, confirmed=True, **NEW_DOCK)
        self.assertTrue(svc.offered)


if __name__ == "__main__":
    unittest.main()
