"""Spending one prompt per attachment, and enrolling only on an explicit yes.

The behaviour worth protecting is not the happy path. It is that the state is
re-checked at the moment of acting rather than trusted from whenever the dialog
was drawn, and that nothing but an exact `True` gets past the confirmation --
because what this grants is direct access to system memory.
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


UUID = "b9010000-0072-741e-03c4-fed98ab0a808"

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
                svc, commands = service()
                outcome = svc.enroll(UUID, confirmed=value, **NEW_DOCK)
                self.assertFalse(outcome.requested)
                self.assertEqual(
                    outcome.code, "device_authorization.confirmation_required"
                )
                self.assertEqual(commands.calls, [])

    def test_falsy_values_are_refused_too(self):
        for value in (False, None, 0, ""):
            with self.subTest(confirmed=repr(value)):
                svc, commands = service()
                self.assertEqual(
                    svc.enroll(UUID, confirmed=value, **NEW_DOCK).code,
                    "device_authorization.confirmation_required",
                )
                self.assertEqual(commands.calls, [])

    def test_a_refused_confirmation_does_not_spend_the_offer(self):
        """Nothing happened, so the player can still be asked."""
        svc, _ = service()
        svc.enroll(UUID, confirmed=False, **NEW_DOCK)
        self.assertFalse(svc.offered)


class TheStateIsRecheckedWhenActing(unittest.TestCase):
    def _refused(self, expected, **changed):
        svc, commands = service()
        svc.note_offered()
        state = {**NEW_DOCK, **changed}
        outcome = svc.enroll(UUID, confirmed=True, **state)
        self.assertFalse(outcome.requested)
        self.assertEqual(outcome.code, expected)
        self.assertEqual(
            commands.calls, [], f"{changed!r} still reached boltd"
        )

    def test_a_dock_unplugged_since_the_prompt_refuses(self):
        self._refused("device_authorization.no_device", device_present=False)

    def test_a_dock_authorized_since_the_prompt_refuses(self):
        """Something else trusted it while the dialog sat there."""
        self._refused(
            "device_authorization.already_authorized", authorized=True
        )

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
        svc, commands = service()
        svc.note_offered()
        outcome = svc.enroll(UUID, confirmed=True, **NEW_DOCK)
        self.assertTrue(outcome.requested)
        self.assertEqual(commands.calls, [UUID])


class TheOutcomeIsHonest(unittest.TestCase):
    def test_it_reports_the_executor_result_and_names_the_device(self):
        svc, commands = service()
        outcome = svc.enroll(UUID, confirmed=True, **NEW_DOCK)
        self.assertTrue(outcome.requested)
        self.assertEqual(
            outcome.code, "device_authorization.enroll_accepted_unverified"
        )
        self.assertEqual(outcome.uuid, UUID)
        self.assertEqual(commands.calls, [UUID])

    def test_an_executor_failure_is_reported_as_itself(self):
        svc, _ = service(
            result=DeviceEnrollmentResult(
                False, "device_authorization.enroll_failed"
            )
        )
        outcome = svc.enroll(UUID, confirmed=True, **NEW_DOCK)
        self.assertFalse(outcome.requested)
        self.assertEqual(outcome.code, "device_authorization.enroll_failed")

    def test_an_executor_that_raises_is_a_failure_not_a_crash(self):
        svc, _ = service(raising=True)
        outcome = svc.enroll(UUID, confirmed=True, **NEW_DOCK)
        self.assertFalse(outcome.requested)
        self.assertEqual(
            outcome.code, "device_authorization.enroll_unavailable"
        )

    def test_an_empty_uuid_never_reaches_the_executor(self):
        for value in ("", None, 7):
            with self.subTest(uuid=repr(value)):
                svc, commands = service()
                outcome = svc.enroll(value, confirmed=True, **NEW_DOCK)
                self.assertEqual(
                    outcome.code, "device_authorization.uuid_invalid"
                )
                self.assertEqual(commands.calls, [])

    def test_acting_spends_the_offer_even_when_the_executor_fails(self):
        """A failed enrol should not re-prompt in a loop on the same dock."""
        svc, _ = service(
            result=DeviceEnrollmentResult(
                False, "device_authorization.enroll_failed"
            )
        )
        svc.enroll(UUID, confirmed=True, **NEW_DOCK)
        self.assertTrue(svc.offered)


if __name__ == "__main__":
    unittest.main()
