from __future__ import annotations

import json
import sys
import unittest
import threading
from unittest.mock import Mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.application.experimental_transition import (  # noqa: E402
    ExperimentalTransitionApprovalStore,
)
from hdm.application.supervised_transition import (  # noqa: E402
    SupervisedPresentationTransitionService,
)
from hdm.delivery.presentation_transition import status_to_payload  # noqa: E402
from hdm.application.transition_orchestrator import RuntimeTransitionResult  # noqa: E402
from hdm.domain.control_plane import (  # noqa: E402
    PlacementState,
    TransitionOutcome,
    TransitionOutcomeKind,
    WorkflowState,
)
from hdm.domain.serialization import snapshot_from_dict  # noqa: E402
from hdm.domain.transition_journal import (  # noqa: E402
    JournalEventKind,
    TransitionJournal,
    append_journal_entry,
)
from hdm.ports.transition import VersionedObservation  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures"


def snapshot(name="connected-internal.json", *, game_state=None):
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    if game_state is not None:
        value["game_state"] = game_state
    old_ids = {gpu["stable_id"] for gpu in value["gpus"] if gpu["role"] == "external"}
    for gpu in value["gpus"]:
        if gpu["role"] == "external":
            gpu["stable_id"] = "gpd-g1:0123456789abcdef"
    if value["gamescope"].get("render_gpu_stable_id") in old_ids:
        value["gamescope"]["render_gpu_stable_id"] = "gpd-g1:0123456789abcdef"
    return snapshot_from_dict(value)


def docked_igpu_snapshot():
    value = json.loads((FIXTURES / "tv-docked.json").read_text(encoding="utf-8"))
    for gpu in value["gpus"]:
        gpu["selected_for_render"] = gpu["role"] == "internal"
        if gpu["role"] == "external":
            gpu["stable_id"] = "gpd-g1:0123456789abcdef"
    value["gamescope"]["render_gpu_stable_id"] = "internal-gpu"
    value["gamescope"]["render_vendor_device"] = "1002:0000"
    return snapshot_from_dict(value)


class Observations:
    def __init__(self, *values):
        self.values = list(values)

    def observe(self):
        return self.values.pop(0) if self.values else None


class FakeOrchestrator:
    def __init__(self):
        self.plans = []
        self.recoveries = 0

    def run(self, plan):
        self.plans.append(plan)
        return RuntimeTransitionResult(
            None,
            TransitionOutcome(
                TransitionOutcomeKind.SUCCEEDED,
                plan.target_placement,
                WorkflowState.IDLE,
            ),
            True,
        )

    def recover_interrupted(self, **kwargs):
        self.recoveries += 1
        return RuntimeTransitionResult(
            None,
            TransitionOutcome(
                TransitionOutcomeKind.NO_OP,
                PlacementState.UNKNOWN,
                WorkflowState.IDLE,
            ),
            True,
        )


class JournalStore:
    def __init__(self, current=None):
        self.current = current

    def load_current(self):
        return self.current

    def save(self, journal):
        self.current = journal

    def clear_terminal(self, operation_id):
        if self.current and self.current.operation_id == operation_id:
            self.current = None


def approvals():
    return ExperimentalTransitionApprovalStore(
        ttl_seconds=30,
        monotonic=lambda: 10,
        token_factory=lambda: "experimental_token_0001",
    )


def service(observed, *, ready=True, journal=None):
    orchestrator = FakeOrchestrator()
    store = JournalStore(journal)
    value = SupervisedPresentationTransitionService(
        observations=observed,
        orchestrator=orchestrator,
        journal_store=store,
        integration_ready=lambda: ready,
        approvals=approvals(),
        identifier_factory=iter(("operation-0001", "request-0001")).__next__,
    )
    return value, orchestrator, store


class SupervisedTransitionTests(unittest.TestCase):
    def test_preview_requires_ready_integration_and_explicit_approval(self):
        value, _, _ = service(
            Observations(VersionedObservation("generation-1", snapshot())),
            ready=False,
        )
        blocked = value.preview(
            PlacementState.DOCKED_EGPU, user_confirmed=False
        )
        self.assertIn("integration.not_ready", blocked.blockers)

        value, _, _ = service(
            Observations(VersionedObservation("generation-1", snapshot()))
        )
        inspection = value.preview(
            PlacementState.DOCKED_EGPU, user_confirmed=False
        )
        self.assertTrue(inspection.ready)
        self.assertFalse(inspection.approval_token)

    def test_approved_exact_plan_executes_once(self):
        value, orchestrator, _ = service(
            Observations(
                VersionedObservation("generation-1", snapshot()),
                VersionedObservation("generation-1", snapshot()),
            )
        )
        token = value.preview(
            PlacementState.DOCKED_EGPU, user_confirmed=True
        ).approval_token
        result = value.execute(token)
        self.assertTrue(result.accepted)
        self.assertTrue(result.durable)
        self.assertEqual(result.operation_id, "operation-0001")
        self.assertEqual(len(orchestrator.plans), 1)
        self.assertTrue(orchestrator.plans[0].experimental)
        self.assertEqual(
            orchestrator.plans[0].target_placement, PlacementState.DOCKED_EGPU
        )
        self.assertEqual(value.execute(token).code, "transition.approval_invalid")

    def test_automatic_opt_in_uses_same_exact_plan_without_manual_token(self):
        value, orchestrator, _ = service(
            Observations(VersionedObservation("generation-1", snapshot()))
        )

        rejected = value.execute_automatic(
            PlacementState.DOCKED_EGPU,
            expected_generation="generation-1",
            standing_consent=False,
        )
        accepted = value.execute_automatic(
            PlacementState.DOCKED_EGPU,
            expected_generation="generation-1",
            standing_consent=True,
        )

        self.assertEqual(rejected.code, "automatic_dock.not_enabled")
        self.assertTrue(accepted.accepted)
        self.assertEqual(len(orchestrator.plans), 1)
        self.assertEqual(
            orchestrator.plans[0].target_placement, PlacementState.DOCKED_EGPU
        )

    def test_automatic_request_rejects_changed_evidence_and_pending_journal(self):
        value, orchestrator, _ = service(
            Observations(VersionedObservation("generation-new", snapshot()))
        )
        changed = value.execute_automatic(
            PlacementState.DOCKED_EGPU,
            expected_generation="generation-old",
            standing_consent=True,
        )
        self.assertEqual(changed.code, "transition.evidence_changed")
        self.assertEqual(orchestrator.plans, [])

        journal = append_journal_entry(
            TransitionJournal("operation-old", "request-old"),
            kind=JournalEventKind.REQUESTED,
            occurred_at="2026-08-31T12:00:00Z",
            workflow_state=WorkflowState.IDLE,
            placement=PlacementState.PORTABLE,
            code="request.accepted",
            details=(("capability", "presentation_transition"),),
        )
        value, orchestrator, _ = service(
            Observations(VersionedObservation("generation-1", snapshot())),
            journal=journal,
        )
        blocked = value.execute_automatic(
            PlacementState.DOCKED_EGPU,
            expected_generation="generation-1",
            standing_consent=True,
        )
        self.assertEqual(blocked.code, "journal.recovery_required")
        self.assertEqual(orchestrator.plans, [])

    def test_idle_docked_igpu_uses_same_preview_approval_and_execution(self):
        source = docked_igpu_snapshot()
        value, orchestrator, _ = service(
            Observations(
                VersionedObservation("generation-1", source),
                VersionedObservation("generation-1", source),
            )
        )

        preview = value.preview(
            PlacementState.DOCKED_EGPU, user_confirmed=True
        )
        result = value.execute(preview.approval_token)

        self.assertEqual(preview.current, PlacementState.DOCKED_IGPU)
        self.assertTrue(result.accepted)
        self.assertEqual(
            orchestrator.plans[0].from_placement,
            PlacementState.DOCKED_IGPU,
        )

    def test_changed_generation_or_game_blocks_without_orchestrator(self):
        value, orchestrator, _ = service(
            Observations(
                VersionedObservation("generation-1", snapshot()),
                VersionedObservation("generation-2", snapshot()),
            )
        )
        token = value.preview(
            PlacementState.DOCKED_EGPU, user_confirmed=True
        ).approval_token
        self.assertEqual(value.execute(token).code, "transition.evidence_changed")
        self.assertEqual(orchestrator.plans, [])

        value, _, _ = service(
            Observations(
                VersionedObservation(
                    "generation-1", snapshot(game_state="running")
                )
            )
        )
        preview = value.preview(
            PlacementState.DOCKED_EGPU, user_confirmed=True
        )
        self.assertIn("game.running", preview.blockers)

    def test_bound_preview_rejects_changed_private_generation_before_approval(self):
        value, _, _ = service(
            Observations(VersionedObservation("generation-new", snapshot()))
        )
        preview = value.preview(
            PlacementState.DOCKED_EGPU,
            user_confirmed=True,
            expected_generation="generation-ready",
        )

        self.assertEqual(preview.blockers, ("transition.evidence_changed",))
        self.assertFalse(preview.approval_token)

    def test_only_exact_terminal_operation_can_be_acknowledged(self):
        journal = append_journal_entry(
            TransitionJournal("operation-0001", "request-0001"),
            kind=JournalEventKind.REQUESTED,
            occurred_at="2026-08-31T12:00:00Z",
            workflow_state=WorkflowState.IDLE,
            placement=PlacementState.PORTABLE,
            code="request.accepted",
            details=(("capability", "presentation_transition"),),
        )
        journal = append_journal_entry(
            journal,
            kind=JournalEventKind.BLOCKED,
            occurred_at="2026-08-31T12:00:01Z",
            workflow_state=WorkflowState.ACTION_REQUIRED,
            placement=PlacementState.PORTABLE,
            code="transition.blocked",
        )
        value, _, store = service(Observations(), journal=journal)
        self.assertFalse(value.acknowledge("operation-other"))
        self.assertTrue(value.acknowledge("operation-0001"))
        self.assertIsNone(store.current)

    def test_pending_journal_blocks_new_approval(self):
        journal = append_journal_entry(
            TransitionJournal("operation-old", "request-old"),
            kind=JournalEventKind.REQUESTED,
            occurred_at="2026-08-31T12:00:00Z",
            workflow_state=WorkflowState.IDLE,
            placement=PlacementState.PORTABLE,
            code="request.accepted",
            details=(("capability", "presentation_transition"),),
        )
        value, _, _ = service(
            Observations(VersionedObservation("generation-1", snapshot())),
            journal=journal,
        )
        preview = value.preview(
            PlacementState.DOCKED_EGPU, user_confirmed=True
        )
        self.assertIn("journal.recovery_required", preview.blockers)
        self.assertFalse(preview.approval_token)

    def test_status_survives_lost_execute_response_with_recovery_required(self):
        journal = append_journal_entry(
            TransitionJournal("operation-0001", "request-0001"),
            kind=JournalEventKind.REQUESTED,
            occurred_at="2026-08-31T12:00:00Z",
            workflow_state=WorkflowState.IDLE,
            placement=PlacementState.PORTABLE,
            code="request.accepted",
            details=(("capability", "presentation_transition"),),
        )
        journal = append_journal_entry(
            journal,
            kind=JournalEventKind.OBSERVED,
            occurred_at="2026-08-31T12:00:01Z",
            workflow_state=WorkflowState.IDLE,
            placement=PlacementState.PORTABLE,
            code="transition.observed",
        )
        journal = append_journal_entry(
            journal,
            kind=JournalEventKind.VALIDATED,
            occurred_at="2026-08-31T12:00:02Z",
            workflow_state=WorkflowState.IDLE,
            placement=PlacementState.PORTABLE,
            code="transition.validated",
        )
        journal = append_journal_entry(
            journal,
            kind=JournalEventKind.PLANNED,
            occurred_at="2026-08-31T12:00:03Z",
            workflow_state=WorkflowState.IDLE,
            placement=PlacementState.PORTABLE,
            code="transition.planned",
        )
        journal = append_journal_entry(
            journal,
            kind=JournalEventKind.STEP_STARTED,
            occurred_at="2026-08-31T12:00:04Z",
            workflow_state=WorkflowState.CONNECTING,
            placement=PlacementState.PORTABLE,
            code="step.started",
            details=(("step_code", "presentation_apply_docked_egpu"),),
        )
        value, _, _ = service(Observations(), journal=journal)

        status = value.status()
        self.assertEqual(status.code, "transition.recovery_required")
        self.assertTrue(status.action_required)
        self.assertFalse(status.acknowledgement_required)
        self.assertEqual(status.operation_id, "operation-0001")
        self.assertFalse(value.acknowledge(status.operation_id))

    def test_terminal_presentation_status_is_acknowledgeable_and_private(self):
        journal = append_journal_entry(
            TransitionJournal("operation-0001", "request-0001"),
            kind=JournalEventKind.REQUESTED,
            occurred_at="2026-08-31T12:00:00Z",
            workflow_state=WorkflowState.IDLE,
            placement=PlacementState.PORTABLE,
            code="request.accepted",
            details=(("capability", "presentation_transition"),),
        )
        journal = append_journal_entry(
            journal,
            kind=JournalEventKind.OBSERVED,
            occurred_at="2026-08-31T12:00:01Z",
            workflow_state=WorkflowState.IDLE,
            placement=PlacementState.PORTABLE,
            code="transition.observed",
        )
        journal = append_journal_entry(
            journal,
            kind=JournalEventKind.VALIDATED,
            occurred_at="2026-08-31T12:00:02Z",
            workflow_state=WorkflowState.IDLE,
            placement=PlacementState.PORTABLE,
            code="transition.validated",
        )
        journal = append_journal_entry(
            journal,
            kind=JournalEventKind.PLANNED,
            occurred_at="2026-08-31T12:00:03Z",
            workflow_state=WorkflowState.IDLE,
            placement=PlacementState.PORTABLE,
            code="transition.planned",
        )
        journal = append_journal_entry(
            journal,
            kind=JournalEventKind.STEP_STARTED,
            occurred_at="2026-08-31T12:00:04Z",
            workflow_state=WorkflowState.CONNECTING,
            placement=PlacementState.PORTABLE,
            code="step.started",
            details=(("step_code", "presentation_apply_docked_egpu"),),
        )
        journal = append_journal_entry(
            journal,
            kind=JournalEventKind.FAILED,
            occurred_at="2026-08-31T12:00:05Z",
            workflow_state=WorkflowState.ACTION_REQUIRED,
            placement=PlacementState.PORTABLE,
            code="recovery.failed",
        )
        value, _, store = service(Observations(), journal=journal)

        payload = status_to_payload(value.status())
        self.assertEqual(payload["code"], "recovery.failed")
        self.assertTrue(payload["acknowledgement_required"])
        self.assertTrue(payload["action_required"])
        self.assertEqual(payload["acknowledgement_id"], "operation-0001")
        self.assertEqual(payload["target"], "unknown")
        self.assertNotIn("request_id", payload)
        self.assertTrue(value.acknowledge(payload["acknowledgement_id"]))
        self.assertIsNone(store.current)

    def test_status_exposes_only_categorical_persisted_target(self):
        journal = append_journal_entry(
            TransitionJournal("operation-0002", "request-0002"),
            kind=JournalEventKind.REQUESTED,
            occurred_at="2026-08-31T12:00:00Z",
            workflow_state=WorkflowState.IDLE,
            placement=PlacementState.DOCKED_EGPU,
            code="request.accepted",
            details=(
                ("capability", "presentation_transition"),
                ("target_placement", "portable"),
            ),
        )
        journal = append_journal_entry(
            journal,
            kind=JournalEventKind.OBSERVED,
            occurred_at="2026-08-31T12:00:01Z",
            workflow_state=WorkflowState.IDLE,
            placement=PlacementState.DOCKED_EGPU,
            code="snapshot.observed",
        )
        journal = append_journal_entry(
            journal,
            kind=JournalEventKind.VALIDATED,
            occurred_at="2026-08-31T12:00:02Z",
            workflow_state=WorkflowState.RETURNING_TO_PORTABLE,
            placement=PlacementState.DOCKED_EGPU,
            code="plan.validated",
        )
        journal = append_journal_entry(
            journal,
            kind=JournalEventKind.PLANNED,
            occurred_at="2026-08-31T12:00:03Z",
            workflow_state=WorkflowState.RETURNING_TO_PORTABLE,
            placement=PlacementState.DOCKED_EGPU,
            code="plan.ready",
        )
        journal = append_journal_entry(
            journal,
            kind=JournalEventKind.COMMITTED,
            occurred_at="2026-08-31T12:00:04Z",
            workflow_state=WorkflowState.IDLE,
            placement=PlacementState.PORTABLE,
            code="transition.committed",
        )
        value, _, _ = service(Observations(), journal=journal)

        payload = status_to_payload(value.status())

        self.assertEqual(payload["target"], "portable")
        self.assertNotIn("request_id", payload)

    def test_status_refuses_foreign_terminal_journal(self):
        journal = append_journal_entry(
            TransitionJournal("sleep-operation-1", "sleep-request-1"),
            kind=JournalEventKind.REQUESTED,
            occurred_at="2026-08-31T12:00:00Z",
            workflow_state=WorkflowState.IDLE,
            placement=PlacementState.PORTABLE,
            code="sleep.requested",
        )
        journal = append_journal_entry(
            journal,
            kind=JournalEventKind.BLOCKED,
            occurred_at="2026-08-31T12:00:01Z",
            workflow_state=WorkflowState.ACTION_REQUIRED,
            placement=PlacementState.PORTABLE,
            code="sleep.blocked",
        )
        value, _, store = service(
            Observations(VersionedObservation("generation-1", snapshot())),
            journal=journal,
        )

        status = value.status()
        self.assertEqual(status.code, "transition.foreign_journal")
        self.assertTrue(status.action_required)
        self.assertFalse(status.acknowledgement_required)
        self.assertFalse(value.acknowledge("sleep-operation-1"))
        self.assertIs(store.current, journal)

        automatic = value.execute_automatic(
            PlacementState.DOCKED_EGPU,
            expected_generation="generation-1",
            standing_consent=True,
        )
        self.assertEqual(automatic.code, "journal.foreign_workflow")
        self.assertIs(store.current, journal)

    def test_interrupted_recovery_delegates_to_orchestrator(self):
        value, orchestrator, _ = service(Observations())
        result = value.recover_interrupted()
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.NO_OP)
        self.assertEqual(orchestrator.recoveries, 1)





class RecoverySerializationTests(unittest.TestCase):
    def test_recovery_excludes_execution_and_completion_until_return(self):
        value, orchestrator, store = service(Observations())
        entered, release = threading.Event(), threading.Event()
        original = orchestrator.recover_interrupted
        def recover():
            entered.set()
            if not release.wait(2):
                raise TimeoutError('test recovery release missing')
            return original()
        orchestrator.recover_interrupted = recover
        results = []
        thread = threading.Thread(target=lambda: results.append(value.recover_interrupted()))
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            self.assertEqual(value.execute('unused-token').code, 'transition.concurrent_request')
            self.assertEqual(value.execute_automatic(PlacementState.DOCKED_EGPU,
                expected_generation='generation', standing_consent=True).code,
                'transition.concurrent_request')
            self.assertFalse(value.acknowledge('operation-0001'))
            self.assertEqual(value.reconcile_completion(None).code, 'completion.transition_busy')
            concurrent = value.recover_interrupted()
            self.assertEqual(concurrent.outcome.failure.code, 'transition.concurrent_request')
            self.assertFalse(concurrent.durable)
        finally:
            release.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(results), 1)
        self.assertEqual(orchestrator.recoveries, 1)

    def test_recovery_cannot_enter_during_execute(self):
        value, orchestrator, _ = service(Observations())
        calls = []
        def execute(token):
            result = value.recover_interrupted()
            calls.append(result.outcome.failure.code)
            return 'executed'
        value._execute_locked = execute
        self.assertEqual(value.execute('token'), 'executed')
        self.assertEqual(calls, ['transition.concurrent_request'])
        self.assertEqual(orchestrator.recoveries, 0)

    def test_recovery_exception_releases_outer_lock(self):
        value, orchestrator, _ = service(Observations())
        original = orchestrator.recover_interrupted
        orchestrator.recover_interrupted = Mock(side_effect=OSError('fixture'))
        with self.assertRaises(OSError):
            value.recover_interrupted()
        orchestrator.recover_interrupted = original
        self.assertEqual(value.recover_interrupted().outcome.kind, TransitionOutcomeKind.NO_OP)


if __name__ == "__main__":
    unittest.main()
