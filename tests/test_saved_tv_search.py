from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.application.saved_tv_search import SavedTvSearch  # noqa: E402
from hdm.domain.models import (  # noqa: E402
    Confidence,
    DisplayKind,
    DisplayObservation,
)
from hdm.domain.saved_tv import (  # noqa: E402
    SavedTvProfile,
    SavedTvState,
)


PROFILE = SavedTvProfile(
    display_stable_id="display:9f2c41ab77e0d135",
    edid_identified=True,
    label="Living room TV",
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


def search(profile=PROFILE, error=None, max_attempts=3):
    store = FakeStore(profile, error)
    return SavedTvSearch(store, max_attempts=max_attempts), store


class BudgetTests(unittest.TestCase):
    def test_a_finished_look_that_missed_spends_the_budget(self) -> None:
        subject, _ = search()

        subject.observe(displays=(PANEL,), scan_complete=True)

        self.assertEqual(subject.attempts, 1)

    def test_an_unfinished_look_never_spends_the_budget(self) -> None:
        # A reader that keeps failing must not exhaust the attempts and
        # abandon a TV that was there the whole time.
        subject, _ = search()

        for _ in range(20):
            decision = subject.observe(displays=(), scan_complete=False)

        self.assertEqual(subject.attempts, 0)
        self.assertIs(decision.state, SavedTvState.UNOBSERVABLE)

    def test_finding_it_does_not_spend_the_budget(self) -> None:
        subject, _ = search()

        decision = subject.observe(displays=(PANEL, TV), scan_complete=True)

        self.assertIs(decision.state, SavedTvState.READY)
        self.assertEqual(subject.attempts, 0)

    def test_having_no_saved_tv_does_not_spend_the_budget(self) -> None:
        # Otherwise a player who never docked anywhere accumulates attempts
        # against a search that was never running.
        subject, _ = search(profile=None)

        for _ in range(10):
            decision = subject.observe(displays=(PANEL,), scan_complete=True)

        self.assertIs(decision.state, SavedTvState.NONE)
        self.assertEqual(subject.attempts, 0)

    def test_the_search_settles_once_the_budget_is_spent(self) -> None:
        subject, _ = search(max_attempts=3)

        states = [
            subject.observe(displays=(PANEL,), scan_complete=True).state
            for _ in range(5)
        ]

        self.assertEqual(states[:3], [SavedTvState.WAITING] * 3)
        self.assertEqual(states[3], SavedTvState.SETTLED)
        self.assertEqual(states[4], SavedTvState.SETTLED)


class RearmTests(unittest.TestCase):
    def test_a_new_dock_gets_a_fresh_search(self) -> None:
        # The budget bounds one attempt to find the TV, not the lifetime of
        # the plugin. Docking again is asking again.
        subject, _ = search(max_attempts=2)
        for _ in range(5):
            subject.observe(displays=(PANEL,), scan_complete=True)
        self.assertIs(
            subject.observe(displays=(PANEL,), scan_complete=True).state,
            SavedTvState.SETTLED,
        )

        subject.rearm()

        self.assertEqual(subject.attempts, 0)
        self.assertIs(
            subject.observe(displays=(PANEL,), scan_complete=True).state,
            SavedTvState.WAITING,
        )

    def test_a_settled_search_still_recognises_the_tv_if_it_appears(self) -> None:
        subject, _ = search(max_attempts=1)
        for _ in range(4):
            subject.observe(displays=(PANEL,), scan_complete=True)

        decision = subject.observe(displays=(PANEL, TV), scan_complete=True)

        self.assertIs(decision.state, SavedTvState.READY)

    def test_rearming_re_reads_the_record(self) -> None:
        subject, store = search()
        subject.observe(displays=(PANEL,), scan_complete=True)
        self.assertEqual(store.loads, 1)

        subject.rearm()
        subject.observe(displays=(PANEL,), scan_complete=True)

        self.assertEqual(store.loads, 2)

    def test_the_record_is_read_once_per_search_not_once_per_reading(self) -> None:
        subject, store = search()

        for _ in range(6):
            subject.observe(displays=(PANEL,), scan_complete=True)

        self.assertEqual(store.loads, 1)


class RememberTests(unittest.TestCase):
    def test_a_successful_dock_is_written_and_re_arms_the_search(self) -> None:
        subject, store = search(profile=None, max_attempts=2)
        for _ in range(3):
            subject.observe(displays=(PANEL,), scan_complete=True)

        written = subject.remember(
            display=TV, transition_succeeded=True, label="Living room TV"
        )

        self.assertIsNotNone(written)
        self.assertEqual(store.records, [written])
        self.assertEqual(subject.attempts, 0)

    def test_a_transition_that_did_not_succeed_writes_nothing(self) -> None:
        subject, store = search(profile=None)

        self.assertIsNone(
            subject.remember(display=TV, transition_succeeded=False)
        )
        self.assertEqual(store.records, [])

    def test_what_was_just_docked_to_is_what_gets_resumed(self) -> None:
        subject, _ = search(profile=None)
        subject.remember(display=TV, transition_succeeded=True)

        decision = subject.observe(displays=(PANEL, TV), scan_complete=True)

        self.assertIs(decision.state, SavedTvState.READY)
        self.assertEqual(decision.display_stable_id, TV.stable_id)

    def test_forgetting_clears_the_record_and_the_search(self) -> None:
        subject, store = search()
        subject.observe(displays=(PANEL,), scan_complete=True)

        subject.forget()

        self.assertEqual(store.forgets, 1)
        self.assertEqual(subject.attempts, 0)
        self.assertIs(
            subject.observe(displays=(PANEL,), scan_complete=True).state,
            SavedTvState.NONE,
        )


class UnreadableRecordTests(unittest.TestCase):
    """A record that cannot be read is "cannot tell", never "no saved TV"."""

    def test_a_refused_record_does_not_read_as_having_none(self) -> None:
        # Reading it as absent would silently stop resuming and look exactly
        # like the feature was never set up.
        subject, _ = search(error=ValueError("saved TV record cannot be a symlink"))

        decision = subject.observe(displays=(PANEL, TV), scan_complete=True)

        self.assertIs(decision.state, SavedTvState.UNOBSERVABLE)
        self.assertEqual(decision.code, "saved_tv.record_unreadable")
        self.assertIsNot(decision.state, SavedTvState.NONE)

    def test_a_refused_record_never_switches_a_display(self) -> None:
        subject, _ = search(error=ValueError("refused"))

        decision = subject.observe(displays=(PANEL, TV), scan_complete=True)

        self.assertFalse(decision.may_continue)

    def test_a_refused_record_does_not_raise_into_a_polling_loop(self) -> None:
        subject, _ = search(error=OSError("gone"))

        for _ in range(5):
            subject.observe(displays=(PANEL,), scan_complete=True)

        self.assertEqual(subject.attempts, 0)


class ContractTests(unittest.TestCase):
    def test_only_ready_may_continue(self) -> None:
        cases = [
            search()[0].observe(displays=(PANEL, TV), scan_complete=True),
            search()[0].observe(displays=(PANEL,), scan_complete=True),
            search()[0].observe(displays=(), scan_complete=False),
            search(profile=None)[0].observe(displays=(PANEL,), scan_complete=True),
            search(error=ValueError("x"))[0].observe(
                displays=(PANEL, TV), scan_complete=True
            ),
            search(profile=replace(PROFILE, edid_identified=False))[0].observe(
                displays=(PANEL, TV), scan_complete=True
            ),
        ]

        for decision in cases:
            self.assertEqual(
                decision.may_continue,
                decision.state is SavedTvState.READY,
                decision.code,
            )


class TargetTests(unittest.TestCase):
    def test_the_remembered_tv_is_readable(self) -> None:
        subject, _ = search()

        target = subject.target()

        self.assertTrue(target.readable)
        self.assertEqual(target.profile, PROFILE)

    def test_nothing_remembered_is_still_readable(self) -> None:
        # The distinction a caller binding a request depends on: "no saved TV"
        # is an answer, "cannot tell" is not.
        subject, _ = search(profile=None)

        target = subject.target()

        self.assertTrue(target.readable)
        self.assertIsNone(target.profile)

    def test_an_unreadable_record_is_reported_as_cannot_tell(self) -> None:
        for error in (ValueError("symlink"), OSError("gone")):
            subject, _ = search(error=error)

            target = subject.target()

            self.assertFalse(target.readable, error)
            self.assertIsNone(target.profile, error)

    def test_asking_both_questions_reads_the_record_once(self) -> None:
        subject, store = search()

        subject.target()
        subject.observe(displays=(PANEL,), scan_complete=True)
        subject.target()

        self.assertEqual(store.loads, 1)

    def test_rearming_re_reads_the_record_for_the_target_too(self) -> None:
        subject, store = search()
        subject.target()

        subject.rearm()
        store.profile = replace(PROFILE, label="Bedroom TV")

        self.assertEqual(subject.target().profile.label, "Bedroom TV")
        self.assertEqual(store.loads, 2)

    def test_remembering_updates_the_target_without_another_read(self) -> None:
        subject, store = search(profile=None)
        subject.target()

        subject.remember(display=TV, transition_succeeded=True, label="Living room TV")

        self.assertEqual(subject.target().profile.display_stable_id, TV.stable_id)
        self.assertEqual(store.loads, 1)


if __name__ == "__main__":
    unittest.main()
