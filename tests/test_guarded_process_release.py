from __future__ import annotations

import dataclasses
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.guarded_process_release import (  # noqa: E402
    GuardedProcessReleaseService,
)
from regear.application.process_release import (  # noqa: E402
    GracefulReleaseReceiptStore,
    ProcessReleaseApprovalStore,
)
from regear.application.process_release_replay import (  # noqa: E402
    ProcessReleaseJournalRecovery,
    ProcessReleaseReplaySimulator,
)
from regear.application.sleep_workflow_journal import (  # noqa: E402
    advance_sleep_journal,
    start_sleep_journal,
)
from regear.domain.control_plane import PlacementState, WorkflowState  # noqa: E402
from regear.domain.game_compatibility import GameSaveCapability  # noqa: E402
from regear.domain.models import (  # noqa: E402
    EgpuClientKind,
    EgpuClientObservation,
    EgpuResourceKind,
)
from regear.domain.process_release import ReleasePhase  # noqa: E402
from regear.domain.serialization import snapshot_from_dict  # noqa: E402
from regear.domain.sleep_workflow import SleepFlow, SleepFlowStage  # noqa: E402
from regear.domain.transition_journal import (  # noqa: E402
    JournalEventKind,
    TransitionJournal,
    append_journal_entry,
)
from regear.ports.process_signal import (  # noqa: E402
    ProcessSignalAction,
    ProcessSignalResult,
)
from regear.ports.transition import VersionedObservation  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures"


def base_snapshot():
    value = json.loads((FIXTURES / "portable.json").read_text(encoding="utf-8"))
    value["disconnect_readiness"] = {
        "applicable": True,
        "scan_complete": True,
        "ready": False,
        "egpu_stable_id": "gpd-g1:ephemeral",
        "clients": [],
        "storage_devices": 0,
        "storage_in_use": False,
        "error": "",
    }
    return snapshot_from_dict(value)


def client():
    return EgpuClientObservation(
        instance_id="instance-1",
        pid=100,
        name="test-client",
        kind=EgpuClientKind.USER,
        resources=(EgpuResourceKind.DRM_RENDER,),
        close_eligible=True,
        reason="test fixture",
        process_start_time="12345",
    )


def with_clients(snapshot, *clients):
    return dataclasses.replace(
        snapshot,
        disconnect_readiness=dataclasses.replace(
            snapshot.disconnect_readiness,
            clients=tuple(clients),
            ready=not clients,
        ),
    )


class Observations:
    def __init__(self, *values):
        self.values = list(values)

    def observe(self):
        return self.values.pop(0) if self.values else None


class Clock:
    value = 0

    def now_ms(self):
        self.value += 10
        return self.value


class Signals:
    def __init__(self, capability=""):
        self.actions = []
        self.capability = capability

    def capability_code(self):
        return self.capability

    def signal(self, target, action):
        self.actions.append((target.instance_id, action))
        return ProcessSignalResult(True, "signal.accepted")


class JournalStore:
    def __init__(self, current=None):
        self.current = current

    def load_current(self):
        return self.current

    def save(self, journal):
        self.current = journal

    def clear_terminal(self, operation_id):
        if self.current is None or self.current.operation_id != operation_id:
            raise ValueError("operation mismatch")
        if not self.current.terminal:
            raise ValueError("journal is incomplete")
        self.current = None


def approvals():
    operation_ids = iter(("process-release-graceful-1", "process-release-force-0001"))
    tokens = iter(("graceful_approval_0001", "force_approval_000001"))
    return ProcessReleaseApprovalStore(
        ttl_seconds=30,
        monotonic=lambda: 10,
        token_factory=tokens.__next__,
        operation_id_factory=operation_ids.__next__,
    )


def service(observations, *, signal_capability=""):
    store = JournalStore()
    signals = Signals(signal_capability)
    recovery = ProcessReleaseJournalRecovery(
        store, occurred_at=lambda: "2026-08-31T12:00:00Z"
    )
    runner = ProcessReleaseReplaySimulator(
        observations,
        signals,
        Clock(),
        journal_store=store,
        occurred_at=lambda: "2026-08-31T12:00:00Z",
    )
    return (
        GuardedProcessReleaseService(
            observations=observations,
            approvals=approvals(),
            receipts=GracefulReleaseReceiptStore(
                ttl_seconds=30,
                monotonic=lambda: 10,
                token_factory=iter(
                    ("force_receipt_000001", "force_receipt_000002")
                ).__next__,
            ),
            runner=runner,
            journal_store=store,
            recovery=recovery,
        ),
        signals,
        store,
    )


class GuardedProcessReleaseTests(unittest.TestCase):
    def test_unavailable_exact_signal_capability_blocks_before_observation(self):
        value, signals, _ = service(
            Observations(), signal_capability="signal.pidfd_unsupported"
        )
        preview = value.preview(ReleasePhase.GRACEFUL, user_confirmed=False)
        self.assertEqual(preview.blockers, ("signal.pidfd_unsupported",))
        self.assertEqual(signals.actions, [])

    def test_foreign_journal_is_reported_without_recovery_or_acknowledgement(self):
        foreign = TransitionJournal("sleep-operation-1", "sleep-request-1")
        foreign = append_journal_entry(
            foreign,
            kind=JournalEventKind.REQUESTED,
            occurred_at="test",
            workflow_state=WorkflowState.SLEEP_PENDING_DISCONNECT,
            placement=PlacementState.DOCKED_EGPU,
            code="sleep.requested",
        )
        value, signals, store = service(Observations())
        store.current = foreign
        self.assertEqual(value.status().code, "process_release.foreign_journal")
        preview = value.preview(ReleasePhase.GRACEFUL, user_confirmed=False)
        self.assertEqual(preview.blockers, ("journal.foreign_operation",))
        self.assertFalse(value.acknowledge("sleep-operation-1"))
        self.assertEqual(store.current, foreign)
        self.assertEqual(signals.actions, [])

    def test_sleep_child_release_uses_parent_journal_substeps(self):
        target = client()
        initial = with_clients(base_snapshot(), target)
        cleared = with_clients(initial)
        observed = Observations(
            VersionedObservation("semantic-1", initial, "sample-1"),
            VersionedObservation("semantic-1", initial, "sample-2"),
            VersionedObservation("semantic-2", cleared, "sample-3"),
        )
        value, signals, store = service(observed)
        before = SleepFlow(
            "sleep-request-0001",
            SleepFlowStage.RELEASING_CLIENTS,
            (),
            True,
            "disconnect.release_clients",
            0,
            900_000,
            save_capability=GameSaveCapability.UNTESTED,
        )
        store.current = start_sleep_journal(
            "sleep-operation-0001",
            before,
            PlacementState.DOCKED_EGPU,
            occurred_at="test",
        )
        approved = value.preview(
            ReleasePhase.GRACEFUL,
            user_confirmed=True,
            parent_operation_id="sleep-operation-0001",
        )
        self.assertTrue(approved.ready)
        result = value.execute(approved.details.token)
        self.assertTrue(result.result.software_blockers_cleared)
        self.assertEqual(store.current.operation_id, "sleep-operation-0001")
        self.assertFalse(store.current.terminal)
        self.assertEqual(
            store.current.entries[-2].kind, JournalEventKind.SUBSTEP_STARTED
        )
        self.assertEqual(
            store.current.entries[-1].kind, JournalEventKind.SUBSTEP_VERIFIED
        )
        self.assertNotIn(
            "process_release.requested",
            tuple(entry.code for entry in store.current.entries),
        )
        after = SleepFlow(
            "sleep-request-0001",
            SleepFlowStage.AWAITING_DISCONNECT,
            (),
            True,
            "disconnect.live_removal_verified",
            0,
            900_000,
            history=(SleepFlowStage.RELEASING_CLIENTS,),
            save_capability=GameSaveCapability.UNTESTED,
        )
        advanced = advance_sleep_journal(
            store.current,
            before,
            after,
            PlacementState.DOCKED_EGPU,
            occurred_at="test",
        )
        self.assertEqual(advanced.entries[-2].kind, JournalEventKind.STEP_VERIFIED)
        self.assertEqual(advanced.entries[-1].kind, JournalEventKind.STEP_STARTED)
        self.assertEqual(
            signals.actions,
            [("instance-1", ProcessSignalAction.GRACEFUL_TERMINATE)],
        )

    def test_sleep_child_force_receipt_stays_in_same_parent_journal(self):
        target = client()
        remaining = with_clients(base_snapshot(), target)
        cleared = with_clients(remaining)
        observed = Observations(
            VersionedObservation("semantic-1", remaining, "sample-1"),
            VersionedObservation("semantic-1", remaining, "sample-2"),
            VersionedObservation("semantic-1", remaining, "sample-3"),
            VersionedObservation("semantic-1", remaining, "sample-4"),
            VersionedObservation("semantic-1", remaining, "sample-5"),
            VersionedObservation("semantic-2", cleared, "sample-6"),
        )
        value, signals, store = service(observed)
        flow = SleepFlow(
            "sleep-request-0001",
            SleepFlowStage.RELEASING_CLIENTS,
            (),
            True,
            "disconnect.release_clients",
            0,
            900_000,
            save_capability=GameSaveCapability.UNTESTED,
        )
        store.current = start_sleep_journal(
            "sleep-operation-0001",
            flow,
            PlacementState.DOCKED_EGPU,
            occurred_at="test",
        )
        graceful = value.preview(
            ReleasePhase.GRACEFUL,
            user_confirmed=True,
            parent_operation_id="sleep-operation-0001",
        )
        graceful_result = value.execute(graceful.details.token)
        self.assertTrue(graceful_result.force_receipt_token)
        self.assertFalse(store.current.terminal)

        force = value.preview(
            ReleasePhase.FORCE,
            user_confirmed=True,
            graceful_receipt_token=graceful_result.force_receipt_token,
            parent_operation_id="sleep-operation-0001",
        )
        force_result = value.execute(force.details.token)
        self.assertTrue(force_result.result.software_blockers_cleared)
        self.assertEqual(store.current.operation_id, "sleep-operation-0001")
        self.assertFalse(store.current.terminal)
        self.assertEqual(
            tuple(
                entry.kind
                for entry in store.current.entries
                if entry.kind
                in {
                    JournalEventKind.SUBSTEP_STARTED,
                    JournalEventKind.SUBSTEP_VERIFIED,
                }
            ),
            (
                JournalEventKind.SUBSTEP_STARTED,
                JournalEventKind.SUBSTEP_VERIFIED,
                JournalEventKind.SUBSTEP_STARTED,
                JournalEventKind.SUBSTEP_VERIFIED,
            ),
        )
        self.assertEqual(
            signals.actions,
            [
                ("instance-1", ProcessSignalAction.GRACEFUL_TERMINATE),
                ("instance-1", ProcessSignalAction.FORCE_TERMINATE),
            ],
        )

    def test_read_only_preview_has_no_token(self):
        initial = with_clients(base_snapshot(), client())
        value, signals, _ = service(
            Observations(VersionedObservation("semantic-1", initial, "sample-1"))
        )
        preview = value.preview(ReleasePhase.GRACEFUL, user_confirmed=False)
        self.assertTrue(preview.ready)
        self.assertEqual(preview.details.token, "")
        self.assertEqual(preview.details.expires_in_seconds, 0)
        self.assertEqual(signals.actions, [])

    def test_explicit_approval_executes_after_fresh_sample(self):
        target = client()
        initial = with_clients(base_snapshot(), target)
        cleared = with_clients(initial)
        observed = Observations(
            VersionedObservation("semantic-1", initial, "sample-1"),
            VersionedObservation("semantic-1", initial, "sample-2"),
            VersionedObservation("semantic-2", cleared, "sample-3"),
        )
        value, signals, store = service(observed)
        preview = value.preview(ReleasePhase.GRACEFUL, user_confirmed=True)
        result = value.execute(preview.details.token)
        self.assertTrue(result.accepted)
        self.assertTrue(result.result.software_blockers_cleared)
        self.assertFalse(result.result.hardware_removal_authorized)
        self.assertEqual(result.force_receipt_token, "")
        self.assertEqual(
            signals.actions,
            [("instance-1", ProcessSignalAction.GRACEFUL_TERMINATE)],
        )
        self.assertTrue(store.current.terminal)
        self.assertEqual(
            value.execute(preview.details.token).code,
            "process_release.approval_invalid",
        )

    def test_force_is_a_separate_approval_limited_by_graceful_evidence(self):
        target = client()
        remaining = with_clients(base_snapshot(), target)
        cleared = with_clients(remaining)
        observed = Observations(
            VersionedObservation("semantic-1", remaining, "sample-1"),
            VersionedObservation("semantic-1", remaining, "sample-2"),
            VersionedObservation("semantic-1", remaining, "sample-3"),
            VersionedObservation("semantic-1", remaining, "sample-4"),
            VersionedObservation("semantic-1", remaining, "sample-5"),
            VersionedObservation("semantic-2", cleared, "sample-6"),
        )
        value, signals, _ = service(observed)
        graceful = value.preview(ReleasePhase.GRACEFUL, user_confirmed=True)
        graceful_result = value.execute(graceful.details.token)
        self.assertFalse(graceful_result.result.software_blockers_cleared)
        self.assertEqual(
            graceful_result.force_receipt_token, "force_receipt_000001"
        )
        self.assertTrue(value.acknowledge(graceful_result.operation_id))

        force = value.preview(
            ReleasePhase.FORCE,
            user_confirmed=True,
            graceful_receipt_token=graceful_result.force_receipt_token,
        )
        self.assertTrue(force.ready)
        force_result = value.execute(force.details.token)
        self.assertTrue(force_result.result.software_blockers_cleared)
        self.assertEqual(force_result.force_receipt_token, "")
        self.assertEqual(
            signals.actions,
            [
                ("instance-1", ProcessSignalAction.GRACEFUL_TERMINATE),
                ("instance-1", ProcessSignalAction.FORCE_TERMINATE),
            ],
        )

    def test_terminal_journal_blocks_new_approval_until_exact_acknowledgement(self):
        target = client()
        remaining = with_clients(base_snapshot(), target)
        observed = Observations(
            VersionedObservation("semantic-1", remaining, "sample-1"),
            VersionedObservation("semantic-1", remaining, "sample-2"),
            VersionedObservation("semantic-1", remaining, "sample-3"),
        )
        value, _, _ = service(observed)
        approved = value.preview(ReleasePhase.GRACEFUL, user_confirmed=True)
        result = value.execute(approved.details.token)
        status = value.status()
        self.assertTrue(status.acknowledgement_required)
        self.assertFalse(status.action_required)
        self.assertEqual(status.operation_id, result.operation_id)
        blocked = value.preview(ReleasePhase.GRACEFUL, user_confirmed=True)
        self.assertEqual(blocked.blockers, ("journal.acknowledgement_required",))
        self.assertFalse(value.acknowledge("process-release-wrong-1"))
        self.assertTrue(value.acknowledge(result.operation_id))


if __name__ == "__main__":
    unittest.main()
