"""Guarded application facade for approved eGPU client release.

This service is deliberately delivery-agnostic. Decky constructs it behind
opaque approval, exact-identity, durable-journal, and acknowledgement gates.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol

from ..domain.process_release import (
    ProcessReleaseApproval,
    ProcessReleasePreview,
    ReleasePhase,
)
from ..domain.transition_journal import JournalEventKind
from ..ports.transition import TransitionObservationPort, VersionedObservation
from ..ports.transition_journal import TransitionJournalPort
from .process_release import (
    GracefulReleaseEvidence,
    GracefulReleaseReceiptStore,
    ProcessReleaseApprovalStore,
)
from .process_release_replay import (
    ProcessReleaseJournalRecovery,
    ProcessReleaseRecoveryResult,
    ProcessReleaseReplayResult,
    ProcessReleaseStatus,
)


class ProcessReleaseRunnerPort(Protocol):
    def preflight(self) -> str: ...

    def run(
        self,
        approval: ProcessReleaseApproval,
        current: VersionedObservation,
    ) -> ProcessReleaseReplayResult: ...


@dataclass(frozen=True, slots=True)
class GuardedProcessReleasePreview:
    phase: ReleasePhase
    details: ProcessReleasePreview | None = None
    blockers: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.details is not None and not self.blockers


@dataclass(frozen=True, slots=True)
class GuardedProcessReleaseExecution:
    accepted: bool
    code: str
    operation_id: str = ""
    result: ProcessReleaseReplayResult | None = None
    force_receipt_token: str = ""
    action_required: bool = False


@dataclass(frozen=True, slots=True)
class GuardedProcessReleaseStatus:
    code: str
    acknowledgement_required: bool = False
    action_required: bool = False
    operation_id: str = ""
    durable: bool = True


class GuardedProcessReleaseService:
    """Join observation, consent, execution, persistence, and recovery gates."""

    def __init__(
        self,
        *,
        observations: TransitionObservationPort,
        approvals: ProcessReleaseApprovalStore,
        receipts: GracefulReleaseReceiptStore,
        runner: ProcessReleaseRunnerPort,
        journal_store: TransitionJournalPort,
        recovery: ProcessReleaseJournalRecovery,
    ) -> None:
        self._observations = observations
        self._approvals = approvals
        self._receipts = receipts
        self._runner = runner
        self._journal_store = journal_store
        self._recovery = recovery
        self._lock = threading.Lock()

    def preview(
        self,
        phase: ReleasePhase,
        *,
        user_confirmed: bool,
        graceful_receipt_token: str = "",
        parent_operation_id: str = "",
    ) -> GuardedProcessReleasePreview:
        runtime_blocker = self._runner.preflight()
        if runtime_blocker:
            return GuardedProcessReleasePreview(phase, blockers=(runtime_blocker,))
        journal_blocker = self._journal_blocker(parent_operation_id)
        if journal_blocker:
            return GuardedProcessReleasePreview(phase, blockers=(journal_blocker,))
        observed = self._observe()
        if observed is None:
            return GuardedProcessReleasePreview(
                phase, blockers=("observation.unavailable",)
            )
        try:
            graceful_evidence = self._resolve_graceful_evidence(
                phase,
                graceful_receipt_token,
                consume=user_confirmed,
            )
            method = self._approvals.issue if user_confirmed else self._approvals.inspect
            details = method(
                observed.snapshot,
                observed_generation=observed.sample_id,
                phase=phase,
                graceful_evidence=graceful_evidence,
                parent_operation_id=parent_operation_id,
            )
        except ValueError as error:
            return GuardedProcessReleasePreview(
                phase, blockers=(self._policy_error_code(error),)
            )
        return GuardedProcessReleasePreview(phase, details)

    def execute(self, approval_token: str) -> GuardedProcessReleaseExecution:
        if not self._lock.acquire(blocking=False):
            return GuardedProcessReleaseExecution(
                False, "process_release.concurrent_request"
            )
        try:
            return self._execute_locked(approval_token)
        finally:
            self._lock.release()

    def _execute_locked(
        self, approval_token: str
    ) -> GuardedProcessReleaseExecution:
        try:
            approval = self._approvals.consume(approval_token)
        except ValueError:
            return GuardedProcessReleaseExecution(
                False, "process_release.approval_invalid"
            )
        observed = self._observe()
        if observed is None:
            return GuardedProcessReleaseExecution(
                False,
                "process_release.observation_unavailable",
                approval.operation_id,
            )
        try:
            result = self._runner.run(approval, observed)
        except (OSError, ValueError):
            return GuardedProcessReleaseExecution(
                True,
                "process_release.execution_interrupted",
                approval.operation_id,
                action_required=True,
            )
        evidence = self._graceful_evidence(approval, result)
        try:
            receipt = self._receipts.issue(evidence) if evidence is not None else ""
        except ValueError:
            return GuardedProcessReleaseExecution(
                True,
                "process_release.receipt_unavailable",
                approval.operation_id,
                result,
                action_required=True,
            )
        code = result.reason_code or f"process_release.{result.status.value}"
        return GuardedProcessReleaseExecution(
            True,
            code,
            approval.operation_id,
            result,
            receipt,
            result.status
            in (ProcessReleaseStatus.ACTION_REQUIRED, ProcessReleaseStatus.BLOCKED),
        )

    def recover_interrupted(self) -> ProcessReleaseRecoveryResult:
        return self._recovery.recover(self._observe())

    def acknowledge(self, operation_id: str) -> bool:
        return self._recovery.acknowledge(operation_id)

    def status(self) -> GuardedProcessReleaseStatus:
        try:
            current = self._journal_store.load_current()
        except Exception:
            return GuardedProcessReleaseStatus(
                "process_release.journal_unavailable",
                action_required=True,
                durable=False,
            )
        if current is None:
            return GuardedProcessReleaseStatus("process_release.idle")
        if not self._recovery.is_process_release_journal(current):
            return GuardedProcessReleaseStatus(
                "process_release.foreign_journal",
                action_required=True,
            )
        if not current.terminal:
            return GuardedProcessReleaseStatus(
                "process_release.recovery_required",
                action_required=True,
                operation_id=current.operation_id,
            )
        terminal = current.entries[-1]
        return GuardedProcessReleaseStatus(
            terminal.code,
            acknowledgement_required=True,
            action_required=terminal.kind
            in (JournalEventKind.BLOCKED, JournalEventKind.FAILED),
            operation_id=current.operation_id,
        )

    def _journal_blocker(self, parent_operation_id: str = "") -> str:
        try:
            current = self._journal_store.load_current()
        except Exception:
            return "journal.unavailable"
        if current is None:
            return "journal.parent_missing" if parent_operation_id else ""
        if parent_operation_id:
            if (
                current.operation_id != parent_operation_id
                or current.terminal
                or not current.entries
                or current.entries[0].code != "sleep.requested"
            ):
                return "journal.parent_mismatch"
            active = next(
                (
                    entry
                    for entry in reversed(current.entries)
                    if entry.kind is JournalEventKind.STEP_STARTED
                ),
                None,
            )
            if (
                active is None
                or dict(active.details).get("step_code") != "releasing_clients"
                or current.entries[-1].kind
                not in {
                    JournalEventKind.STEP_STARTED,
                    JournalEventKind.SUBSTEP_VERIFIED,
                }
            ):
                return "journal.parent_step_invalid"
            return ""
        if not self._recovery.is_process_release_journal(current):
            return "journal.foreign_operation"
        return (
            "journal.acknowledgement_required"
            if current.terminal
            else "journal.recovery_required"
        )

    def _observe(self) -> VersionedObservation | None:
        try:
            return self._observations.observe()
        except Exception:
            return None

    def _resolve_graceful_evidence(
        self,
        phase: ReleasePhase,
        receipt_token: str,
        *,
        consume: bool,
    ) -> GracefulReleaseEvidence | None:
        if phase is ReleasePhase.GRACEFUL:
            if receipt_token:
                raise ValueError("graceful release cannot use a force receipt")
            return None
        if not receipt_token:
            raise ValueError("force approval requires a prior graceful receipt")
        method = self._receipts.consume if consume else self._receipts.inspect
        return method(receipt_token)

    @staticmethod
    def _graceful_evidence(
        approval: ProcessReleaseApproval,
        result: ProcessReleaseReplayResult,
    ) -> GracefulReleaseEvidence | None:
        if approval.phase is not ReleasePhase.GRACEFUL:
            return None
        attempted = tuple(
            approval.targets[item.target_index - 1].instance_id
            for item in result.target_results
            if item.signal_requested and not item.released
        )
        if not attempted:
            return None
        return GracefulReleaseEvidence(
            approval.operation_id,
            attempted,
            approval.observed_generation,
            approval.parent_operation_id,
        )

    @staticmethod
    def _policy_error_code(error: ValueError) -> str:
        message = str(error)
        categories = (
            ("storage", "process_release.storage_in_use"),
            ("scan", "process_release.scan_incomplete"),
            ("identity", "process_release.identity_unknown"),
            ("no close-eligible", "process_release.no_eligible_targets"),
            ("prior graceful", "process_release.graceful_evidence_required"),
            ("prior graceful receipt", "process_release.graceful_evidence_required"),
            ("force receipt", "process_release.phase_evidence_invalid"),
            ("receipt expired", "process_release.graceful_evidence_invalid"),
            ("receipt token", "process_release.graceful_evidence_invalid"),
            ("post-graceful", "process_release.fresh_evidence_required"),
            ("new process target", "process_release.target_set_changed"),
            ("valid only for force", "process_release.phase_evidence_invalid"),
            ("target count", "process_release.target_limit_exceeded"),
        )
        return next(
            (code for text, code in categories if text in message),
            "process_release.preconditions_not_met",
        )
