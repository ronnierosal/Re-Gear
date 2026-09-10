from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.shared_transition_journal import (  # noqa: E402
    SharedTransitionJournalService,
    TransitionJournalOwner,
)
from regear.domain.control_plane import PlacementState, WorkflowState  # noqa: E402
from regear.domain.transition_journal import (  # noqa: E402
    JournalEventKind,
    TransitionJournal,
    append_journal_entry,
)


class Store:
    def __init__(self, current=None):
        self.current = current

    def load_current(self):
        return self.current

    def save(self, journal):
        self.current = journal

    def clear_terminal(self, operation_id):
        if self.current is None or self.current.operation_id != operation_id:
            raise ValueError("wrong operation")
        if not self.current.terminal:
            raise ValueError("not terminal")
        self.current = None


def journal(first_code: str, *, details=(), terminal=True):
    value = append_journal_entry(
        TransitionJournal("operation-1", "request-1"),
        kind=JournalEventKind.REQUESTED,
        occurred_at="2026-09-02T12:00:00Z",
        workflow_state=WorkflowState.IDLE,
        placement=PlacementState.PORTABLE,
        code=first_code,
        details=details,
    )
    if terminal:
        value = append_journal_entry(
            value,
            kind=JournalEventKind.BLOCKED,
            occurred_at="2026-09-02T12:00:01Z",
            workflow_state=WorkflowState.ACTION_REQUIRED,
            placement=PlacementState.PORTABLE,
            code="workflow.blocked",
        )
    return value


class SharedTransitionJournalTests(unittest.TestCase):
    def test_identifies_each_known_owner_without_exposing_request_identity(self):
        examples = (
            ("sleep.requested", (), TransitionJournalOwner.SLEEP),
            ("process_release.requested", (), TransitionJournalOwner.PROCESS_RELEASE),
            (
                "request.accepted",
                (("capability", "presentation_transition"),),
                TransitionJournalOwner.PRESENTATION,
            ),
            ("request.accepted", (), TransitionJournalOwner.PRESENTATION),
        )
        for first_code, details, owner in examples:
            with self.subTest(owner=owner):
                status = SharedTransitionJournalService(
                    Store(journal(first_code, details=details))
                ).status()
                self.assertEqual(status.owner, owner)
                self.assertTrue(status.acknowledgement_required)
                self.assertEqual(status.operation_id, "operation-1")

    def test_unknown_or_incomplete_journal_never_offers_acknowledgement(self):
        unknown = SharedTransitionJournalService(
            Store(journal("other.requested"))
        ).status()
        incomplete = SharedTransitionJournalService(
            Store(journal("sleep.requested", terminal=False))
        ).status()

        self.assertEqual(unknown.code, "journal.unknown_owner")
        self.assertFalse(unknown.acknowledgement_required)
        self.assertEqual(unknown.operation_id, "")
        self.assertEqual(incomplete.code, "journal.recovery_required")
        self.assertFalse(incomplete.acknowledgement_required)
        self.assertEqual(incomplete.operation_id, "")

    def test_only_exact_terminal_sleep_journal_can_be_acknowledged(self):
        sleep_store = Store(journal("sleep.requested"))
        sleep = SharedTransitionJournalService(sleep_store)
        process_store = Store(journal("process_release.requested"))
        process = SharedTransitionJournalService(process_store)

        self.assertFalse(sleep.acknowledge_sleep("wrong-operation"))
        self.assertFalse(process.acknowledge_sleep("operation-1"))
        self.assertIsNotNone(process_store.current)
        self.assertTrue(sleep.acknowledge_sleep("operation-1"))
        self.assertIsNone(sleep_store.current)


if __name__ == "__main__":
    unittest.main()
