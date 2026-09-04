from __future__ import annotations

import unittest
from dataclasses import replace

from tests.test_supervised_transition import snapshot
from hdm.application.supervised_transition import SupervisedPresentationTransitionService
from hdm.application.presentation_completion import reconcile_presentation_completion
from hdm.domain.control_plane import PlacementState, WorkflowState
from hdm.domain.models import Confidence, GameState
from hdm.domain.transition_journal import TransitionJournal, JournalEventKind, append_journal_entry
from hdm.ports.transition import VersionedObservation


def committed(target=PlacementState.DOCKED_EGPU, capability="presentation_transition"):
    journal = TransitionJournal("operation-complete", "request-complete")
    for kind, code in (
        (JournalEventKind.REQUESTED, "request.accepted"),
        (JournalEventKind.OBSERVED, "transition.observed"),
        (JournalEventKind.VALIDATED, "transition.validated"),
        (JournalEventKind.PLANNED, "transition.planned"),
        (JournalEventKind.COMMITTED, "transition.committed"),
    ):
        journal = append_journal_entry(
            journal, kind=kind, code=code, occurred_at="2026-09-04T03:00:00Z",
            workflow_state=WorkflowState.IDLE, placement=target,
            details=(("capability", capability), ("target_placement", target.value))
            if kind is JournalEventKind.REQUESTED else (),
        )
    return journal


class Store:
    def __init__(self, active=None, receipt=None):
        self.active, self.receipt = active, receipt
        self.retired = []

    def load_current(self):
        return self.active

    def load_completed(self):
        return self.receipt

    def retire_committed(self, operation_id):
        self.retired.append(operation_id)
        self.receipt, self.active = self.active, None

    def clear_completed(self, operation_id):
        assert self.receipt.operation_id == operation_id
        self.receipt = None


def observation(name="tv-docked.json", **changes):
    return VersionedObservation("fresh-generation", replace(snapshot(name), **changes), "fresh-sample")


class PresentationCompletionTests(unittest.TestCase):
    def test_explicit_success_acknowledgement_preserves_portable_receipt(self):
        store = Store(committed(PlacementState.PORTABLE))
        service = SupervisedPresentationTransitionService(
            observations=None, orchestrator=None, journal_store=store,
            integration_ready=lambda: True,
        )
        self.assertTrue(service.acknowledge("operation-complete"))
        restored = Store(receipt=store.receipt)
        self.assertTrue(reconcile_presentation_completion(
            restored, observation("connected-internal.json")
        ).hold_portable)
        self.assertIsNone(store.active)

    def test_success_archived_only_with_verified_target(self):
        store = Store(committed())
        result = reconcile_presentation_completion(store, observation())
        self.assertTrue(result.finalized)
        self.assertFalse(result.hold_portable)
        self.assertIsNone(store.active)
        self.assertEqual(store.receipt, committed())
        self.assertFalse(reconcile_presentation_completion(store, observation()).finalized)
        self.assertEqual(len(store.retired), 1)

    def test_unknown_game_render_or_wrong_output_cannot_finalize(self):
        tv = observation().snapshot
        for current in (
            observation(game_state=GameState.UNKNOWN),
            observation(game_state=GameState.RUNNING),
            observation(gamescope=replace(tv.gamescope, confidence=Confidence.UNKNOWN)),
            observation("connected-internal.json"),
            VersionedObservation("", tv, ""),
        ):
            with self.subTest(current=current):
                store = Store(committed())
                result = reconcile_presentation_completion(store, current)
                self.assertFalse(result.finalized)
                self.assertIsNotNone(store.active)
                self.assertEqual(store.retired, [])

    def test_foreign_failed_recovered_or_incomplete_never_retired(self):
        base = committed()
        journals = [committed(capability="sleep"), replace(base, entries=base.entries[:-1])]
        for kind in (JournalEventKind.FAILED, JournalEventKind.BLOCKED):
            journals.append(replace(base, entries=(*base.entries[:-1], replace(base.entries[-1], kind=kind))))
        recovery = append_journal_entry(
            replace(base, entries=base.entries[:-1]), kind=JournalEventKind.RECOVERY_STARTED,
            code="recovery.started", occurred_at="now", workflow_state=WorkflowState.IDLE,
            placement=PlacementState.PORTABLE,
        )
        journals.append(append_journal_entry(
            recovery, kind=JournalEventKind.RECOVERY_VERIFIED, code="recovery.verified",
            occurred_at="now", workflow_state=WorkflowState.IDLE, placement=PlacementState.PORTABLE,
        ))
        for journal in journals:
            store = Store(journal)
            self.assertFalse(reconcile_presentation_completion(store, observation()).finalized)
            self.assertEqual(store.active, journal)

    def test_portable_receipt_survives_restart_and_partial_then_clears_on_absence(self):
        store = Store(committed(PlacementState.PORTABLE))
        result = reconcile_presentation_completion(store, observation("connected-internal.json"))
        self.assertTrue(result.finalized)
        self.assertTrue(result.hold_portable)
        restored = Store(receipt=store.receipt)
        self.assertTrue(reconcile_presentation_completion(
            restored, observation("connected-internal.json")
        ).hold_portable)
        self.assertTrue(reconcile_presentation_completion(
            restored, observation("portable.json", gpus=())
        ).hold_portable)
        result = reconcile_presentation_completion(restored, observation("portable.json"))
        self.assertFalse(result.hold_portable)
        self.assertIsNone(restored.receipt)

    def test_storage_failure_preserves_active_and_holds(self):
        store = Store(committed())
        def fail(*args):
            raise OSError("simulated archive failure")
        store.retire_committed = fail
        result = reconcile_presentation_completion(store, observation())
        self.assertFalse(result.finalized)
        self.assertTrue(result.hold_portable)
        self.assertIsNotNone(store.active)


if __name__ == "__main__":
    unittest.main()
