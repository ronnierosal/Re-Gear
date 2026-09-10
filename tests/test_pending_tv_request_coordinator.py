from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.pending_tv_request import (  # noqa: E402
    PendingTvRequestCoordinator,
)
from regear.application.saved_tv_search import SavedTvSearch  # noqa: E402
from regear.domain.control_plane import RequestSource  # noqa: E402
from regear.domain.models import (  # noqa: E402
    Confidence,
    DisplayKind,
    DisplayObservation,
    GameState,
)
from regear.domain.pending_tv_request import PendingTvState  # noqa: E402
from regear.domain.saved_tv import SavedTvProfile  # noqa: E402


ATTACHMENT = "egpu:e3b0c44298fc1c14"
OTHER_ATTACHMENT = "egpu:1111222233334444"
GENERATION = "observation-41"

PROFILE = SavedTvProfile(
    display_stable_id="display:9f2c41ab77e0d135",
    edid_identified=True,
    label="Living room TV",
)

OTHER_PROFILE = SavedTvProfile(
    display_stable_id="display:5511aa22bb33cc44",
    edid_identified=True,
    label="Bedroom TV",
)

TV = DisplayObservation(
    stable_id="display:9f2c41ab77e0d135",
    kind=DisplayKind.EXTERNAL,
    connector="HDMI-A-1",
    connected=True,
    active=False,
    edid_ready=True,
    confidence=Confidence.VERIFIED,
)

PANEL = DisplayObservation(
    stable_id="internal-panel",
    kind=DisplayKind.INTERNAL,
    connector="eDP-1",
    connected=True,
    active=True,
    edid_ready=True,
    confidence=Confidence.VERIFIED,
)


class FakeStore:
    def __init__(self, profile=None, error=None):
        self.profile = profile
        self.error = error
        self.loads = 0
        self.records = []
        self.forgets = 0

    def load(self):
        self.loads += 1
        if self.error is not None:
            raise self.error
        return self.profile

    def record(self, profile):
        self.records.append(profile)
        self.profile = profile

    def forget(self):
        self.forgets += 1
        self.profile = None


def coordinator(profile=PROFILE, *, error=None, max_attempts=4):
    store = FakeStore(profile, error)
    search = SavedTvSearch(store)
    return PendingTvRequestCoordinator(search, max_attempts=max_attempts), store, search


def observe(subject, **overrides):
    values = {
        "attachment_binding": ATTACHMENT,
        "displays": (PANEL,),
        "scan_complete": True,
        "observed_generation": GENERATION,
        "game_state": GameState.IDLE,
    }
    values.update(overrides)
    return subject.observe(**values)


def request(subject):
    return subject.request(
        request_id="request-7f21",
        source=RequestSource.MANUAL,
        attachment_binding=ATTACHMENT,
    )


class LifecycleTests(unittest.TestCase):
    def test_no_request_reports_nothing_outstanding(self):
        subject, _store, _search = coordinator()

        status = observe(subject)

        self.assertIs(status.state, PendingTvState.NONE)
        self.assertEqual(status.code, "pending_tv.no_request")
        self.assertFalse(status.approval_offered)
        self.assertFalse(subject.outstanding)

    def test_request_binds_to_the_remembered_tv(self):
        subject, _store, _search = coordinator()

        status = request(subject)

        self.assertIs(status.state, PendingTvState.WAITING)
        self.assertEqual(status.code, "pending_tv.requested")
        self.assertTrue(subject.outstanding)
        self.assertEqual(status.max_attempts, 4)

    def test_an_unreadable_record_refuses_the_request(self):
        subject, _store, _search = coordinator(None, error=ValueError("symlink"))

        status = request(subject)

        self.assertIs(status.state, PendingTvState.REJECTED)
        self.assertEqual(status.code, "pending_tv.record_unreadable")
        self.assertFalse(subject.outstanding)

    def test_cancel_is_explicit_and_immediate(self):
        subject, _store, _search = coordinator()
        request(subject)

        status = subject.cancel()

        self.assertIs(status.state, PendingTvState.CANCELLED)
        self.assertEqual(status.code, "pending_tv.cancelled")
        self.assertFalse(subject.outstanding)
        self.assertIs(observe(subject).state, PendingTvState.NONE)

    def test_cancel_without_a_request_is_a_no_op(self):
        subject, _store, _search = coordinator()

        status = subject.cancel()

        self.assertIs(status.state, PendingTvState.NONE)

    def test_a_second_request_replaces_the_first_and_rearms(self):
        subject, _store, _search = coordinator()
        request(subject)
        observe(subject)
        observe(subject)
        self.assertEqual(subject.attempts, 2)

        status = request(subject)

        self.assertEqual(subject.attempts, 0)
        self.assertEqual(status.attempts, 0)

    def test_a_succeeded_transition_retires_the_request(self):
        subject, _store, _search = coordinator()
        request(subject)

        status = subject.satisfied()

        self.assertIs(status.state, PendingTvState.NONE)
        self.assertEqual(status.code, "pending_tv.satisfied")
        self.assertFalse(subject.outstanding)

    def test_the_coordinator_never_writes_the_record(self):
        subject, store, _search = coordinator()
        request(subject)
        observe(subject)
        observe(subject, displays=(PANEL, TV))
        subject.cancel()

        self.assertEqual(store.records, [])
        self.assertEqual(store.forgets, 0)


class BudgetTests(unittest.TestCase):
    def test_only_a_finished_look_spends_the_budget(self):
        subject, _store, _search = coordinator()
        request(subject)

        observe(subject)
        self.assertEqual(subject.attempts, 1)
        observe(subject, scan_complete=False)
        self.assertEqual(subject.attempts, 1)

    def test_repeated_failed_scans_never_exhaust_the_budget(self):
        subject, _store, _search = coordinator()
        request(subject)

        for _ in range(20):
            status = observe(subject, scan_complete=False)

        self.assertIs(status.state, PendingTvState.UNOBSERVABLE)
        self.assertEqual(status.code, "pending_tv.display_scan_incomplete")
        self.assertEqual(subject.attempts, 0)
        self.assertTrue(subject.outstanding)

    def test_waiting_is_bounded_and_settles_into_not_found(self):
        subject, _store, _search = coordinator(max_attempts=3)
        request(subject)

        states = [observe(subject).state for _ in range(4)]

        self.assertEqual(
            states,
            [
                PendingTvState.WAITING,
                PendingTvState.WAITING,
                PendingTvState.WAITING,
                PendingTvState.NOT_FOUND,
            ],
        )
        self.assertTrue(subject.outstanding)

    def test_rearm_resumes_the_same_request_from_zero(self):
        subject, _store, _search = coordinator(max_attempts=2)
        request(subject)
        observe(subject)
        observe(subject)
        self.assertIs(observe(subject).state, PendingTvState.NOT_FOUND)

        status = subject.rearm()

        self.assertIs(status.state, PendingTvState.WAITING)
        self.assertEqual(status.code, "pending_tv.rearmed")
        self.assertEqual(subject.attempts, 0)
        self.assertIs(observe(subject).state, PendingTvState.WAITING)

    def test_rearm_without_a_request_is_a_no_op(self):
        subject, _store, _search = coordinator()

        self.assertIs(subject.rearm().state, PendingTvState.NONE)

    def test_a_found_tv_does_not_spend_the_budget(self):
        subject, _store, _search = coordinator()
        request(subject)

        observe(subject, displays=(PANEL, TV), game_state=GameState.RUNNING)

        self.assertEqual(subject.attempts, 0)


class ReadyArrivalTests(unittest.TestCase):
    def test_late_hdmi_offers_the_existing_approval_path(self):
        subject, _store, _search = coordinator()
        request(subject)
        observe(subject)

        status = observe(subject, displays=(PANEL, TV))

        self.assertIs(status.state, PendingTvState.READY)
        self.assertEqual(status.code, "pending_tv.ready")
        self.assertTrue(status.approval_offered)
        self.assertEqual(status.blockers, ())
        self.assertFalse(subject.outstanding)

    def test_the_handoff_names_the_detected_display_and_is_taken_once(self):
        subject, _store, _search = coordinator()
        request(subject)
        observe(subject, displays=(PANEL, TV))

        handoff = subject.take_handoff()

        self.assertIsNotNone(handoff)
        self.assertEqual(handoff.display_stable_id, TV.stable_id)
        self.assertEqual(handoff.attachment_binding, ATTACHMENT)
        self.assertEqual(handoff.observed_generation, GENERATION)
        self.assertIsNone(subject.take_handoff())

    def test_a_running_game_blocks_the_offer_without_losing_the_request(self):
        subject, _store, _search = coordinator()
        request(subject)

        status = observe(
            subject, displays=(PANEL, TV), game_state=GameState.RUNNING
        )

        self.assertIs(status.state, PendingTvState.READY)
        self.assertFalse(status.approval_offered)
        self.assertFalse(status.automatic_continuation)
        self.assertEqual(status.blockers, ("pending_tv.game_running",))
        self.assertTrue(subject.outstanding)
        self.assertIsNone(subject.take_handoff())

    def test_the_offer_appears_once_the_game_closes(self):
        subject, _store, _search = coordinator()
        request(subject)
        observe(subject, displays=(PANEL, TV), game_state=GameState.RUNNING)

        status = observe(subject, displays=(PANEL, TV), game_state=GameState.IDLE)

        self.assertTrue(status.approval_offered)
        self.assertIsNotNone(subject.take_handoff())

    def test_unknown_game_evidence_fails_closed(self):
        subject, _store, _search = coordinator()
        request(subject)

        status = observe(
            subject, displays=(PANEL, TV), game_state=GameState.UNKNOWN
        )

        self.assertIs(status.state, PendingTvState.READY)
        self.assertFalse(status.approval_offered)
        self.assertEqual(status.blockers, ("pending_tv.game_state_unknown",))
        self.assertTrue(subject.outstanding)

    def test_a_found_tv_is_reported_ready_whatever_the_game_is_doing(self):
        # Display target and running-game state stay independent: the game
        # never changes what is true about the TV, only what may be offered.
        for game_state in (GameState.IDLE, GameState.RUNNING, GameState.UNKNOWN):
            subject, _store, _search = coordinator()
            request(subject)
            status = observe(subject, displays=(PANEL, TV), game_state=game_state)
            self.assertIs(status.state, PendingTvState.READY, game_state)
            self.assertEqual(status.code, "pending_tv.ready", game_state)

    def test_no_state_but_ready_ever_offers_the_approval_path(self):
        cases = {
            PendingTvState.WAITING: {},
            PendingTvState.UNOBSERVABLE: {"scan_complete": False},
            PendingTvState.INVALIDATED: {"attachment_binding": OTHER_ATTACHMENT},
        }
        for state, overrides in cases.items():
            subject, _store, _search = coordinator()
            request(subject)
            status = observe(subject, **overrides)
            self.assertIs(status.state, state)
            self.assertFalse(status.approval_offered, state)
            self.assertFalse(status.automatic_continuation, state)
            self.assertIsNone(subject.take_handoff(), state)


class AutomaticContinuationTests(unittest.TestCase):
    def test_the_preference_gates_automatic_continuation(self):
        subject, _store, _search = coordinator()
        request(subject)

        status = observe(
            subject, displays=(PANEL, TV), automatic_preference_enabled=True
        )

        self.assertTrue(status.approval_offered)
        self.assertTrue(status.automatic_continuation)

    def test_without_the_preference_only_the_manual_offer_stands(self):
        subject, _store, _search = coordinator()
        request(subject)

        status = observe(
            subject, displays=(PANEL, TV), automatic_preference_enabled=False
        )

        self.assertTrue(status.approval_offered)
        self.assertFalse(status.automatic_continuation)

    def test_a_deliberate_return_to_the_handheld_is_not_undone(self):
        subject, _store, _search = coordinator()
        request(subject)

        status = observe(
            subject,
            displays=(PANEL, TV),
            automatic_preference_enabled=True,
            portable_return_suppressed=True,
        )

        self.assertFalse(status.automatic_continuation)
        # The player may still ask for the TV themselves; suppression bounds
        # the automatic path, not their own explicit request.
        self.assertTrue(status.approval_offered)

    def test_an_unbound_request_is_never_continued_automatically(self):
        subject, _store, _search = coordinator(None)
        request(subject)

        status = observe(
            subject, displays=(PANEL, TV), automatic_preference_enabled=True
        )

        self.assertIs(status.state, PendingTvState.READY)
        self.assertTrue(status.approval_offered)
        self.assertFalse(status.automatic_continuation)


class ChangedDockTests(unittest.TestCase):
    def test_a_changed_attachment_invalidates_the_request(self):
        subject, _store, _search = coordinator()
        request(subject)

        status = observe(
            subject, attachment_binding=OTHER_ATTACHMENT, displays=(PANEL, TV)
        )

        self.assertIs(status.state, PendingTvState.INVALIDATED)
        self.assertEqual(status.code, "pending_tv.attachment_changed")
        self.assertFalse(subject.outstanding)

    def test_an_absent_attachment_invalidates_the_request(self):
        subject, _store, _search = coordinator()
        request(subject)

        status = observe(subject, attachment_binding="")

        self.assertIs(status.state, PendingTvState.INVALIDATED)
        self.assertEqual(status.code, "pending_tv.attachment_absent")
        self.assertFalse(subject.outstanding)

    def test_a_changed_tv_record_invalidates_rather_than_retargets(self):
        subject, store, search = coordinator()
        request(subject)
        store.profile = OTHER_PROFILE
        search.rearm()

        status = observe(subject, displays=(PANEL, TV))

        self.assertIs(status.state, PendingTvState.INVALIDATED)
        self.assertEqual(status.code, "pending_tv.target_changed")
        self.assertFalse(subject.outstanding)

    def test_a_record_that_appears_under_an_unbound_request_invalidates_it(self):
        subject, store, search = coordinator(None)
        request(subject)
        store.profile = PROFILE
        search.rearm()

        status = observe(subject, displays=(PANEL, TV))

        self.assertIs(status.state, PendingTvState.INVALIDATED)
        self.assertEqual(status.code, "pending_tv.target_changed")

    def test_an_unreadable_record_keeps_the_request_and_spends_nothing(self):
        subject, store, search = coordinator()
        request(subject)
        store.error = OSError("record vanished")
        search.rearm()

        status = observe(subject, displays=(PANEL, TV))

        self.assertIs(status.state, PendingTvState.UNOBSERVABLE)
        self.assertEqual(status.code, "pending_tv.record_unreadable")
        self.assertTrue(subject.outstanding)
        self.assertEqual(subject.attempts, 0)
        self.assertFalse(status.approval_offered)


class ConnectorDerivedIdentityTests(unittest.TestCase):
    def test_a_socket_identity_ends_the_search_rather_than_waiting(self):
        subject, _store, _search = coordinator(
            replace(PROFILE, edid_identified=False)
        )
        request(subject)

        status = observe(subject, displays=(PANEL, TV))

        self.assertIs(status.state, PendingTvState.NOT_FOUND)
        self.assertEqual(status.code, "pending_tv.identity_not_verifiable")
        self.assertFalse(status.approval_offered)
        self.assertIsNone(subject.take_handoff())


if __name__ == "__main__":
    unittest.main()
