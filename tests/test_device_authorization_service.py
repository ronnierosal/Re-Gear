"""Spending one prompt per attachment, and acting only on an explicit yes.

Five things are protected here.

**The state is re-checked when acting**, not trusted from whenever the dialog
was drawn -- a dock can be unplugged, replaced or trusted by something else
while a prompt sits on screen.

**The re-check has to be about the same dock.**  Fresh booleans carry no
identity: a true reading of a *different* device used to authorize the cached
one.  So the confirmation names the attachment generation and the observed
UUID, and is refused unless both match what the token was minted against.

**One attachment, one act.**  The token is consumed and its generation marked
spent, because clearing the token alone left the bound UUID behind and the next
poll minted a fresh one for the same dock -- two enrolments from one prompt.

**An unreadable scan is not an absence.**  A failed scan used to read as "the
dock went away", which re-armed the latch and brought the prompt back.

**The device is addressed by an opaque attachment token, never a hardware id.**
A router UUID is a hardware unique identifier and `SAFETY_INVARIANTS` #12 keeps
those out of payloads and diagnostics, so what this layer guarantees is the
enforceable half: it never copies the uuid into an outcome itself.  The
executor's result code, which arrives from outside, is repeated **unedited**.
The shape filter that used to refuse it by counting hex-class characters is
gone: it was blind to every non-hex encoding of the thing it was meant to stop,
and it refused precisely the codes worth reading -- a real diagnostic naming
what went wrong is long and dense, while the short generic codes this feature
emits itself always passed.

**A deliberate disconnect names the device it is about.**  Keying it to the
attachment generation was unfilable: the deauthorization itself makes the dock
read absent, that poll retires the attachment, and the report always arrived
one poll too late.  The tests for it start from an absence on purpose, because
that is the only state the owning layer can actually file from.  It is also
normalized, both when it is filed and when it is cleared, because the attached
identity it is compared against is case-folded: an uppercase report used to be
*accepted* and then match nothing.

**A payload's fields are read together or they are not read.**  `snapshot`
answers every field one payload needs under a single acquisition of the lock.
Serialising six reads is not the same as answering once, and the tests for that
race real threads, because six correct answers taken at six instants is exactly
the defect no sequential test can see.

The single-flight claim is tested against real threads at the bottom: a
sequential double press proves the token is consumable, not that two presses
racing cannot both reach `boltd`.  A report racing a poll is tested the same
way, three hundred rounds of it, because the read-then-file pair it replaced
lost three reports in three hundred and every sequential test passed.
"""

from __future__ import annotations

import inspect
import sys
import threading
import time
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


#: Obviously synthetic. Real router UUIDs are hardware unique ids, and #12 keeps
#: those out of the repository as much as out of diagnostics. Shaped like the
#: real thing only so the fixtures exercise the same string handling.
DOCK = "11111111-1111-4111-8111-111111111111"
OTHER_DOCK = "22222222-2222-4222-8222-222222222222"
#: One with hex *letters* in it, for the tests about how an id is spelled.
#: `DOCK` is all digits, so upper-casing it changes nothing at all and a
#: case test written against it passes on code that ignores case entirely.
LETTERED_DOCK = "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d"

#: The state a brand-new dock arrives in.
NEW_DOCK = {
    "device_present": True,
    "identity_resolved": True,
    "authorized": False,
    "already_enrolled": False,
}

ACCEPTED = "device_authorization.enroll_accepted_unverified"


class FakeCommands:
    """Records what reached `boltd`, and whether two calls ever overlapped."""

    def __init__(self, result=None, raising=False, delay=0.0):
        self.calls: list[tuple[str, str]] = []
        self._result = result or DeviceEnrollmentResult(True, ACCEPTED)
        self._raising = raising
        self._delay = delay
        self._guard = threading.Lock()
        self._inside = 0
        self.max_overlap = 0

    def enroll(self, uuid):
        return self._act("enroll", uuid)

    def authorize(self, uuid):
        return self._act("authorize", uuid)

    def _act(self, action, uuid):
        with self._guard:
            self.calls.append((action, uuid))
            self._inside += 1
            self.max_overlap = max(self.max_overlap, self._inside)
        try:
            if self._delay:
                time.sleep(self._delay)
            if self._raising:
                raise OSError("boltctl exploded")
            return self._result
        finally:
            with self._guard:
                self._inside -= 1


class EnrollOnlyCommands:
    """The runner that exists today: the Protocol widened, it did not."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def enroll(self, uuid):
        self.calls.append(("enroll", uuid))
        return DeviceEnrollmentResult(True, ACCEPTED)


def service(**kwargs):
    commands = FakeCommands(**kwargs)
    return DeviceAuthorizationService(commands), commands


def armed(uuid=DOCK, **kwargs):
    """A service holding a live token for an attached dock, as after a prompt."""
    svc, commands = service(**kwargs)
    svc.observe_attachment(present=True, uuid=uuid)
    return svc, commands, svc.candidate_token(uuid)


def confirm(svc, token, **overrides):
    """Confirm with facts that describe the attachment unless told otherwise."""
    call = {
        "consent": True,
        "action": "enroll",
        "uuid": DOCK,
        "generation": svc.generation,
        **NEW_DOCK,
        **overrides,
    }
    return svc.confirm(token, **call)


class TheOfferIsOncePerAttachment(unittest.TestCase):
    def test_a_new_dock_is_offered(self):
        svc, _ = service()
        self.assertTrue(svc.assess(**NEW_DOCK).offered)

    def test_acknowledging_the_prompt_spends_it(self):
        """Spent by being shown, so declining does not let it reappear."""
        svc, _, token = armed()
        self.assertTrue(svc.acknowledge(token))
        self.assertEqual(
            svc.assess(**NEW_DOCK).code, "device_authorization.already_offered"
        )

    def test_reading_the_state_never_spends_it(self):
        """A status poll is not the player being asked."""
        svc, _, token = armed()
        for _ in range(5):
            svc.assess(**NEW_DOCK)
            self.assertEqual(svc.candidate_token(DOCK), token)
        self.assertTrue(svc.assess(**NEW_DOCK).offered)
        self.assertFalse(svc.offered)

    def test_an_unknown_token_acknowledges_nothing(self):
        svc, _, _ = armed()
        for value in ("", None, 7, "deadbeef", DOCK):
            with self.subTest(token=repr(value)):
                self.assertFalse(svc.acknowledge(value))
                self.assertFalse(svc.offered)

    def test_the_dock_going_away_re_arms_it(self):
        svc, _, token = armed()
        svc.acknowledge(token)
        svc.observe_attachment(present=False, uuid="")
        self.assertTrue(svc.assess(**NEW_DOCK).offered)

    def test_the_dock_staying_put_does_not_re_arm_it(self):
        svc, _, token = armed()
        svc.acknowledge(token)
        svc.observe_attachment(present=True, uuid=DOCK)
        self.assertFalse(svc.assess(**NEW_DOCK).offered)

    def test_a_replacement_dock_is_a_new_attachment(self):
        """A swap is not the same device deciding it wants asking again."""
        svc, _, token = armed()
        svc.acknowledge(token)
        svc.observe_attachment(present=True, uuid=OTHER_DOCK)
        self.assertTrue(svc.assess(**NEW_DOCK).offered)
        self.assertNotEqual(svc.candidate_token(OTHER_DOCK), token)

    def test_declining_suppresses_this_attachment_only(self):
        svc, commands, token = armed()
        self.assertTrue(svc.decline(token))
        self.assertEqual(
            svc.assess(**NEW_DOCK).code, "device_authorization.already_offered"
        )
        self.assertEqual(svc.candidate_token(DOCK), "")
        # No blacklist: unplug, plug back in, and the offer returns.
        svc.observe_attachment(present=False, uuid="")
        svc.observe_attachment(present=True, uuid=DOCK)
        self.assertTrue(svc.assess(**NEW_DOCK).offered)
        self.assertNotEqual(svc.candidate_token(DOCK), "")
        self.assertEqual(commands.calls, [])

    def test_declining_an_unknown_token_spends_nothing(self):
        svc, _, token = armed()
        self.assertFalse(svc.decline("deadbeef"))
        self.assertFalse(svc.offered)
        self.assertEqual(svc.candidate_token(DOCK), token)


class AnUnreadableScanIsNotAnAbsence(unittest.TestCase):
    """The reproduced defect: a failed scan re-armed the prompt."""

    def test_an_unreadable_scan_does_not_re_arm_the_prompt(self):
        svc, _, token = armed()
        svc.acknowledge(token)
        svc.observe_attachment(present=None, uuid="")
        self.assertEqual(
            svc.assess(**NEW_DOCK).code, "device_authorization.already_offered"
        )

    def test_an_unreadable_scan_keeps_the_token_and_the_generation(self):
        svc, _, token = armed()
        generation = svc.generation
        svc.observe_attachment(present=None, uuid="")
        self.assertEqual(svc.candidate_token(DOCK), token)
        self.assertEqual(svc.generation, generation)

    def test_an_unresolved_identity_while_present_changes_nothing(self):
        """Present but nameless is unreadable, not a nameless replacement."""
        svc, _, token = armed()
        svc.acknowledge(token)
        for _ in range(3):
            svc.observe_attachment(present=True, uuid="")
        self.assertEqual(svc.candidate_token(DOCK), token)
        self.assertFalse(svc.assess(**NEW_DOCK).offered)

    def test_the_deprecated_shim_still_retires_and_never_re_arms_on_unknown(self):
        svc, _, token = armed()
        svc.acknowledge(token)
        svc.observe_device(None)
        self.assertFalse(svc.assess(**NEW_DOCK).offered)
        svc.observe_device(True)
        self.assertFalse(svc.assess(**NEW_DOCK).offered)
        svc.observe_device(False)
        self.assertTrue(svc.assess(**NEW_DOCK).offered)


class TheTokenBindsTheConfirmationToOneAttachment(unittest.TestCase):
    def test_it_is_stable_while_the_dock_stays_put(self):
        """A status poll must not make the card change identity."""
        svc, _, token = armed()
        svc.observe_attachment(present=True, uuid=DOCK)
        self.assertEqual(svc.candidate_token(DOCK), token)

    def test_it_never_contains_the_hardware_id(self):
        svc, _, token = armed()
        self.assertNotIn(DOCK, token)
        self.assertNotIn(DOCK.replace("-", ""), token)

    def test_nothing_is_minted_for_a_device_with_no_name(self):
        svc, _ = service()
        for value in ("", None, 7):
            with self.subTest(uuid=repr(value)):
                self.assertEqual(svc.candidate_token(value), "")

    def test_a_replug_retires_it_and_mints_a_new_one(self):
        """This is what makes same-device binding enforceable, not hoped for."""
        svc, commands, stale = armed()
        svc.observe_attachment(present=False, uuid="")
        svc.observe_attachment(present=True, uuid=DOCK)
        fresh = svc.candidate_token(DOCK)
        self.assertNotEqual(stale, fresh)
        self.assertEqual(
            confirm(svc, stale).code, "device_authorization.token_stale"
        )
        self.assertEqual(commands.calls, [])

    def test_a_stale_or_unknown_token_never_reaches_the_executor(self):
        for value in ("", None, 7, "deadbeef", DOCK):
            with self.subTest(token=repr(value)):
                svc, commands, _ = armed()
                outcome = confirm(svc, value)
                self.assertEqual(
                    outcome.code, "device_authorization.token_stale"
                )
                self.assertEqual(outcome.token, "")
                self.assertEqual(commands.calls, [])

    def test_a_replug_bumps_the_generation(self):
        svc, _, _ = armed()
        first = svc.generation
        svc.observe_attachment(present=False, uuid="")
        self.assertGreater(svc.generation, first)
        svc.observe_attachment(present=True, uuid=DOCK)
        self.assertGreater(svc.generation, first)


class OneAttachmentOneAct(unittest.TestCase):
    """The reproduced defect: the prompt returned and enrolled a second time."""

    def test_a_spent_generation_mints_no_second_token(self):
        svc, commands, token = armed()
        self.assertTrue(confirm(svc, token).requested)
        self.assertEqual(svc.candidate_token(DOCK), "")
        self.assertEqual(commands.calls, [("enroll", DOCK)])

    def test_a_poll_and_a_second_press_cannot_enrol_twice(self):
        """The exact observed failure: executor call count 2 for one dock."""
        svc, commands, token = armed()
        self.assertTrue(confirm(svc, token).requested)
        # However many times the panel polls afterwards.
        for _ in range(3):
            svc.observe_attachment(present=True, uuid=DOCK)
            reissued = svc.candidate_token(DOCK)
            self.assertEqual(reissued, "")
            self.assertEqual(
                confirm(svc, reissued).code, "device_authorization.token_stale"
            )
        self.assertEqual(
            confirm(svc, token).code, "device_authorization.token_stale"
        )
        self.assertEqual(commands.calls, [("enroll", DOCK)])

    def test_a_double_press_on_the_same_token_acts_once(self):
        svc, commands, token = armed()
        self.assertTrue(confirm(svc, token).requested)
        second = confirm(svc, token)
        self.assertFalse(second.requested)
        self.assertEqual(second.code, "device_authorization.token_stale")
        self.assertEqual(commands.calls, [("enroll", DOCK)])

    def test_a_spent_generation_is_not_a_blacklist(self):
        """A real replug is a new attachment and may be acted on again."""
        svc, commands, token = armed()
        confirm(svc, token)
        svc.observe_attachment(present=False, uuid="")
        svc.observe_attachment(present=True, uuid=DOCK)
        again = svc.candidate_token(DOCK)
        self.assertNotEqual(again, "")
        self.assertTrue(confirm(svc, again).requested)
        self.assertEqual(commands.calls, [("enroll", DOCK), ("enroll", DOCK)])

    def test_the_confirmation_closes_once_it_is_spent(self):
        svc, _, token = armed()
        self.assertFalse(svc.confirmation_open)
        svc.acknowledge(token)
        self.assertTrue(svc.confirmation_open)
        confirm(svc, token)
        self.assertFalse(svc.confirmation_open)

    def test_declining_closes_the_confirmation(self):
        svc, _, token = armed()
        svc.acknowledge(token)
        svc.decline(token)
        self.assertFalse(svc.confirmation_open)


class TheConfirmationIsBoundToTheDeviceItNamed(unittest.TestCase):
    """The reproduced defect: fresh facts about one dock acted on another."""

    def test_a_reading_of_another_device_never_acts_on_this_one(self):
        svc, commands, token = armed()
        outcome = confirm(svc, token, uuid=OTHER_DOCK)
        self.assertFalse(outcome.requested)
        self.assertEqual(outcome.code, "device_authorization.attachment_changed")
        self.assertEqual(outcome.token, token)
        self.assertEqual(commands.calls, [])

    def test_a_reading_from_a_previous_generation_refuses(self):
        svc, commands, token = armed()
        outcome = confirm(svc, token, generation=svc.generation - 1)
        self.assertEqual(outcome.code, "device_authorization.attachment_changed")
        self.assertEqual(commands.calls, [])

    def test_a_reading_from_a_later_generation_refuses(self):
        svc, commands, token = armed()
        outcome = confirm(svc, token, generation=svc.generation + 1)
        self.assertEqual(outcome.code, "device_authorization.attachment_changed")
        self.assertEqual(commands.calls, [])

    def test_an_identity_that_is_not_an_identity_refuses(self):
        """Each case changes exactly one half of the binding, not both."""
        for overrides in (
            {"uuid": ""},
            {"uuid": None},
            {"uuid": 7},
            {"generation": None},
            {"generation": "1"},
            {"generation": 1.0},
            # `True == 1`, so only checking the value would let a bool through
            # as the generation this dock was actually observed in.
            {"generation": True},
        ):
            with self.subTest(**{k: repr(v) for k, v in overrides.items()}):
                svc, commands, token = armed()
                self.assertEqual(svc.generation, 1)
                outcome = confirm(svc, token, **overrides)
                self.assertEqual(
                    outcome.code, "device_authorization.attachment_changed"
                )
                self.assertEqual(commands.calls, [])

    def test_a_matching_identity_is_what_lets_the_act_through(self):
        svc, commands, token = armed()
        self.assertTrue(confirm(svc, token, uuid=DOCK).requested)
        self.assertEqual(commands.calls, [("enroll", DOCK)])

    def test_a_refused_binding_leaves_the_prompt_answerable(self):
        """Nothing happened, so the right confirmation can still arrive."""
        svc, commands, token = armed()
        confirm(svc, token, uuid=OTHER_DOCK)
        self.assertEqual(svc.candidate_token(DOCK), token)
        self.assertTrue(confirm(svc, token).requested)
        self.assertEqual(commands.calls, [("enroll", DOCK)])


class NothingButAnExactTrue(unittest.TestCase):
    def test_truthy_values_are_not_a_confirmation(self):
        for value in (1, "yes", "true", [1], {"ok": True}, object(), 1.0):
            with self.subTest(consent=repr(value)):
                svc, commands, token = armed()
                outcome = confirm(svc, token, consent=value)
                self.assertFalse(outcome.requested)
                self.assertEqual(
                    outcome.code, "device_authorization.confirmation_required"
                )
                self.assertEqual(commands.calls, [])

    def test_falsy_values_are_refused_too(self):
        for value in (False, None, 0, ""):
            with self.subTest(consent=repr(value)):
                svc, commands, token = armed()
                self.assertEqual(
                    confirm(svc, token, consent=value).code,
                    "device_authorization.confirmation_required",
                )
                self.assertEqual(commands.calls, [])

    def test_a_refused_confirmation_does_not_spend_the_offer(self):
        """Nothing happened, so the player can still be asked."""
        svc, _, token = armed()
        confirm(svc, token, consent=False)
        self.assertFalse(svc.offered)
        self.assertEqual(svc.candidate_token(DOCK), token)


class TheActIsNamedByThePlayer(unittest.TestCase):
    def test_enroll_is_the_remembered_act(self):
        svc, commands, token = armed()
        self.assertTrue(confirm(svc, token, action="enroll").requested)
        self.assertEqual(commands.calls, [("enroll", DOCK)])

    def test_authorize_is_the_one_shot_act(self):
        svc, commands, token = armed()
        self.assertTrue(confirm(svc, token, action="authorize").requested)
        self.assertEqual(commands.calls, [("authorize", DOCK)])

    def test_anything_else_is_refused_rather_than_defaulted(self):
        for value in ("", None, 7, "ENROLL", "enrol", "trust", True, ["enroll"]):
            with self.subTest(action=repr(value)):
                svc, commands, token = armed()
                outcome = confirm(svc, token, action=value)
                self.assertFalse(outcome.requested)
                self.assertEqual(
                    outcome.code, "device_authorization.action_invalid"
                )
                self.assertEqual(commands.calls, [])

    def test_an_unnamed_act_is_refused_before_anything_is_spent(self):
        svc, _, token = armed()
        confirm(svc, token, action="trust")
        self.assertFalse(svc.offered)
        self.assertEqual(svc.candidate_token(DOCK), token)

    def test_the_act_is_checked_before_the_token_is_resolved(self):
        """Order matters: an unnamed act is not reported as a stale prompt."""
        svc, _, _ = armed()
        self.assertEqual(
            confirm(svc, "deadbeef", action="trust").code,
            "device_authorization.action_invalid",
        )

    def test_a_port_without_the_one_shot_act_fails_honestly(self):
        """The Protocol widened; the runner shipping today enrols only."""
        commands = EnrollOnlyCommands()
        svc = DeviceAuthorizationService(commands)
        svc.observe_attachment(present=True, uuid=DOCK)
        token = svc.candidate_token(DOCK)
        outcome = confirm(svc, token, action="authorize")
        self.assertFalse(outcome.requested)
        self.assertEqual(outcome.code, "device_authorization.enroll_unavailable")
        self.assertEqual(commands.calls, [])


class TheStateIsRecheckedWhenActing(unittest.TestCase):
    def _refused(self, expected, **changed):
        svc, commands, token = armed()
        svc.acknowledge(token)
        outcome = confirm(svc, token, **changed)
        self.assertFalse(outcome.requested)
        self.assertEqual(outcome.code, expected)
        self.assertEqual(outcome.token, token)
        self.assertEqual(commands.calls, [], f"{changed!r} still reached boltd")

    def test_a_scan_that_stopped_reading_refuses_as_itself(self):
        self._refused("device_authorization.scan_unreadable", device_present=None)

    def test_a_dock_unplugged_since_the_prompt_refuses(self):
        self._refused("device_authorization.no_device", device_present=False)

    def test_a_dock_authorized_since_the_prompt_refuses(self):
        """Something else trusted it while the dialog sat there."""
        self._refused("device_authorization.already_authorized", authorized=True)

    def test_a_dock_enrolled_since_the_prompt_refuses(self):
        self._refused(
            "device_authorization.already_enrolled", already_enrolled=True
        )

    def test_an_unreadable_enrolment_refuses_rather_than_enrolling_again(self):
        self._refused(
            "device_authorization.enrollment_unreadable", already_enrolled=None
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
        svc.acknowledge(token)
        outcome = confirm(svc, token)
        self.assertTrue(outcome.requested)
        self.assertEqual(commands.calls, [("enroll", DOCK)])


class ADeliberateDisconnectNamesTheDeviceItIsAbout(unittest.TestCase):
    """The report is keyed to a UUID, and only that UUID clears it.

    Keying it to the attachment generation could not be filed at all, and the
    reason is the feature itself: the deauthorization is what makes the dock
    read absent, that absent poll retires the attachment and bumps the
    generation, and the owning layer -- holding the generation it read while
    the dock was still there -- files one poll too late, every single time.
    Every test below that starts with an absence is that sequence.

    The second failure was its mirror: filing while nothing was named bound
    the disownership to the empty string, which then attached itself to
    whatever enumerated next, so a dock that had never been disowned was
    refused forever with no exit a player could reach.
    """

    def test_the_report_names_a_device_and_no_generation(self):
        """The signature is the fix: there is no stale window to file into."""
        parameters = inspect.signature(
            DeviceAuthorizationService.note_intentional_disconnect
        ).parameters
        self.assertEqual(list(parameters), ["self", "active", "uuid"])
        self.assertIs(parameters["uuid"].kind, inspect.Parameter.KEYWORD_ONLY)

    def test_it_declines_with_its_own_code(self):
        svc, _, _ = armed()
        self.assertTrue(svc.note_intentional_disconnect(True, uuid=DOCK))
        self.assertEqual(
            svc.assess(**NEW_DOCK).code,
            "device_authorization.intentional_disconnect",
        )

    def test_it_refuses_the_act_as_well_as_the_offer(self):
        svc, commands, token = armed()
        svc.note_intentional_disconnect(True, uuid=DOCK)
        outcome = confirm(svc, token)
        self.assertFalse(outcome.requested)
        self.assertEqual(
            outcome.code, "device_authorization.intentional_disconnect"
        )
        self.assertEqual(commands.calls, [])

    def test_filing_while_the_dock_reads_absent_blocks_it_when_it_returns(self):
        """The critical case: deauthorizing is what makes it read absent.

        The dock is already gone from the scan by the time the owning layer
        can say why it went, so a report it cannot file then is a report it
        can never file. The dock that has to be blocked is the one that comes
        back on the next wake.
        """
        svc, commands, _ = armed()
        svc.observe_attachment(present=False, uuid="")
        self.assertIs(svc.note_intentional_disconnect(True, uuid=DOCK), True)
        svc.observe_attachment(present=True, uuid=DOCK)
        self.assertFalse(svc.assess(**NEW_DOCK).offered)
        self.assertEqual(
            svc.assess(**NEW_DOCK).code,
            "device_authorization.intentional_disconnect",
        )
        outcome = confirm(svc, svc.candidate_token(DOCK))
        self.assertFalse(outcome.requested)
        self.assertEqual(commands.calls, [])

    def test_no_amount_of_polling_makes_a_report_too_late_to_file(self):
        """Nothing is read before filing, so nothing can go stale under it."""
        svc, _, _ = armed()
        for _ in range(25):
            svc.observe_attachment(present=False, uuid="")
            svc.observe_attachment(present=True, uuid=DOCK)
        svc.observe_attachment(present=False, uuid="")
        self.assertIs(svc.note_intentional_disconnect(True, uuid=DOCK), True)
        svc.observe_attachment(present=True, uuid=DOCK)
        self.assertFalse(svc.assess(**NEW_DOCK).offered)

    def test_a_report_about_one_dock_never_blocks_another(self):
        svc, commands, _ = armed()
        svc.note_intentional_disconnect(True, uuid=DOCK)
        svc.observe_attachment(present=True, uuid=OTHER_DOCK)
        self.assertTrue(svc.assess(**NEW_DOCK).offered)
        outcome = confirm(
            svc,
            svc.candidate_token(OTHER_DOCK),
            uuid=OTHER_DOCK,
            generation=svc.generation,
        )
        self.assertTrue(outcome.requested)
        self.assertEqual(commands.calls, [("enroll", OTHER_DOCK)])

    def test_a_report_filed_while_dock_a_is_absent_never_blocks_dock_b(self):
        """The permanent blacklist, in the order that produced it.

        A report with nothing attached used to bind to nothing, and nothing
        then became the next dock to enumerate -- a different device, never
        disowned, refused with no way back.
        """
        svc, _, _ = armed()
        svc.observe_attachment(present=False, uuid="")
        svc.note_intentional_disconnect(True, uuid=DOCK)
        svc.observe_attachment(present=True, uuid=OTHER_DOCK)
        self.assertTrue(
            svc.assess(**NEW_DOCK).offered,
            "a report about dock A was answered by dock B",
        )
        self.assertNotEqual(svc.candidate_token(OTHER_DOCK), "")

    def test_a_full_unplug_and_replug_of_dock_b_is_never_blocked(self):
        svc, commands, _ = armed()
        svc.note_intentional_disconnect(True, uuid=DOCK)
        for _ in range(3):
            svc.observe_attachment(present=True, uuid=OTHER_DOCK)
            self.assertTrue(svc.assess(**NEW_DOCK).offered)
            self.assertNotEqual(svc.candidate_token(OTHER_DOCK), "")
            svc.observe_attachment(present=False, uuid="")
        svc.observe_attachment(present=True, uuid=OTHER_DOCK)
        self.assertTrue(svc.assess(**NEW_DOCK).offered)
        self.assertEqual(commands.calls, [])

    def test_dock_a_and_dock_b_alternating_answer_only_for_themselves(self):
        """Through any sequence: the question is asked of what is attached."""
        svc, _, _ = armed()
        svc.note_intentional_disconnect(True, uuid=DOCK)
        for _ in range(4):
            svc.observe_attachment(present=True, uuid=OTHER_DOCK)
            self.assertTrue(svc.assess(**NEW_DOCK).offered)
            svc.observe_attachment(present=True, uuid=DOCK)
            self.assertFalse(svc.assess(**NEW_DOCK).offered)
            svc.observe_attachment(present=False, uuid="")

    def test_it_can_be_taken_back_by_the_same_uuid(self):
        svc, _, _ = armed()
        svc.note_intentional_disconnect(True, uuid=DOCK)
        self.assertIs(svc.note_intentional_disconnect(False, uuid=DOCK), True)
        self.assertTrue(svc.assess(**NEW_DOCK).offered)

    def test_a_clear_naming_another_device_does_not_take_it_back(self):
        svc, _, _ = armed()
        svc.note_intentional_disconnect(True, uuid=DOCK)
        svc.note_intentional_disconnect(False, uuid=OTHER_DOCK)
        self.assertFalse(
            svc.assess(**NEW_DOCK).offered,
            "a clear about another dock unblocked this one",
        )
        svc.note_intentional_disconnect(False, uuid=DOCK)
        self.assertTrue(svc.assess(**NEW_DOCK).offered)

    def test_nothing_the_hardware_does_takes_it_back(self):
        """Absence, an unreadable scan, a wake and a replug are all readings.

        A reading is not the owning layer retracting anything, and the whole
        defect was letting one speak as if it were.
        """
        svc, commands, _ = armed()
        svc.note_intentional_disconnect(True, uuid=DOCK)
        for _ in range(3):
            svc.observe_attachment(present=False, uuid="")
            svc.observe_attachment(present=None, uuid="")
            svc.observe_attachment(present=True, uuid=DOCK)
            self.assertEqual(
                svc.assess(**NEW_DOCK).code,
                "device_authorization.intentional_disconnect",
            )
        self.assertEqual(commands.calls, [])

    def test_another_dock_attaching_does_not_take_it_back(self):
        """Reversed on purpose: a second dock is not news about the first.

        Clearing on a different UUID meant that plugging in any other dock --
        or a router enumerating on the way to a replug -- un-disowned the one
        we deauthorized, and its next attach was first-time trust again.
        """
        svc, _, _ = armed()
        svc.note_intentional_disconnect(True, uuid=DOCK)
        svc.observe_attachment(present=True, uuid=OTHER_DOCK)
        self.assertTrue(svc.assess(**NEW_DOCK).offered)
        svc.observe_attachment(present=True, uuid=DOCK)
        self.assertFalse(svc.assess(**NEW_DOCK).offered)

    def test_a_full_confirmation_after_a_wake_never_reaches_the_executor(self):
        """The act, not just the offer: this is what grants memory access."""
        svc, commands, _ = armed()
        svc.note_intentional_disconnect(True, uuid=DOCK)
        svc.observe_attachment(present=False, uuid="")
        svc.observe_attachment(present=True, uuid=DOCK)
        outcome = confirm(svc, svc.candidate_token(DOCK))
        self.assertFalse(outcome.requested)
        self.assertEqual(commands.calls, [])

    def test_only_an_explicit_clear_takes_it_back_after_a_wake(self):
        """Blocked is not permanent: the owning layer files one clear."""
        svc, _, _ = armed()
        svc.note_intentional_disconnect(True, uuid=DOCK)
        svc.observe_attachment(present=False, uuid="")
        svc.observe_attachment(present=True, uuid=DOCK)
        self.assertTrue(svc.note_intentional_disconnect(False, uuid=DOCK))
        self.assertTrue(svc.assess(**NEW_DOCK).offered)

    def test_a_report_filed_with_nothing_attached_binds_to_the_named_device(
        self,
    ):
        """It binds to the UUID it names, and to nothing that arrives later."""
        svc, commands = service()
        self.assertIs(svc.note_intentional_disconnect(True, uuid=DOCK), True)
        svc.observe_attachment(present=True, uuid=OTHER_DOCK)
        self.assertTrue(
            svc.assess(**NEW_DOCK).offered,
            "the report bound itself to whatever enumerated next",
        )
        svc.observe_attachment(present=True, uuid=DOCK)
        self.assertFalse(svc.assess(**NEW_DOCK).offered)
        self.assertEqual(commands.calls, [])

    def test_a_report_never_binds_to_the_empty_string(self):
        svc, _ = service()
        self.assertIs(svc.note_intentional_disconnect(True, uuid=""), False)
        for uuid in (DOCK, OTHER_DOCK):
            with self.subTest(attaching=uuid):
                svc.observe_attachment(present=True, uuid=uuid)
                self.assertTrue(svc.assess(**NEW_DOCK).offered)

    def test_a_uuid_that_is_not_a_non_empty_string_is_refused(self):
        for value in ("", None, 7, 1.0, True, DOCK.encode(), [DOCK], {DOCK}):
            with self.subTest(uuid=repr(value)):
                svc, _ = service()
                self.assertIs(
                    svc.note_intentional_disconnect(True, uuid=value), False
                )
                svc.observe_attachment(present=True, uuid=DOCK)
                self.assertTrue(svc.assess(**NEW_DOCK).offered)

    def test_a_clear_for_a_device_that_was_never_disowned_is_harmless(self):
        svc, _, _ = armed()
        self.assertIs(svc.note_intentional_disconnect(False, uuid=DOCK), True)
        self.assertTrue(svc.assess(**NEW_DOCK).offered)

    def test_an_empty_port_is_never_the_disowned_device(self):
        """The published flag answers about what is attached, not the record."""
        svc, _, _ = armed()
        svc.note_intentional_disconnect(True, uuid=DOCK)
        self.assertTrue(svc.intentional_disconnect)
        svc.observe_attachment(present=False, uuid="")
        self.assertFalse(svc.intentional_disconnect)
        svc.observe_attachment(present=True, uuid=DOCK)
        self.assertTrue(svc.intentional_disconnect)

    def test_a_report_is_accepted_or_refused_out_loud(self):
        svc, _, _ = armed()
        self.assertIs(svc.note_intentional_disconnect(True, uuid=DOCK), True)
        self.assertIs(svc.note_intentional_disconnect(True, uuid=""), False)

    def test_only_an_exact_false_is_a_clear(self):
        """bool(active) let None, 0, the empty string and [] unblock a dock."""
        for value in (None, 0, "", [], 0.0):
            with self.subTest(active=repr(value)):
                svc, _, _ = armed()
                svc.note_intentional_disconnect(True, uuid=DOCK)
                self.assertIs(
                    svc.note_intentional_disconnect(value, uuid=DOCK), False
                )
                self.assertFalse(svc.assess(**NEW_DOCK).offered)

    def test_only_an_exact_true_is_a_report(self):
        for value in (1, "yes", [1], {"ok": True}, 1.0):
            with self.subTest(active=repr(value)):
                svc, _, _ = armed()
                self.assertIs(
                    svc.note_intentional_disconnect(value, uuid=DOCK), False
                )
                self.assertTrue(svc.assess(**NEW_DOCK).offered)

    def test_a_refused_report_leaves_an_earlier_one_standing(self):
        """A malformed retraction is not a retraction."""
        svc, _, _ = armed()
        svc.note_intentional_disconnect(True, uuid=DOCK)
        for value in (None, 0, "", [], "no"):
            with self.subTest(active=repr(value)):
                svc.note_intentional_disconnect(value, uuid=DOCK)
                self.assertFalse(svc.assess(**NEW_DOCK).offered)


class AReportIsNeverLostToAPollLandingUnderIt(unittest.TestCase):
    """Filing needs nothing read first, so there is no gap to lose it in.

    The old pair -- read the generation, then file against it -- was two lock
    acquisitions with every poll in the system free to land between them. A
    poll that retired the attachment made the report stale before it arrived,
    and it was refused silently, because the caller mirrored its own argument
    into the payload rather than this layer's answer. Measured at three losses
    in three hundred rounds, which is exactly the shape of defect that a
    single sequential test never sees.

    Three pollers and a short switch interval are what make the window
    visible: with one poller and the default interval, the gap between the
    read and the file is a handful of bytecodes and three hundred rounds of
    the old pair lost nothing at all. Under these two knobs the same three
    hundred rounds of the same code lost six, so a test written without them
    would have passed over the defect it exists to catch.
    """

    def setUp(self):
        interval = sys.getswitchinterval()
        self.addCleanup(sys.setswitchinterval, interval)
        sys.setswitchinterval(1e-6)

    def test_three_hundred_rounds_of_filing_against_polling_threads(self):
        lost: list[int] = []
        for round_index in range(300):
            svc, _ = service()
            svc.observe_attachment(present=True, uuid=DOCK)
            start = threading.Barrier(4)
            filed: list[object] = []

            def poll():
                start.wait()
                for _ in range(20):
                    svc.observe_attachment(present=False, uuid="")
                    svc.observe_attachment(present=True, uuid=DOCK)

            def file_it():
                start.wait()
                filed.append(svc.note_intentional_disconnect(True, uuid=DOCK))

            threads = [threading.Thread(target=poll) for _ in range(3)]
            threads.append(threading.Thread(target=file_it))
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
            for thread in threads:
                self.assertFalse(thread.is_alive(), "a caller never returned")
            svc.observe_attachment(present=True, uuid=DOCK)
            if filed != [True] or svc.assess(**NEW_DOCK).offered:
                lost.append(round_index)
        self.assertEqual(lost, [], f"{len(lost)} of 300 reports were lost")

    def test_a_report_and_a_clear_racing_leave_one_coherent_answer(self):
        """Whichever lands last wins, and neither is applied halfway."""
        for _ in range(50):
            svc, _ = service()
            svc.observe_attachment(present=True, uuid=DOCK)
            start = threading.Barrier(2)
            answers: list[object] = []
            guard = threading.Lock()

            def work(active):
                def run():
                    start.wait()
                    accepted = svc.note_intentional_disconnect(
                        active, uuid=DOCK
                    )
                    with guard:
                        answers.append(accepted)

                return run

            threads = [
                threading.Thread(target=work(True)),
                threading.Thread(target=work(False)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
            self.assertEqual(answers, [True, True])
            blocked = not svc.assess(**NEW_DOCK).offered
            self.assertIs(svc.intentional_disconnect, blocked)


class AReportIsSpelledTheWayTheObserverSpellsIt(unittest.TestCase):
    """The reproduced defect: an uppercase report was accepted and blocked nothing.

    The observer case-folds the `unique_id` it reads, and that is the spelling
    the disowned set is compared against.  The set used to store the caller's
    bytes exactly as they arrived, so a report naming the same dock in the
    uppercase hex some tools print -- or with whitespace still around it --
    returned `True`, which told the layer that filed it the dock was disowned,
    and then matched nothing at all.  The dock was offered as first-time trust
    on its next attach and a full confirmation ran the executor.  A report that
    is accepted and does nothing is worse than one that is refused: nobody is
    left to notice.
    """

    #: The same device, written the ways a caller might actually hand it over.
    #: `LETTERED_DOCK` and not `DOCK`, because an id of nothing but digits is
    #: its own upper case and a case test written on one proves nothing.
    SPELLINGS = (
        LETTERED_DOCK.upper(),
        LETTERED_DOCK[:8].upper() + LETTERED_DOCK[8:],
        f"  {LETTERED_DOCK}  ",
        f"\t{LETTERED_DOCK.upper()}\n",
    )

    def test_the_fixtures_really_are_a_different_spelling(self):
        """Or every test below passes on code that never looked at case."""
        for spelling in self.SPELLINGS:
            with self.subTest(uuid=repr(spelling)):
                self.assertNotEqual(spelling, LETTERED_DOCK)
                self.assertEqual(spelling.strip().casefold(), LETTERED_DOCK)

    def test_a_report_in_any_spelling_blocks_the_dock(self):
        for spelling in self.SPELLINGS:
            with self.subTest(uuid=repr(spelling)):
                svc, _, _ = armed(uuid=LETTERED_DOCK)
                self.assertIs(
                    svc.note_intentional_disconnect(True, uuid=spelling), True
                )
                self.assertFalse(
                    svc.assess(**NEW_DOCK).offered,
                    "an accepted report blocked nothing",
                )
                self.assertEqual(
                    svc.assess(**NEW_DOCK).code,
                    "device_authorization.intentional_disconnect",
                )
                self.assertTrue(svc.intentional_disconnect)

    def test_it_blocks_the_act_as_well_as_the_offer(self):
        """The offer is the symptom; the executor is the consequence."""
        for spelling in self.SPELLINGS:
            with self.subTest(uuid=repr(spelling)):
                svc, commands, token = armed(uuid=LETTERED_DOCK)
                svc.note_intentional_disconnect(True, uuid=spelling)
                outcome = confirm(
                    svc,
                    token,
                    uuid=LETTERED_DOCK,
                    generation=svc.generation,
                )
                self.assertFalse(outcome.requested)
                self.assertEqual(
                    outcome.code,
                    "device_authorization.intentional_disconnect",
                )
                self.assertEqual(commands.calls, [])

    def test_a_clear_in_any_spelling_takes_it_back(self):
        for spelling in self.SPELLINGS:
            with self.subTest(uuid=repr(spelling)):
                svc, _, _ = armed(uuid=LETTERED_DOCK)
                svc.note_intentional_disconnect(True, uuid=LETTERED_DOCK)
                self.assertIs(
                    svc.note_intentional_disconnect(False, uuid=spelling), True
                )
                self.assertTrue(svc.assess(**NEW_DOCK).offered)

    def test_a_report_in_one_spelling_is_cleared_by_another(self):
        """Both directions, or the exit a player reaches stops working."""
        svc, _, _ = armed(uuid=LETTERED_DOCK)
        svc.note_intentional_disconnect(
            True, uuid=f"  {LETTERED_DOCK.upper()} "
        )
        self.assertFalse(svc.assess(**NEW_DOCK).offered)
        svc.note_intentional_disconnect(False, uuid=LETTERED_DOCK)
        self.assertTrue(svc.assess(**NEW_DOCK).offered)

    def test_an_attached_id_that_arrives_unnormalized_is_recognised_too(self):
        """Both sides are normalized, so neither side has to be trusted."""
        svc, _ = service()
        svc.note_intentional_disconnect(True, uuid=LETTERED_DOCK)
        svc.observe_attachment(present=True, uuid=LETTERED_DOCK.upper())
        self.assertFalse(svc.assess(**NEW_DOCK).offered)
        self.assertTrue(svc.intentional_disconnect)

    def test_a_uuid_that_is_only_whitespace_names_no_device(self):
        """It must never bind to "", and "   " is "" once it is normalized."""
        for value in ("", "   ", "\t", "\n "):
            with self.subTest(uuid=repr(value)):
                svc, _, _ = armed()
                self.assertIs(
                    svc.note_intentional_disconnect(True, uuid=value), False
                )
                self.assertTrue(svc.assess(**NEW_DOCK).offered)

    def test_it_still_answers_only_for_the_device_it_names(self):
        svc, _, _ = armed(uuid=LETTERED_DOCK)
        svc.note_intentional_disconnect(True, uuid=LETTERED_DOCK.upper())
        svc.observe_attachment(present=True, uuid=OTHER_DOCK)
        self.assertTrue(
            svc.assess(**NEW_DOCK).offered,
            "a report about dock A was answered by dock B",
        )


class AStaleIdentityDoesNotAnswerForANewDevice(unittest.TestCase):
    """The reproduced defect: dock B reported under dock A's disownership.

    A poll that finds something present and cannot name it leaves the
    attachment alone -- retiring there would drop a live prompt every time one
    sysfs attribute went briefly unreadable -- but the identity still held is
    the previous dock's.  Plug dock B in where a disowned dock A was, catch the
    poll before B's `device_name` is readable, and the answer was that the
    attached device is one we disowned.
    """

    #: What a caller reads while something is attached and nothing names it.
    #: The observer produces exactly this for an ambiguous scan -- two routers,
    #: which is what a chained dock or a second Thunderbolt device looks like
    #: -- and for a router whose `unique_id` will not read.
    NAMELESS = {**NEW_DOCK, "identity_resolved": False}

    def test_a_nameless_poll_stops_the_last_dock_answering(self):
        svc, _, _ = armed()
        svc.note_intentional_disconnect(True, uuid=DOCK)
        self.assertTrue(svc.intentional_disconnect)
        # Dock B arrives, and this poll cannot name it yet.
        svc.observe_attachment(present=True, uuid="")
        self.assertFalse(
            svc.intentional_disconnect,
            "a dock nobody disowned was reported as disowned",
        )
        self.assertEqual(
            svc.assess(**self.NAMELESS).code,
            "device_authorization.identity_unresolved",
            "the refusal named the wrong reason",
        )

    def test_the_attachment_itself_survives_the_nameless_poll(self):
        """Nothing is retired: a live prompt outlives an unreadable attribute."""
        svc, _, token = armed()
        generation = svc.generation
        svc.acknowledge(token)
        for _ in range(3):
            svc.observe_attachment(present=True, uuid="")
        self.assertEqual(svc.candidate_token(DOCK), token)
        self.assertEqual(svc.generation, generation)
        self.assertTrue(svc.confirmation_open)

    def test_naming_the_device_again_restores_the_answer(self):
        svc, _, _ = armed()
        svc.note_intentional_disconnect(True, uuid=DOCK)
        svc.observe_attachment(present=True, uuid="")
        self.assertFalse(svc.intentional_disconnect)
        svc.observe_attachment(present=True, uuid=DOCK)
        self.assertTrue(svc.intentional_disconnect)
        self.assertFalse(svc.assess(**NEW_DOCK).offered)

    def test_naming_a_different_device_retires_and_offers_that_one(self):
        svc, _, _ = armed()
        svc.note_intentional_disconnect(True, uuid=DOCK)
        svc.observe_attachment(present=True, uuid="")
        svc.observe_attachment(present=True, uuid=OTHER_DOCK)
        self.assertTrue(svc.assess(**NEW_DOCK).offered)
        self.assertFalse(svc.intentional_disconnect)

    def test_a_confirmation_that_names_the_disowned_dock_is_still_refused(self):
        """The one thing the guard may not become: a way in.

        A caller naming the device has proved which device it means, so the
        record answers for it -- the "no reading has confirmed this" guard is
        about what a *poll* may claim. If it applied here, one nameless poll
        would be enough to enrol a dock this backend deliberately disowned.
        """
        svc, commands, token = armed()
        svc.note_intentional_disconnect(True, uuid=DOCK)
        svc.observe_attachment(present=True, uuid="")
        outcome = confirm(svc, token)
        self.assertFalse(outcome.requested)
        self.assertEqual(
            outcome.code, "device_authorization.intentional_disconnect"
        )
        self.assertEqual(commands.calls, [])

    def test_an_empty_port_still_answers_for_nobody(self):
        svc, _, _ = armed()
        svc.note_intentional_disconnect(True, uuid=DOCK)
        svc.observe_attachment(present=False, uuid="")
        self.assertFalse(svc.intentional_disconnect)


def snapshot(svc, **overrides):
    """A snapshot for a reading that describes the attached dock by default."""
    call = {**NEW_DOCK, "uuid": DOCK, **overrides}
    return svc.snapshot(**call)


class OnePayloadIsOneLockAcquisition(unittest.TestCase):
    """Serialising six reads is not the same as answering once.

    Each of `assess`, `offered`, `generation`, `candidate_token`,
    `confirmation_open` and `intentional_disconnect` is correct under the lock
    and they were six different instants, so a payload built from them could
    say `offered` with a live token beside `intentional_disconnect=True` -- the
    prompt for a dock this backend had just deauthorized. `snapshot` answers
    all of it at once.
    """

    def test_it_answers_every_field_a_payload_needs(self):
        svc, _, _ = armed()
        taken = snapshot(svc)
        self.assertTrue(taken.offered)
        self.assertEqual(taken.code, "device_authorization.available")
        self.assertTrue(taken.token)
        self.assertFalse(taken.already_offered)
        self.assertFalse(taken.intentional_disconnect)
        self.assertFalse(taken.confirmation_open)
        self.assertEqual(taken.generation, svc.generation)

    def test_the_token_it_mints_is_the_one_the_attachment_holds(self):
        svc, _, token = armed()
        self.assertEqual(snapshot(svc).token, token)
        self.assertEqual(svc.candidate_token(DOCK), token)

    def test_it_mints_for_a_device_this_layer_observed_and_no_other(self):
        svc, _, _ = armed()
        self.assertEqual(snapshot(svc, uuid=OTHER_DOCK).token, "")
        for value in ("", None, 7):
            with self.subTest(uuid=repr(value)):
                self.assertEqual(snapshot(svc, uuid=value).token, "")

    def test_a_reading_that_names_nothing_repeats_an_open_confirmations_token(
        self,
    ):
        """A dialog on screen must not be stranded by one unreadable poll."""
        svc, _, token = armed()
        svc.acknowledge(token)
        taken = snapshot(svc, device_present=None, identity_resolved=False, uuid="")
        self.assertTrue(taken.confirmation_open)
        self.assertEqual(taken.token, token)

    def test_a_reading_naming_another_device_is_never_lent_that_token(self):
        """The token addresses one attachment, so it names one device.

        Repeating it for a reading that named a *different* dock is how a
        status came to return the replacement's token while reporting the
        attachment it replaced.
        """
        svc, _, token = armed()
        svc.acknowledge(token)
        taken = snapshot(svc, uuid=OTHER_DOCK)
        self.assertTrue(taken.confirmation_open)
        self.assertEqual(taken.token, "")

    def test_with_no_reading_it_offers_nothing_and_mints_nothing(self):
        """What `confirm` asks for: the state around an act it already took."""
        svc, _ = service()
        svc.observe_attachment(present=True, uuid=DOCK)
        taken = svc.snapshot()
        self.assertFalse(taken.offered)
        self.assertEqual(taken.code, "device_authorization.scan_unreadable")
        self.assertEqual(taken.token, "")
        self.assertFalse(taken.confirmation_open)
        self.assertEqual(taken.generation, svc.generation)
        # Nothing was minted by it: the first token this attachment ever has is
        # still the one the next poll asks for, and it survives being asked
        # for a snapshot again.
        first = svc.candidate_token(DOCK)
        self.assertTrue(first)
        self.assertEqual(svc.snapshot().token, "")
        self.assertEqual(svc.candidate_token(DOCK), first)

    def test_taking_one_never_spends_the_latch(self):
        svc, _, token = armed()
        for _ in range(5):
            taken = snapshot(svc)
            self.assertTrue(taken.offered)
            self.assertEqual(taken.token, token)
            self.assertFalse(taken.already_offered)
        self.assertFalse(svc.offered)

    def test_an_offer_and_a_disownership_are_never_both_in_one(self):
        svc, _, _ = armed()
        svc.note_intentional_disconnect(True, uuid=DOCK)
        taken = snapshot(svc)
        self.assertFalse(taken.offered)
        self.assertTrue(taken.intentional_disconnect)
        self.assertEqual(
            taken.code, "device_authorization.intentional_disconnect"
        )
        self.assertEqual(taken.token, "")

    def test_an_offer_and_a_spent_latch_are_never_both_in_one(self):
        svc, _, token = armed()
        svc.acknowledge(token)
        taken = snapshot(svc)
        self.assertFalse(taken.offered)
        self.assertTrue(taken.already_offered)
        self.assertTrue(taken.confirmation_open)
        self.assertEqual(taken.token, token)

    def test_its_fields_are_copies_rather_than_a_view(self):
        """Whatever happens next, the snapshot still describes its moment."""
        svc, _, _ = armed()
        taken = snapshot(svc)
        svc.note_intentional_disconnect(True, uuid=DOCK)
        svc.observe_attachment(present=False, uuid="")
        self.assertTrue(taken.offered)
        self.assertFalse(taken.intentional_disconnect)
        self.assertNotEqual(taken.generation, svc.generation)


class ASnapshotIsNeverSelfContradictory(unittest.TestCase):
    """The same claim, under the threads that produced the contradiction.

    Three pollers and a short switch interval, for the reason the report race
    below uses them: with the default interval the gap between two of the six
    reads is a handful of bytecodes and almost nothing lands inside it.
    """

    def setUp(self):
        interval = sys.getswitchinterval()
        self.addCleanup(sys.setswitchinterval, interval)
        sys.setswitchinterval(1e-6)

    def assertCoherent(self, taken):
        """What one snapshot may not say about itself.

        Deliberately not "offered implies a token": the decision is about the
        *caller's* reading and the token is about the identity this layer
        observed, so a reading of a dock that was retired underneath it is
        offered with nothing to mint against. That pair is a real state and the
        delivery layer is what resolves it, into `identity_unresolved` with no
        token -- tested there, where the rule lives.
        """
        if taken.offered:
            self.assertFalse(taken.intentional_disconnect, taken)
            self.assertFalse(taken.already_offered, taken)
            self.assertEqual(taken.code, "device_authorization.available", taken)
        if taken.token:
            self.assertTrue(taken.offered or taken.confirmation_open, taken)
        if taken.confirmation_open:
            self.assertTrue(taken.already_offered, taken)
        if taken.code == "device_authorization.intentional_disconnect":
            self.assertTrue(taken.intentional_disconnect, taken)

    def test_a_report_racing_the_pollers_never_lands_inside_a_snapshot(self):
        """Half the rounds run with a confirmation already open.

        Without them `assertCoherent`'s fourth clause is decoration: no racing
        test acknowledged anything, so `confirmation_open` was `False` in every
        snapshot ever handed to it and the invariant it advertises -- an open
        confirmation implies a spent latch -- was never once evaluated. An open
        prompt is also the state a report is most dangerous in, because it is
        the one where a live token survives the refusal.
        """
        for round_index in range(60):
            svc, _ = service()
            svc.observe_attachment(present=True, uuid=DOCK)
            open_prompt = bool(round_index % 2)
            if open_prompt:
                self.assertTrue(svc.acknowledge(svc.candidate_token(DOCK)))
            start = threading.Barrier(4)
            taken: list = []
            guard = threading.Lock()

            def poll():
                start.wait()
                mine = [snapshot(svc) for _ in range(20)]
                with guard:
                    taken.extend(mine)

            def file_it():
                start.wait()
                for _ in range(10):
                    svc.note_intentional_disconnect(True, uuid=DOCK)
                    svc.note_intentional_disconnect(False, uuid=DOCK)

            threads = [threading.Thread(target=poll) for _ in range(3)]
            threads.append(threading.Thread(target=file_it))
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
            for thread in threads:
                self.assertFalse(thread.is_alive(), "a caller never returned")
            self.assertEqual(len(taken), 60)
            for one in taken:
                self.assertCoherent(one)
                # Nothing in this race opens or closes a confirmation, so the
                # state every snapshot was taken in is known, and the clause
                # above is exercised rather than skipped.
                self.assertIs(one.confirmation_open, open_prompt, one)

    def test_a_replug_racing_the_pollers_never_lands_inside_a_snapshot(self):
        for _ in range(60):
            svc, _ = service()
            svc.observe_attachment(present=True, uuid=DOCK)
            start = threading.Barrier(4)
            taken: list = []
            guard = threading.Lock()

            def poll():
                start.wait()
                mine = [snapshot(svc) for _ in range(20)]
                with guard:
                    taken.extend(mine)

            def replug():
                start.wait()
                for _ in range(20):
                    svc.observe_attachment(present=False, uuid="")
                    svc.observe_attachment(present=True, uuid=DOCK)

            threads = [threading.Thread(target=poll) for _ in range(3)]
            threads.append(threading.Thread(target=replug))
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
            for thread in threads:
                self.assertFalse(thread.is_alive(), "a caller never returned")
            minted: dict = {}
            for one in taken:
                self.assertCoherent(one)
                if one.token:
                    minted.setdefault(one.token, set()).add(one.generation)
            for token, generations in minted.items():
                self.assertEqual(
                    len(generations),
                    1,
                    f"one token was reported under {generations!r}",
                )


def read(svc, **overrides):
    """One reading, observed and answered under the one acquisition."""
    call = {
        "present": True,
        "identity_resolved": True,
        "authorized": False,
        "already_enrolled": False,
        "uuid": DOCK,
        **overrides,
    }
    return svc.observe_and_snapshot(**call)


class OneAcquisitionTakesTheReadingAndAnswersAboutIt(unittest.TestCase):
    """The reading is part of the payload, so it is part of the acquisition.

    `observe_attachment` and then `snapshot` is the same work split across two
    acquisitions, and the gap between them is not an inefficiency, it is the
    defect: another RPC thread observes *its* dock in there, and the snapshot
    answers the two things it reads from the attachment rather than from its
    argument -- the disownership, and the guard saying whether any reading has
    confirmed the held identity -- about that thread's dock, while every other
    input to the same assessment is this caller's own reading.
    """

    def test_it_observes_and_answers_about_the_same_reading(self):
        svc, _ = service()
        taken = read(svc)
        self.assertTrue(taken.offered)
        self.assertEqual(taken.code, "device_authorization.available")
        self.assertTrue(taken.token)
        self.assertEqual(taken.token, svc.candidate_token(DOCK))
        self.assertEqual(taken.generation, svc.generation)

    def test_an_absence_retires_inside_the_same_acquisition(self):
        svc, _, token = armed()
        taken = read(svc, present=False, identity_resolved=False, uuid="")
        self.assertEqual(taken.code, "device_authorization.no_device")
        self.assertEqual(taken.token, "")
        self.assertGreater(taken.generation, 1)
        self.assertEqual(svc.candidate_token(DOCK), "")
        self.assertNotEqual(svc.candidate_token(DOCK), token)

    def test_a_replacement_is_answered_for_as_the_replacement(self):
        svc, _, first = armed()
        taken = read(svc, uuid=OTHER_DOCK)
        self.assertTrue(taken.offered)
        self.assertNotEqual(taken.token, first)
        self.assertEqual(taken.token, svc.candidate_token(OTHER_DOCK))

    def test_a_disowned_dock_is_answered_for_by_its_own_record(self):
        svc, _ = service()
        svc.note_intentional_disconnect(True, uuid=DOCK)
        taken = read(svc)
        self.assertFalse(taken.offered)
        self.assertTrue(taken.intentional_disconnect)
        self.assertEqual(
            taken.code, "device_authorization.intentional_disconnect"
        )
        self.assertEqual(taken.token, "")

    def test_another_docks_disownership_is_never_charged_to_this_reading(self):
        """The second symptom, sequentially: the flag came from the attachment.

        A reading of dock B answered with dock A's disownership whenever dock A
        was the identity this layer happened to be holding.
        """
        svc, _, _ = armed()
        svc.note_intentional_disconnect(True, uuid=DOCK)
        taken = read(svc, uuid=OTHER_DOCK)
        self.assertFalse(taken.intentional_disconnect)
        self.assertTrue(taken.offered)
        self.assertTrue(taken.token)

    def test_a_nameless_reading_stops_the_held_id_answering(self):
        """The first symptom, sequentially: one flag, whoever wrote it last."""
        svc, _, _ = armed()
        svc.note_intentional_disconnect(True, uuid=DOCK)
        self.assertTrue(read(svc).intentional_disconnect)
        nameless = read(svc, identity_resolved=False, uuid="")
        self.assertFalse(nameless.intentional_disconnect)
        self.assertEqual(
            nameless.code, "device_authorization.identity_unresolved"
        )
        # And naming it again restores the answer, in one acquisition too.
        self.assertTrue(read(svc).intentional_disconnect)

    def test_reading_repeatedly_never_spends_the_latch(self):
        svc, _ = service()
        tokens = {read(svc).token for _ in range(5)}
        self.assertEqual(len(tokens), 1)
        self.assertFalse(svc.offered)
        self.assertFalse(read(svc).already_offered)

    def test_the_answer_variant_acknowledges_and_reports_it_at_once(self):
        svc, _, token = armed()
        answer = svc.observe_and_answer(
            token,
            accept=True,
            present=True,
            identity_resolved=True,
            authorized=False,
            already_enrolled=False,
            uuid=DOCK,
        )
        self.assertIs(answer.accepted, True)
        self.assertTrue(answer.state.already_offered)
        self.assertTrue(answer.state.confirmation_open)
        self.assertEqual(answer.state.token, token)
        self.assertFalse(answer.state.offered)
        self.assertEqual(
            answer.state.code, "device_authorization.already_offered"
        )

    def test_the_answer_variant_declines_and_reports_it_at_once(self):
        svc, _, token = armed()
        answer = svc.observe_and_answer(
            token,
            accept=False,
            present=True,
            identity_resolved=True,
            authorized=False,
            already_enrolled=False,
            uuid=DOCK,
        )
        self.assertIs(answer.accepted, True)
        self.assertTrue(answer.state.already_offered)
        self.assertFalse(answer.state.confirmation_open)
        self.assertEqual(answer.state.token, "")

    def test_an_unknown_token_answers_nothing_and_spends_nothing(self):
        for value in ("", None, 7, "deadbeef", DOCK):
            for accept in (True, False):
                with self.subTest(token=repr(value), accept=accept):
                    svc, _, token = armed()
                    answer = svc.observe_and_answer(
                        value,
                        accept=accept,
                        present=True,
                        identity_resolved=True,
                        authorized=False,
                        already_enrolled=False,
                        uuid=DOCK,
                    )
                    self.assertIs(answer.accepted, False)
                    self.assertFalse(svc.offered)
                    self.assertTrue(answer.state.offered)
                    self.assertEqual(answer.state.token, token)

    def test_an_answer_that_is_neither_word_spends_nothing(self):
        """`accept` is read by identity, like every other decision here."""
        for value in (1, 0, "yes", "", None, [1]):
            with self.subTest(accept=repr(value)):
                svc, _, token = armed()
                answer = svc.observe_and_answer(
                    token,
                    accept=value,
                    present=True,
                    identity_resolved=True,
                    authorized=False,
                    already_enrolled=False,
                    uuid=DOCK,
                )
                self.assertIs(answer.accepted, False)
                self.assertFalse(svc.offered)
                self.assertFalse(answer.state.already_offered)
                self.assertEqual(answer.state.token, token)

    def test_the_answer_is_taken_against_the_device_that_is_there_now(self):
        """A token for a dock that has gone answers for nothing."""
        svc, _, token = armed()
        answer = svc.observe_and_answer(
            token,
            accept=True,
            present=True,
            identity_resolved=True,
            authorized=False,
            already_enrolled=False,
            uuid=OTHER_DOCK,
        )
        self.assertIs(answer.accepted, False)
        self.assertTrue(answer.state.offered)
        self.assertFalse(answer.state.already_offered)
        self.assertNotEqual(answer.state.token, token)


class ReadingsOfDifferentDocksNeverAnswerForEachOther(unittest.TestCase):
    """The reproduced defect, under the threads that produced it.

    Two panels polling two docks is not exotic on this hardware: a status call
    per RPC thread is exactly what the plugin does, and the observation half of
    one landed between the observation and the snapshot of the other. Nothing
    sequential can see it, so this races it.
    """

    def setUp(self):
        interval = sys.getswitchinterval()
        self.addCleanup(sys.setswitchinterval, interval)
        sys.setswitchinterval(1e-6)

    def test_a_reading_is_answered_for_by_its_own_dock_and_no_other(self):
        for _ in range(40):
            svc, _ = service()
            # Dock A is disowned for the whole round and dock B never is, so
            # every snapshot has exactly one right answer and it is known
            # before the threads start.
            svc.note_intentional_disconnect(True, uuid=DOCK)
            start = threading.Barrier(5)
            taken: list = []
            guard = threading.Lock()

            def poll(uuid):
                def run():
                    start.wait()
                    mine = [(uuid, read(svc, uuid=uuid)) for _ in range(20)]
                    with guard:
                        taken.extend(mine)

                return run

            def nameless():
                # The poll that finds something present and cannot name it:
                # the one that writes the identity-unconfirmed guard.
                start.wait()
                for _ in range(20):
                    read(svc, identity_resolved=False, uuid="")

            threads = [threading.Thread(target=poll(DOCK)) for _ in range(2)]
            threads += [
                threading.Thread(target=poll(OTHER_DOCK)) for _ in range(2)
            ]
            threads.append(threading.Thread(target=nameless))
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
            for thread in threads:
                self.assertFalse(thread.is_alive(), "a caller never returned")
            self.assertEqual(len(taken), 80)
            for uuid, one in taken:
                if uuid == DOCK:
                    self.assertTrue(one.intentional_disconnect, one)
                    self.assertEqual(
                        one.code,
                        "device_authorization.intentional_disconnect",
                        one,
                    )
                    self.assertEqual(one.token, "", one)
                else:
                    self.assertFalse(one.intentional_disconnect, one)
                    self.assertTrue(one.offered, one)
                    self.assertTrue(one.token, one)


class TheOutcomeIsHonest(unittest.TestCase):
    def test_it_reports_the_executor_result_and_names_the_token(self):
        svc, commands, token = armed()
        outcome = confirm(svc, token)
        self.assertTrue(outcome.requested)
        self.assertEqual(outcome.code, ACCEPTED)
        self.assertEqual(outcome.token, token)
        # The executor still needs the real id; the OUTCOME must not carry it.
        self.assertEqual(commands.calls, [("enroll", DOCK)])
        self.assertNotIn(DOCK, outcome.token + outcome.code)

    def test_acceptance_is_never_reported_as_verified(self):
        svc, _, token = armed()
        self.assertIsNone(confirm(svc, token).verified)

    def test_an_executor_failure_is_reported_as_itself(self):
        svc, _, token = armed(
            result=DeviceEnrollmentResult(
                False, "device_authorization.enroll_failed"
            )
        )
        outcome = confirm(svc, token)
        self.assertFalse(outcome.requested)
        self.assertEqual(outcome.code, "device_authorization.enroll_failed")

    def test_an_executor_that_raises_is_a_failure_not_a_crash(self):
        svc, _, token = armed(raising=True)
        outcome = confirm(svc, token)
        self.assertFalse(outcome.requested)
        self.assertEqual(outcome.code, "device_authorization.enroll_unavailable")

    def test_acting_spends_the_offer_even_when_the_executor_fails(self):
        """A failed act should not re-prompt in a loop on the same dock."""
        svc, _, token = armed(
            result=DeviceEnrollmentResult(
                False, "device_authorization.enroll_failed"
            )
        )
        confirm(svc, token)
        self.assertTrue(svc.offered)
        self.assertEqual(svc.candidate_token(DOCK), "")


class TheOutcomeCarriesTheStateThatBelongsBesideIt(unittest.TestCase):
    """An act and the fields a payload prints next to it are one answer.

    The reproduced defect: the delivery layer took its own snapshot after
    `confirm` returned, which is a second acquisition, and a poll landing in it
    retires the attachment that was just acted on. The payload then said
    `requested=True` with this dock's token and names beside the next dock's
    generation and unspent latch -- one dict about two attachments, naming one
    of them and describing the other.
    """

    def test_a_successful_act_carries_the_acted_attachments_state(self):
        svc, commands, token = armed()
        svc.acknowledge(token)
        acted = svc.generation
        outcome = confirm(svc, token)
        self.assertTrue(outcome.requested)
        self.assertEqual(commands.calls, [("enroll", DOCK)])
        self.assertEqual(outcome.state.generation, acted)
        self.assertTrue(outcome.state.already_offered)
        self.assertFalse(outcome.state.confirmation_open)
        self.assertFalse(outcome.state.intentional_disconnect)

    def test_the_state_survives_a_retire_that_lands_after_the_act(self):
        """What the separate snapshot could not do: describe what it named."""
        svc, _, token = armed()
        svc.acknowledge(token)
        acted = svc.generation
        outcome = confirm(svc, token)
        svc.observe_attachment(present=False, uuid="")
        self.assertGreater(svc.generation, acted)
        self.assertFalse(svc.offered)
        self.assertEqual(outcome.state.generation, acted)
        self.assertTrue(outcome.state.already_offered)

    def test_every_refusal_carries_one_too(self):
        """A payload is built from it however the act went."""
        for overrides in (
            {"consent": False},
            {"action": "trust"},
            {"uuid": OTHER_DOCK},
            {"generation": 99},
        ):
            with self.subTest(**{k: repr(v) for k, v in overrides.items()}):
                svc, commands, token = armed()
                outcome = confirm(svc, token, **overrides)
                self.assertFalse(outcome.requested)
                self.assertIsNotNone(outcome.state)
                self.assertEqual(outcome.state.generation, svc.generation)
                self.assertEqual(commands.calls, [])
        svc, _, _ = armed()
        self.assertIsNotNone(confirm(svc, "deadbeef").state)

    def test_the_state_offers_nothing_and_mints_nothing(self):
        """It is the state around an act, not a second prompt."""
        svc, _, token = armed()
        outcome = confirm(svc, token, consent=False)
        self.assertFalse(outcome.state.offered)
        self.assertEqual(outcome.state.token, "")
        self.assertEqual(svc.candidate_token(DOCK), token)

    def test_it_reports_the_disownership_of_the_device_it_refused_for(self):
        svc, _, token = armed()
        svc.note_intentional_disconnect(True, uuid=DOCK)
        outcome = confirm(svc, token)
        self.assertEqual(
            outcome.code, "device_authorization.intentional_disconnect"
        )
        self.assertTrue(outcome.state.intentional_disconnect)

    def test_another_docks_disownership_is_never_charged_to_this_act(self):
        """The act named a device, so the flag beside it is about that device.

        Read from the attachment instead, the answer is about whatever is on
        the bus by the time the act finishes -- which under a swap is the dock
        that replaced the one this payload names.
        """
        svc, commands, token = armed()
        svc.note_intentional_disconnect(True, uuid=OTHER_DOCK)
        svc.observe_attachment(present=True, uuid=OTHER_DOCK)
        outcome = confirm(svc, token)
        self.assertFalse(outcome.requested)
        self.assertFalse(outcome.state.intentional_disconnect)
        # The service is not wrong about the bus: a disowned dock really is
        # attached. It is not the dock this outcome is about.
        self.assertTrue(svc.intentional_disconnect)
        self.assertEqual(commands.calls, [])


def verify(svc, token, **overrides):
    """Read back, naming the identity the reading was taken in by default."""
    call = {
        "authorized": True,
        "uuid": DOCK,
        "generation": svc.generation,
        **overrides,
    }
    return svc.record_verification(token, **call)


class VerificationIsReadBackNotAssumed(unittest.TestCase):
    """A readback is evidence about the device it was taken of, or nothing."""

    def test_the_reading_has_to_name_the_device_it_was_taken_of(self):
        """The signature is the fix: a readback with no identity cannot lie."""
        parameters = inspect.signature(
            DeviceAuthorizationService.record_verification
        ).parameters
        self.assertEqual(
            list(parameters), ["self", "token", "authorized", "uuid", "generation"]
        )
        for name in ("authorized", "uuid", "generation"):
            self.assertIs(
                parameters[name].kind, inspect.Parameter.KEYWORD_ONLY
            )

    def test_a_re_read_that_found_it_trusted_comes_back_true(self):
        svc, _, token = armed()
        confirm(svc, token)
        self.assertIs(verify(svc, token, authorized=True), True)

    def test_a_re_read_that_found_it_untrusted_comes_back_false(self):
        svc, _, token = armed()
        confirm(svc, token)
        self.assertIs(verify(svc, token, authorized=False), False)

    def test_an_unreadable_re_read_stays_unknown(self):
        svc, _, token = armed()
        confirm(svc, token)
        self.assertIsNone(verify(svc, token, authorized=None))

    def test_a_reading_that_is_not_a_reading_stays_unknown(self):
        """A truthy value is not somebody having read the device."""
        svc, _, token = armed()
        confirm(svc, token)
        for value in (1, 0, "yes", "", [1]):
            with self.subTest(authorized=repr(value)):
                self.assertIsNone(verify(svc, token, authorized=value))

    def test_a_reading_that_names_no_known_prompt_is_not_attributed(self):
        svc, _, token = armed()
        confirm(svc, token)
        for value in ("", None, 7, "deadbeef", DOCK):
            with self.subTest(token=repr(value)):
                self.assertIsNone(verify(svc, value))

    def test_a_reading_of_another_device_is_not_evidence_about_this_one(self):
        """The reproduced defect: verified=True drawn from somebody else."""
        svc, _, token = armed()
        confirm(svc, token)
        self.assertIsNone(verify(svc, token, uuid=OTHER_DOCK))

    def test_a_reading_that_could_not_be_identified_is_never_evidence(self):
        """Unidentifiable is the case `None` exists for, either way it read."""
        for authorized in (True, False):
            for value in ("", None, 7):
                with self.subTest(authorized=authorized, uuid=repr(value)):
                    svc, _, token = armed()
                    confirm(svc, token)
                    self.assertIsNone(
                        verify(svc, token, uuid=value, authorized=authorized)
                    )

    def test_a_reading_from_another_generation_is_not_evidence(self):
        svc, _, token = armed()
        confirm(svc, token)
        for value in (
            svc.generation + 1,
            svc.generation - 1,
            None,
            "1",
            1.0,
            True,
        ):
            with self.subTest(generation=repr(value)):
                self.assertIsNone(verify(svc, token, generation=value))

    def test_a_live_prompt_is_not_something_to_read_back(self):
        """Nothing was acted on, so there is nothing a reading can be about."""
        svc, _, token = armed()
        self.assertIsNone(verify(svc, token))

    def test_a_replug_forgets_the_prompt_it_could_be_attributed_to(self):
        svc, _, token = armed()
        confirm(svc, token)
        svc.observe_attachment(present=False, uuid="")
        self.assertIsNone(verify(svc, token, generation=svc.generation))


class NothingIsMintedForADeviceNobodyObserved(unittest.TestCase):
    """The reproduced defect: `boltd` driven against a uuid never observed."""

    def test_an_unobserved_device_gets_no_token(self):
        svc, _ = service()
        self.assertEqual(svc.candidate_token(DOCK), "")

    def test_a_device_that_is_not_the_observed_one_gets_no_token(self):
        svc, _, token = armed()
        self.assertEqual(svc.candidate_token(OTHER_DOCK), "")
        # And the real attachment is untouched by having been asked about.
        self.assertEqual(svc.candidate_token(DOCK), token)

    def test_an_unobserved_confirmation_never_reaches_the_executor(self):
        svc, commands = service()
        outcome = svc.confirm(
            svc.candidate_token(DOCK),
            consent=True,
            action="enroll",
            uuid=DOCK,
            generation=svc.generation,
            **NEW_DOCK,
        )
        self.assertFalse(outcome.requested)
        self.assertEqual(outcome.code, "device_authorization.token_stale")
        self.assertEqual(commands.calls, [])

    def test_a_confirmation_before_the_first_scan_cannot_enrol_twice(self):
        """The exact sequence: act at generation 0, then let a scan bump it.

        The spent marker belongs to the generation it was spent in, so a
        confirmation that completed before anything was observed was un-spent
        by the first real scan, and the same dock was offered and enrolled all
        over again.
        """
        svc, commands = service()
        early = svc.candidate_token(DOCK)
        svc.confirm(
            early,
            consent=True,
            action="enroll",
            uuid=DOCK,
            generation=svc.generation,
            **NEW_DOCK,
        )
        svc.observe_attachment(present=True, uuid=DOCK)
        self.assertTrue(confirm(svc, svc.candidate_token(DOCK)).requested)
        self.assertEqual(commands.calls, [("enroll", DOCK)])

    def test_the_observed_identity_is_what_confirm_checks(self):
        """Not the token's own record of itself, which agrees with itself."""
        svc, commands, token = armed()
        svc.observe_attachment(present=True, uuid=OTHER_DOCK)
        outcome = confirm(svc, token, uuid=OTHER_DOCK, generation=svc.generation)
        self.assertFalse(outcome.requested)
        self.assertEqual(commands.calls, [])

    def test_the_tokens_own_record_is_not_what_lets_a_confirmation_through(
        self,
    ):
        """The same claim, with the layer in front of it taken out of the way.

        The case above cannot actually reach it.  Observing the other dock
        *retires* the attachment, which drops the token, so the confirmation
        is refused as `token_stale` before `_confirm_locked` ever compares an
        identity -- and the same is true of the swapped-dock journey in
        `tests/test_device_authorization_composition.py`.  Every route in is
        stopped a layer early, which is why deleting `uuid != self._uuid` from
        that comparison leaves every other test in this repository green.

        What is left standing is the token's own record, and the module
        docstring is explicit that the record is *not* the authority: "a record
        that agrees only with itself is how a UUID nobody had ever seen reached
        `boltd`".  Today the two cannot disagree, because `_mint_token` will
        only bind a token to the id this layer observed -- so the disagreement
        is set up here directly, which is the honest way to test the inner half
        of a defence in depth: the outer guard is removed, and the inner one
        has to refuse on its own.  Without it the executor is handed a device
        the observation layer never saw.
        """
        svc, commands, token = armed()
        # The drift `_mint_token` exists to prevent: a live token whose record
        # names a device this layer never observed. `_uuid` is still DOCK.
        svc._token_uuid = OTHER_DOCK
        outcome = confirm(svc, token, uuid=OTHER_DOCK)
        self.assertFalse(outcome.requested)
        self.assertEqual(
            outcome.code,
            "device_authorization.attachment_changed",
            "the observed identity was not what refused this",
        )
        self.assertEqual(
            commands.calls,
            [],
            "boltd was driven against a device nobody observed",
        )


class AnAbsentPollIsNotAnEvent(unittest.TestCase):
    """The reproduced defect: undocked is the default state, not a change."""

    def test_polling_an_empty_port_never_ticks_the_generation(self):
        svc, _ = service()
        for _ in range(1000):
            svc.observe_attachment(present=False, uuid="")
        self.assertEqual(svc.generation, 0)

    def test_an_absence_retires_once_and_then_stops(self):
        svc, _, _ = armed()
        attached = svc.generation
        svc.observe_attachment(present=False, uuid="")
        retired = svc.generation
        self.assertGreater(retired, attached)
        for _ in range(50):
            svc.observe_attachment(present=False, uuid="")
        self.assertEqual(svc.generation, retired)

    def test_the_deprecated_shim_settles_too(self):
        svc, _, _ = armed()
        svc.observe_device(False)
        retired = svc.generation
        for _ in range(50):
            svc.observe_device(False)
        self.assertEqual(svc.generation, retired)

    def test_a_disowned_dock_is_not_something_left_to_retire(self):
        """The record outlives attachments, so it must not look like one.

        Counting it as something to retire would put the retire back on every
        poll of an empty port, and the generation would count polls again --
        the defect this class exists for, re-entered through the new state.
        """
        svc, _, _ = armed()
        svc.note_intentional_disconnect(True, uuid=DOCK)
        svc.observe_attachment(present=False, uuid="")
        retired = svc.generation
        for _ in range(200):
            svc.observe_attachment(present=False, uuid="")
        self.assertEqual(svc.generation, retired)
        svc.observe_attachment(present=True, uuid=DOCK)
        self.assertFalse(svc.assess(**NEW_DOCK).offered)

    def test_a_declined_prompt_still_retires_exactly_once(self):
        """The latch is something to retire; the poll after it is not."""
        svc, _, token = armed()
        svc.decline(token)
        svc.observe_attachment(present=False, uuid="")
        retired = svc.generation
        for _ in range(20):
            svc.observe_attachment(present=False, uuid="")
        self.assertEqual(svc.generation, retired)

    def test_a_spent_token_still_retires_exactly_once(self):
        """The one piece of attachment state only a confirmation leaves.

        The spent token is written by confirming and by nothing else, so every
        case above arrives at the absence with that field empty and never asks
        whether the retire clears it.  Left behind, it is one more thing an
        attachment can still be recognised by, and the poll after the retire
        finds something to retire all over again -- this class's own defect,
        re-entered through the single field none of the others had set.

        So this case confirms first, and then holds the empty port to the same
        rule: retired once, and after that nothing.
        """
        svc, commands, token = armed()
        attached = svc.generation
        self.assertTrue(confirm(svc, token).requested)
        self.assertEqual(commands.calls, [("enroll", DOCK)])
        # The token is spent rather than gone: it is what a readback about
        # this dock is still admitted by.
        self.assertIs(
            svc.record_verification(
                token, authorized=True, uuid=DOCK, generation=attached
            ),
            True,
        )

        svc.observe_attachment(present=False, uuid="")
        retired = svc.generation
        self.assertGreater(retired, attached)

        # It went with the attachment, so nothing about the dock that left is
        # still answerable...
        self.assertIsNone(
            svc.record_verification(
                token, authorized=True, uuid=DOCK, generation=attached
            )
        )
        # ...and there is nothing for the next poll of the empty port to find.
        for _ in range(50):
            svc.observe_attachment(present=False, uuid="")
        self.assertEqual(svc.generation, retired)

    def test_presence_is_read_by_identity(self):
        """Only the literal False is an absence; the rest say nothing.

        Each value arrives naming a *real* dock, and a different one from the
        attached device.  Driving these with `uuid=""` measured nothing: an
        unnamed reading is stopped by the identity check below the presence
        guard whatever `present` was, so the case answered the same with the
        guard and without it.  A named one is what the guard is actually
        holding back -- read as presence, an unreadable `0` retires this
        attachment and adopts the dock it names, taking the generation, the
        latch, the token and the disownership with it.

        So the assertion is the whole observable state, not the generation
        alone: nothing about this reading may reach any of it.
        """
        for value in (0, "", [], 0.0, "no"):
            with self.subTest(present=repr(value)):
                svc, commands, token = armed()
                svc.acknowledge(token)
                #: Disowned, and *not* the attached device: if the reading were
                #: believed, `OTHER_DOCK` becomes the attachment and the flag
                #: about it starts answering for the port.
                svc.note_intentional_disconnect(True, uuid=OTHER_DOCK)
                before = svc.generation

                svc.observe_attachment(present=value, uuid=OTHER_DOCK)

                self.assertEqual(svc.generation, before)
                # The latch this attachment spent, still spent, and its one
                # token still the same token.
                self.assertTrue(svc.offered)
                self.assertTrue(svc.confirmation_open)
                self.assertEqual(svc.candidate_token(DOCK), token)
                self.assertEqual(
                    svc.assess(**NEW_DOCK).code,
                    "device_authorization.already_offered",
                )
                # The attached identity is untouched: the named dock did not
                # become the attachment, so it mints nothing and the record
                # about it is not the answer for this port.
                self.assertEqual(svc.candidate_token(OTHER_DOCK), "")
                self.assertFalse(svc.intentional_disconnect)
                self.assertEqual(commands.calls, [])


class TheOutcomeIsTheExecutorsOwnWords(unittest.TestCase):
    """The port's result code travels unedited, and the id travels nowhere.

    Those are two different claims and only one of them is about content.
    SAFETY_INVARIANTS #12 is kept by not copying the uuid out of this layer,
    which is enforceable; it is not kept by inspecting text that arrived from
    a port, which was tried twice and cost the one message a player could have
    acted on.
    """

    def test_requested_is_a_boolean_not_whatever_the_port_returned(self):
        """`requested == "yes"` is a payload field nobody can read twice."""
        for value in ("yes", 1, [1], 0, None, ""):
            with self.subTest(enrolled=repr(value)):
                svc, _, token = armed(
                    result=DeviceEnrollmentResult(value, ACCEPTED)
                )
                outcome = confirm(svc, token)
                self.assertIs(outcome.requested, False)

    def test_a_real_acceptance_is_still_a_real_acceptance(self):
        svc, _, token = armed()
        self.assertIs(confirm(svc, token).requested, True)

    def test_an_ordinary_code_is_passed_through_unedited(self):
        svc, _, token = armed()
        self.assertEqual(confirm(svc, token).code, ACCEPTED)

    def test_the_diagnostic_worth_reading_is_the_one_that_survives(self):
        """The reproduced defect that removed the filter.

        A code is the only place a failed act can say what went wrong. The
        hex-class filter refused a code whole once its count crossed a limit,
        and a real diagnostic -- the sentence saying the daemon is not running,
        or why it refused -- is long and dense enough to cross it, while the
        short generic codes this feature emits itself never came close. So the
        rule reliably dropped the messages with information in them and kept
        the ones without, and the player was handed a stand-in where the reason
        had been.
        """
        for code in (
            "Failed to connect to boltd: Could not connect: "
            "No such file or directory",
            "boltd is not running; start bolt.service and plug the dock "
            "back in",
            "org.freedesktop.bolt.Error: device 0-1 refused the enrolment",
        ):
            with self.subTest(code=code):
                svc, _, token = armed(
                    result=DeviceEnrollmentResult(True, code)
                )
                self.assertEqual(confirm(svc, token).code, code)

    def test_a_code_there_is_nothing_to_repeat_of_gets_the_stand_in(self):
        """The only substitution left: `code` is typed `str` and has to be one."""
        for value in (None, "", 7, [1], {"code": "x"}):
            with self.subTest(code=repr(value)):
                svc, _, token = armed(
                    result=DeviceEnrollmentResult(True, value)
                )
                self.assertEqual(
                    confirm(svc, token).code,
                    "device_authorization.result_unreportable",
                )

    def test_every_code_this_feature_emits_is_reported_as_itself(self):
        for code in (
            ACCEPTED,
            "device_authorization.enroll_failed",
            "device_authorization.enroll_timeout",
            "device_authorization.enroll_unavailable",
            "device_authorization.root_required",
            "device_authorization.uuid_invalid",
            "device_authorization.authorize_accepted_unverified",
            "device_authorization.result_unreportable",
        ):
            with self.subTest(code=code):
                svc, _, token = armed(
                    result=DeviceEnrollmentResult(True, code)
                )
                self.assertEqual(confirm(svc, token).code, code)

    def test_this_layer_never_copies_the_uuid_into_an_outcome(self):
        """The guarantee that is Re-Gear's to make, for a normal device.

        The executor is handed the real id because it has to name the device to
        `boltd`. Nothing that comes back out carries it: not the token, not the
        code, not the flags.
        """
        svc, commands, token = armed()
        outcome = confirm(svc, token)
        self.assertEqual(commands.calls, [("enroll", DOCK)])
        squashed = DOCK.replace("-", "")
        for field in (outcome.token, outcome.code):
            self.assertNotIn(DOCK, field)
            self.assertNotIn(squashed, field.replace("-", ""))
        self.assertNotIn(DOCK, repr(outcome))


class SingleFlightUnderRealThreads(unittest.TestCase):
    """A sequential double press proves consumability, not mutual exclusion."""

    def _race(self, workers, work):
        barrier = threading.Barrier(workers)
        results: list = []
        guard = threading.Lock()

        def run(index):
            barrier.wait()
            value = work(index)
            with guard:
                results.append(value)

        threads = [
            threading.Thread(target=run, args=(i,)) for i in range(workers)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        for thread in threads:
            self.assertFalse(thread.is_alive(), "a racing caller never returned")
        return results

    def test_eight_threads_pressing_one_token_enrol_exactly_once(self):
        svc, commands, token = armed(delay=0.05)
        outcomes = self._race(8, lambda _index: confirm(svc, token))
        self.assertEqual(
            commands.calls,
            [("enroll", DOCK)],
            "the same prompt reached boltd more than once",
        )
        self.assertEqual(commands.max_overlap, 1)
        accepted = [o for o in outcomes if o.requested]
        refused = [o for o in outcomes if not o.requested]
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(outcomes), 8)
        self.assertTrue(
            all(o.code == "device_authorization.token_stale" for o in refused)
        )

    def test_polling_while_a_confirmation_runs_never_mints_a_second_token(self):
        svc, commands, token = armed(delay=0.05)

        def work(index):
            if index == 0:
                return ("confirm", confirm(svc, token))
            return ("poll", svc.candidate_token(DOCK))

        results = self._race(6, work)
        self.assertEqual(commands.calls, [("enroll", DOCK)])
        minted = {value for kind, value in results if kind == "poll"}
        # A poll either saw the live token or saw a spent generation. It must
        # never have produced a different one.
        self.assertTrue(minted <= {token, ""}, f"a poll minted {minted!r}")
        self.assertEqual(svc.candidate_token(DOCK), "")

    def test_acknowledge_and_decline_racing_leave_one_coherent_state(self):
        """Both endings are raced, and each is asserted for what it is.

        A mix of the two can only end one way, and the branch that waited for
        the other ending was never once taken: the first decline to reach the
        lock drops the token, no later acknowledge can bring it back, and one
        decline among six workers is enough. So the open-confirmation ending is
        raced where it is actually reachable -- every worker acknowledging --
        and the expected ending is named per mix rather than discovered from
        the state under test.
        """
        for declines, still_open in ((0, True), (1, False), (3, False)):
            with self.subTest(declines=declines):
                svc, commands, token = armed()

                def work(index, declines=declines):
                    if index < declines:
                        return svc.decline(token)
                    return svc.acknowledge(token)

                answers = self._race(6, work)
                self.assertEqual(len(answers), 6)
                self.assertTrue(svc.offered)
                self.assertEqual(commands.calls, [])
                self.assertIs(svc.confirmation_open, still_open)
                if still_open:
                    # Nothing dropped the token, so every acknowledge took and
                    # the prompt on screen is still answerable.
                    self.assertTrue(all(answers), answers)
                    self.assertEqual(svc.candidate_token(DOCK), token)
                else:
                    # A decline landed and took the token with it, so whatever
                    # else got through, nothing is left to answer or re-offer.
                    self.assertIn(True, answers)
                    self.assertEqual(svc.candidate_token(DOCK), "")


if __name__ == "__main__":
    unittest.main()
