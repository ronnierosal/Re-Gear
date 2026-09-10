from __future__ import annotations

import dataclasses
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.process_release import (  # noqa: E402
    GracefulReleaseEvidence,
    ProcessReleaseApprovalStore,
)
from regear.application.process_release_replay import (  # noqa: E402
    ProcessReleaseJournalRecovery,
    ProcessReleaseReplaySimulator,
    ProcessReleaseStatus,
    process_audit_to_dict,
)
from regear.domain.models import (  # noqa: E402
    EgpuClientKind,
    EgpuClientObservation,
    EgpuResourceKind,
)
from regear.domain.control_plane import PlacementState, WorkflowState  # noqa: E402
from regear.domain.serialization import snapshot_from_dict  # noqa: E402
from regear.domain.process_release import ReleasePhase  # noqa: E402
from regear.ports.process_signal import (  # noqa: E402
    ProcessSignalAction,
    ProcessSignalResult,
)
from regear.ports.transition import VersionedObservation  # noqa: E402
from regear.domain.transition_journal import (  # noqa: E402
    JournalEventKind,
    TransitionJournal,
    append_journal_entry,
)


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


def client(instance_id: str, pid: int) -> EgpuClientObservation:
    return EgpuClientObservation(
        instance_id=instance_id,
        pid=pid,
        name="test-client",
        kind=EgpuClientKind.USER,
        resources=(EgpuResourceKind.DRM_RENDER,),
        close_eligible=True,
        reason="test fixture",
        process_start_time=str(pid * 100),
    )


def with_clients(snapshot, *clients, complete=True):
    readiness = dataclasses.replace(
        snapshot.disconnect_readiness,
        clients=tuple(clients),
        scan_complete=complete,
        ready=complete and not clients,
    )
    return dataclasses.replace(snapshot, disconnect_readiness=readiness)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0

    def now_ms(self) -> int:
        return self.value

    def advance(self, milliseconds: int) -> None:
        self.value += milliseconds


class Observations:
    def __init__(self, *values):
        self.values = list(values)

    def observe(self):
        return self.values.pop(0) if self.values else None


class Signals:
    def __init__(self, clock, *results):
        self.clock = clock
        self.results = list(results)
        self.calls = []

    def capability_code(self):
        return ""

    def signal(self, target, action):
        self.calls.append((target, action))
        duration, result = self.results.pop(0)
        self.clock.advance(duration)
        return result


class MemoryJournalStore:
    def __init__(self, current=None, fail_kind=None):
        self.current = current
        self.fail_kind = fail_kind
        self.saved = []

    def load_current(self):
        return self.current

    def save(self, journal):
        if journal.entries[-1].kind is self.fail_kind:
            raise OSError("injected journal persistence failure")
        self.current = journal
        self.saved.append(journal)

    def clear_terminal(self, operation_id):
        if self.current and self.current.operation_id == operation_id:
            self.current = None


def approval(snapshot, phase=ReleasePhase.GRACEFUL):
    tokens = iter(["approval_token_123456"])
    store = ProcessReleaseApprovalStore(
        token_factory=lambda: next(tokens),
        operation_id_factory=lambda: "process-release-operation-1",
        monotonic=lambda: 0.0,
    )
    kwargs = {}
    generation = "generation-1"
    if phase is ReleasePhase.FORCE:
        kwargs["graceful_evidence"] = GracefulReleaseEvidence(
            "graceful_operation_1",
            tuple(client.instance_id for client in snapshot.disconnect_readiness.clients),
            "generation-0",
        )
    preview = store.issue(
        snapshot,
        observed_generation=generation,
        phase=phase,
        **kwargs,
    )
    return store.consume(preview.token)


class ProcessReleaseReplayTests(unittest.TestCase):
    def test_durable_runner_persists_step_started_before_signal(self):
        target = client("instance-1", 100)
        initial = with_clients(base_snapshot(), target)
        after = with_clients(initial)
        store = MemoryJournalStore()
        clock = FakeClock()

        class InspectingSignals(Signals):
            def signal(self, target, action):
                self_test.assertEqual(
                    store.current.entries[-1].kind, JournalEventKind.STEP_STARTED
                )
                return super().signal(target, action)

        self_test = self
        signals = InspectingSignals(
            clock, (10, ProcessSignalResult(True, "signal.accepted"))
        )
        result = ProcessReleaseReplaySimulator(
            Observations(VersionedObservation("generation-3", after)),
            signals,
            clock,
            journal_store=store,
            occurred_at=lambda: "2026-08-31T12:00:00Z",
        ).run(approval(initial), VersionedObservation("generation-2", initial))
        self.assertEqual(result.status, ProcessReleaseStatus.COMPLETED)
        self.assertTrue(store.current.terminal)
        self.assertEqual(store.current.entries[-1].kind, JournalEventKind.COMMITTED)

    def test_journal_failure_before_signal_prevents_signal(self):
        target = client("instance-1", 100)
        initial = with_clients(base_snapshot(), target)
        store = MemoryJournalStore(fail_kind=JournalEventKind.STEP_STARTED)
        clock = FakeClock()
        signals = Signals(clock, (10, ProcessSignalResult(True, "signal.accepted")))
        with self.assertRaisesRegex(OSError, "persistence"):
            ProcessReleaseReplaySimulator(
                Observations(), signals, clock, journal_store=store
            ).run(
                approval(initial), VersionedObservation("generation-2", initial)
            )
        self.assertEqual(signals.calls, [])
        self.assertEqual(store.current.entries[-1].kind, JournalEventKind.PLANNED)

    def test_restart_terminalizes_without_repeating_signal(self):
        journal = TransitionJournal("process-release-operation-1", "request-1")
        for kind, code in (
            (JournalEventKind.REQUESTED, "process_release.requested"),
            (JournalEventKind.OBSERVED, "process_release.observed"),
            (JournalEventKind.VALIDATED, "process_release.validated"),
            (JournalEventKind.PLANNED, "process_release.planned"),
            (JournalEventKind.STEP_STARTED, "process_release.step_started"),
        ):
            journal = append_journal_entry(
                journal,
                kind=kind,
                occurred_at="2026-08-31T12:00:00Z",
                workflow_state=WorkflowState.PREPARING_TO_DISCONNECT,
                placement=PlacementState.PORTABLE,
                code=code,
            )
        store = MemoryJournalStore(journal)
        recovery = ProcessReleaseJournalRecovery(
            store, occurred_at=lambda: "2026-08-31T12:01:00Z"
        )
        result = recovery.recover(
            VersionedObservation("generation-current", base_snapshot())
        )
        self.assertTrue(result.action_required)
        self.assertTrue(result.durable)
        self.assertEqual(result.journal.entries[-1].kind, JournalEventKind.FAILED)
        self.assertTrue(recovery.acknowledge("process-release-operation-1"))
        self.assertIsNone(store.current)

    def test_restart_reports_committed_journal_without_false_action_required(self):
        target = client("instance-1", 100)
        initial = with_clients(base_snapshot(), target)
        cleared = with_clients(initial)
        store = MemoryJournalStore()
        clock = FakeClock()
        ProcessReleaseReplaySimulator(
            Observations(VersionedObservation("generation-3", cleared)),
            Signals(clock, (10, ProcessSignalResult(True, "signal.accepted"))),
            clock,
            journal_store=store,
            occurred_at=lambda: "2026-08-31T12:00:00Z",
        ).run(approval(initial), VersionedObservation("generation-2", initial))
        recovery = ProcessReleaseJournalRecovery(
            store, occurred_at=lambda: "2026-08-31T12:01:00Z"
        )
        result = recovery.recover(None)
        self.assertFalse(result.action_required)
        self.assertEqual(result.code, "process_release.committed")
        self.assertTrue(result.durable)

    def test_acknowledgement_rejects_malformed_operation_id(self):
        recovery = ProcessReleaseJournalRecovery(
            MemoryJournalStore(), occurred_at=lambda: "2026-08-31T12:01:00Z"
        )
        self.assertFalse(recovery.acknowledge("../active-transition.json"))

    def test_recovery_never_mutates_or_acknowledges_a_foreign_journal(self):
        foreign = TransitionJournal("sleep-operation-1", "sleep-request-1")
        foreign = append_journal_entry(
            foreign,
            kind=JournalEventKind.REQUESTED,
            occurred_at="2026-08-31T12:00:00Z",
            workflow_state=WorkflowState.SLEEP_PENDING_DISCONNECT,
            placement=PlacementState.DOCKED_EGPU,
            code="sleep.requested",
        )
        store = MemoryJournalStore(foreign)
        recovery = ProcessReleaseJournalRecovery(
            store, occurred_at=lambda: "2026-08-31T12:01:00Z"
        )
        result = recovery.recover(None)
        self.assertTrue(result.action_required)
        self.assertEqual(result.code, "process_release.foreign_journal")
        self.assertEqual(store.current, foreign)
        self.assertFalse(recovery.acknowledge("sleep-operation-1"))
        self.assertEqual(store.current, foreign)

    def test_rescans_after_every_fake_signal_and_clears_software_blockers(self):
        first = client("instance-1", 100)
        second = client("instance-2", 200)
        initial = with_clients(base_snapshot(), first, second)
        after_first = with_clients(initial, second)
        after_second = with_clients(initial)
        clock = FakeClock()
        signals = Signals(
            clock,
            (10, ProcessSignalResult(True, "signal.accepted")),
            (10, ProcessSignalResult(True, "signal.accepted")),
        )
        result = ProcessReleaseReplaySimulator(
            Observations(
                VersionedObservation("generation-3", after_first),
                VersionedObservation("generation-4", after_second),
            ),
            signals,
            clock,
        ).run(
            approval(initial),
            VersionedObservation("generation-2", initial),
        )
        self.assertEqual(result.status, ProcessReleaseStatus.COMPLETED)
        self.assertTrue(result.software_blockers_cleared)
        self.assertFalse(result.hardware_removal_authorized)
        self.assertEqual(len(signals.calls), 2)
        self.assertTrue(all(item.released for item in result.target_results))
        self.assertEqual(result.journal.entries[-1].kind, JournalEventKind.COMMITTED)
        self.assertTrue(result.journal.terminal)

    def test_remaining_process_is_reported_without_force_escalation(self):
        target = client("instance-1", 100)
        initial = with_clients(base_snapshot(), target)
        clock = FakeClock()
        signals = Signals(clock, (10, ProcessSignalResult(True, "signal.accepted")))
        result = ProcessReleaseReplaySimulator(
            Observations(VersionedObservation("generation-3", initial)),
            signals,
            clock,
        ).run(approval(initial), VersionedObservation("generation-2", initial))
        self.assertEqual(result.status, ProcessReleaseStatus.COMPLETED)
        self.assertFalse(result.software_blockers_cleared)
        self.assertEqual(result.reason_code, "software_blockers_remain")
        self.assertEqual(signals.calls[0][1], ProcessSignalAction.GRACEFUL_TERMINATE)

    def test_changed_client_set_stops_before_next_signal(self):
        first = client("instance-1", 100)
        second = client("instance-2", 200)
        unexpected = client("unexpected-3", 300)
        initial = with_clients(base_snapshot(), first, second)
        changed = with_clients(initial, second, unexpected)
        clock = FakeClock()
        signals = Signals(clock, (10, ProcessSignalResult(True, "signal.accepted")))
        result = ProcessReleaseReplaySimulator(
            Observations(VersionedObservation("generation-3", changed)),
            signals,
            clock,
        ).run(approval(initial), VersionedObservation("generation-2", initial))
        self.assertEqual(result.status, ProcessReleaseStatus.ACTION_REQUIRED)
        self.assertEqual(len(signals.calls), 1)
        self.assertEqual(result.reason_code, "rescan.invalid")

    def test_stale_or_incomplete_post_signal_scan_requires_action(self):
        target = client("instance-1", 100)
        initial = with_clients(base_snapshot(), target)
        cases = (
            VersionedObservation("generation-2", with_clients(initial)),
            VersionedObservation(
                "generation-3", with_clients(initial, complete=False)
            ),
        )
        for observed in cases:
            with self.subTest(generation=observed.generation):
                clock = FakeClock()
                signals = Signals(
                    clock, (10, ProcessSignalResult(True, "signal.accepted"))
                )
                result = ProcessReleaseReplaySimulator(
                    Observations(observed), signals, clock
                ).run(
                    approval(initial),
                    VersionedObservation("generation-2", initial),
                )
                self.assertEqual(result.status, ProcessReleaseStatus.ACTION_REQUIRED)
                self.assertEqual(result.reason_code, "rescan.invalid")

    def test_missing_rescan_and_deadline_expiry_require_action(self):
        target = client("instance-1", 100)
        initial = with_clients(base_snapshot(), target)
        for observations, duration, reason in (
            (Observations(None), 10, "rescan.unavailable"),
            (
                Observations(
                    VersionedObservation(
                        "generation-3", with_clients(initial)
                    )
                ),
                201,
                "signal.deadline_exceeded",
            ),
        ):
            with self.subTest(reason=reason):
                clock = FakeClock()
                signals = Signals(
                    clock, (duration, ProcessSignalResult(True, "signal.accepted"))
                )
                result = ProcessReleaseReplaySimulator(
                    observations, signals, clock, per_signal_deadline_ms=200
                ).run(
                    approval(initial),
                    VersionedObservation("generation-2", initial),
                )
                self.assertEqual(result.status, ProcessReleaseStatus.ACTION_REQUIRED)
                self.assertEqual(result.reason_code, reason)
                self.assertEqual(
                    result.journal.entries[-1].kind, JournalEventKind.FAILED
                )

    def test_force_approval_uses_force_action_and_audit_has_no_identity(self):
        target = client("private-instance-token", 4242)
        initial = with_clients(base_snapshot(), target)
        clock = FakeClock()
        signals = Signals(clock, (10, ProcessSignalResult(True, "signal.accepted")))
        result = ProcessReleaseReplaySimulator(
            Observations(
                VersionedObservation("generation-3", with_clients(initial))
            ),
            signals,
            clock,
        ).run(
            approval(initial, ReleasePhase.FORCE),
            VersionedObservation("generation-2", initial),
        )
        self.assertEqual(signals.calls[0][1], ProcessSignalAction.FORCE_TERMINATE)
        exported = json.dumps(process_audit_to_dict(result.audit), sort_keys=True)
        self.assertNotIn("4242", exported)
        self.assertNotIn("private-instance-token", exported)
        self.assertNotIn("test-client", exported)
        self.assertNotIn("pid", exported.casefold())


if __name__ == "__main__":
    unittest.main()
