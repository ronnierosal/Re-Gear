"""Deterministic fake-signal and mandatory re-scan process-release runner."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
import re

from .process_release import (
    TOKEN_RE,
    revalidate_process_release,
    revalidate_process_release_rescan,
    revalidate_process_release_target,
)
from ..domain.models import EgpuResourceKind
from ..domain.inference import infer_placement
from ..domain.process_release import (
    ProcessReleaseApproval,
    ReleasePhase,
)
from ..domain.control_plane import WorkflowState
from ..domain.transition_journal import (
    JournalEventKind,
    TransitionJournal,
    append_journal_entry,
)
from ..ports.process_signal import (
    ProcessSignalAction,
    ProcessSignalPort,
)
from ..ports.transition import (
    MonotonicClockPort,
    TransitionObservationPort,
    VersionedObservation,
)
from ..ports.transition_journal import TransitionJournalPort


MAX_PROCESS_AUDIT_EVENTS = 96


class ProcessReleaseStatus(StrEnum):
    COMPLETED = "completed"
    BLOCKED = "blocked"
    ACTION_REQUIRED = "action_required"


@dataclass(frozen=True, slots=True)
class ProcessReleaseAuditEvent:
    sequence: int
    phase: ReleasePhase
    code: str
    target_index: int | None = None
    resources: tuple[EgpuResourceKind, ...] = field(default_factory=tuple)
    outcome: str = ""

    def __post_init__(self) -> None:
        if self.sequence <= 0:
            raise ValueError("process audit sequence must be positive")
        if not re.fullmatch(r"[a-z0-9_.-]{1,64}", self.code):
            raise ValueError("process audit code must be categorical")
        if self.target_index is not None and self.target_index <= 0:
            raise ValueError("process audit target index must be positive")
        if self.outcome and not re.fullmatch(r"[a-z0-9_.-]{1,64}", self.outcome):
            raise ValueError("process audit outcome must be categorical")


@dataclass(frozen=True, slots=True)
class ProcessTargetResult:
    target_index: int
    signal_requested: bool
    released: bool
    code: str


@dataclass(frozen=True, slots=True)
class ProcessReleaseReplayResult:
    status: ProcessReleaseStatus
    software_blockers_cleared: bool
    hardware_removal_authorized: bool
    target_results: tuple[ProcessTargetResult, ...]
    remaining_client_count: int | None
    audit: tuple[ProcessReleaseAuditEvent, ...]
    journal: TransitionJournal
    reason_code: str = ""


def process_audit_to_dict(
    events: tuple[ProcessReleaseAuditEvent, ...]
) -> list[dict[str, object]]:
    return [
        {
            "sequence": event.sequence,
            "phase": event.phase.value,
            "code": event.code,
            "target_index": event.target_index,
            "resources": [resource.value for resource in event.resources],
            "outcome": event.outcome,
        }
        for event in events
    ]


class ProcessReleaseRunner:
    def __init__(
        self,
        observations: TransitionObservationPort,
        signals: ProcessSignalPort,
        clock: MonotonicClockPort,
        *,
        per_signal_deadline_ms: int = 2_000,
        journal_store: TransitionJournalPort | None = None,
        occurred_at: Callable[[], str] = lambda: "replay",
    ) -> None:
        if per_signal_deadline_ms <= 0 or per_signal_deadline_ms > 10_000:
            raise ValueError("process signal deadline must be between 1 and 10000 ms")
        self._observations = observations
        self._signals = signals
        self._clock = clock
        self._deadline_ms = per_signal_deadline_ms
        self._journal_store = journal_store
        self._occurred_at = occurred_at

    def preflight(self) -> str:
        return self._signals.capability_code()

    def run(
        self,
        approval: ProcessReleaseApproval,
        current: VersionedObservation,
    ) -> ProcessReleaseReplayResult:
        child_mode = bool(approval.parent_operation_id)
        current_journal = (
            self._journal_store.load_current()
            if self._journal_store is not None
            else None
        )
        if child_mode:
            if self._journal_store is None or current_journal is None:
                raise ValueError("process release parent journal is unavailable")
            self._validate_child_parent(current_journal, approval.parent_operation_id)
        elif current_journal is not None:
            raise ValueError("another process release journal requires attention")
        audit: list[ProcessReleaseAuditEvent] = []
        results: list[ProcessTargetResult] = []
        placement = infer_placement(current.snapshot)
        journal = (
            current_journal
            if child_mode and current_journal is not None
            else TransitionJournal(approval.operation_id, approval.operation_id)
        )

        def journal_event(
            kind: JournalEventKind,
            code: str,
            *,
            child_step_code: str = "",
        ) -> None:
            nonlocal journal, placement
            if child_mode:
                if kind in {
                    JournalEventKind.REQUESTED,
                    JournalEventKind.OBSERVED,
                    JournalEventKind.VALIDATED,
                    JournalEventKind.PLANNED,
                    JournalEventKind.COMMITTED,
                }:
                    return
                if kind is JournalEventKind.STEP_STARTED:
                    kind = JournalEventKind.SUBSTEP_STARTED
                    code = "process_release.substep_started"
                elif kind is JournalEventKind.STEP_VERIFIED:
                    kind = JournalEventKind.SUBSTEP_VERIFIED
                    code = "process_release.substep_verified"
                if kind in {
                    JournalEventKind.SUBSTEP_STARTED,
                    JournalEventKind.SUBSTEP_VERIFIED,
                } and not child_step_code:
                    raise ValueError("process release child step identity is required")
            journal = append_journal_entry(
                journal,
                kind=kind,
                occurred_at=self._occurred_at(),
                workflow_state=(
                    WorkflowState.ACTION_REQUIRED
                    if kind in (JournalEventKind.BLOCKED, JournalEventKind.FAILED)
                    else (
                        WorkflowState.SLEEP_PENDING_DISCONNECT
                        if child_mode
                        else WorkflowState.PREPARING_TO_DISCONNECT
                    )
                ),
                placement=placement,
                code=code,
                details=(
                    (("step_code", child_step_code),)
                    if child_mode
                    and kind
                    in {
                        JournalEventKind.SUBSTEP_STARTED,
                        JournalEventKind.SUBSTEP_VERIFIED,
                    }
                    else ()
                ),
            )
            if self._journal_store is not None:
                self._journal_store.save(journal)

        def record(
            code: str,
            *,
            target_index: int | None = None,
            resources: tuple[EgpuResourceKind, ...] = (),
            outcome: str = "",
        ) -> None:
            if len(audit) >= MAX_PROCESS_AUDIT_EVENTS:
                raise ValueError("process release audit exceeded its bound")
            audit.append(
                ProcessReleaseAuditEvent(
                    len(audit) + 1,
                    approval.phase,
                    code,
                    target_index,
                    resources,
                    outcome,
                )
            )

        journal_event(JournalEventKind.REQUESTED, "process_release.requested")
        journal_event(JournalEventKind.OBSERVED, "process_release.observed")
        try:
            revalidate_process_release(
                approval,
                current.snapshot,
                observed_generation=current.sample_id,
            )
        except ValueError:
            record("approval.revalidation_failed", outcome="blocked")
            journal_event(JournalEventKind.BLOCKED, "process_release.blocked")
            return self._result(
                ProcessReleaseStatus.BLOCKED,
                False,
                results,
                current,
                audit,
                journal,
                "approval.revalidation_failed",
            )
        record("approval.revalidated", outcome="verified")
        journal_event(JournalEventKind.VALIDATED, "process_release.validated")
        journal_event(JournalEventKind.PLANNED, "process_release.planned")
        previous_generation = approval.observed_generation

        for index, target in enumerate(approval.targets, start=1):
            child_step_code = (
                f"process_release.{approval.phase.value}.{index}"
                if child_mode
                else ""
            )
            try:
                live_target = revalidate_process_release_target(
                    approval,
                    current.snapshot,
                    observed_generation=current.sample_id,
                    previous_generation=previous_generation,
                    target=target,
                )
            except ValueError:
                record(
                    "target.revalidation_failed",
                    target_index=index,
                    resources=target.resources,
                    outcome="blocked",
                )
                journal_event(JournalEventKind.FAILED, "process_release.revalidation_failed")
                return self._result(
                    ProcessReleaseStatus.BLOCKED,
                    False,
                    results,
                    current,
                    audit,
                    journal,
                    "target.revalidation_failed",
                )
            if live_target is None:
                journal_event(
                    JournalEventKind.STEP_STARTED,
                    "process_release.step_started",
                    child_step_code=child_step_code,
                )
                journal_event(
                    JournalEventKind.STEP_VERIFIED,
                    "process_release.step_no_op",
                    child_step_code=child_step_code,
                )
                results.append(
                    ProcessTargetResult(index, False, True, "target.already_released")
                )
                record(
                    "target.already_released",
                    target_index=index,
                    resources=target.resources,
                    outcome="no_op",
                )
                continue

            action = (
                ProcessSignalAction.GRACEFUL_TERMINATE
                if approval.phase is ReleasePhase.GRACEFUL
                else ProcessSignalAction.FORCE_TERMINATE
            )
            record(
                "target.signal_requested",
                target_index=index,
                resources=target.resources,
                outcome=action.value,
            )
            journal_event(
                JournalEventKind.STEP_STARTED,
                "process_release.step_started",
                child_step_code=child_step_code,
            )
            started = self._clock.now_ms()
            signal_result = self._signals.signal(live_target, action)
            elapsed = self._clock.now_ms() - started
            signal_generation = current.sample_id
            rescanned = self._observations.observe()
            if rescanned is None:
                record(
                    "target.rescan_unavailable",
                    target_index=index,
                    resources=target.resources,
                    outcome="action_required",
                )
                results.append(
                    ProcessTargetResult(index, True, False, "rescan.unavailable")
                )
                journal_event(JournalEventKind.FAILED, "process_release.rescan_unavailable")
                return self._result(
                    ProcessReleaseStatus.ACTION_REQUIRED,
                    False,
                    results,
                    None,
                    audit,
                    journal,
                    "rescan.unavailable",
                )
            current = rescanned
            previous_generation = signal_generation
            try:
                revalidate_process_release_rescan(
                    approval,
                    current.snapshot,
                    observed_generation=current.sample_id,
                    previous_generation=signal_generation,
                )
            except ValueError:
                record(
                    "target.rescan_invalid",
                    target_index=index,
                    resources=target.resources,
                    outcome="action_required",
                )
                results.append(
                    ProcessTargetResult(index, True, False, "rescan.invalid")
                )
                journal_event(JournalEventKind.FAILED, "process_release.rescan_invalid")
                return self._result(
                    ProcessReleaseStatus.ACTION_REQUIRED,
                    False,
                    results,
                    current,
                    audit,
                    journal,
                    "rescan.invalid",
                )
            target_present = any(
                client.instance_id == target.instance_id
                for client in current.snapshot.disconnect_readiness.clients
            )
            released = not target_present
            code = "target.released" if released else "target.remaining"
            results.append(ProcessTargetResult(index, True, released, code))
            record(
                "target.rescanned",
                target_index=index,
                resources=target.resources,
                outcome="released" if released else "remaining",
            )
            placement = infer_placement(current.snapshot)
            journal_event(
                JournalEventKind.STEP_VERIFIED,
                "process_release.rescanned",
                child_step_code=child_step_code,
            )
            if elapsed < 0 or elapsed > self._deadline_ms:
                journal_event(JournalEventKind.FAILED, "process_release.signal_timeout")
                return self._result(
                    ProcessReleaseStatus.ACTION_REQUIRED,
                    False,
                    results,
                    current,
                    audit,
                    journal,
                    "signal.deadline_exceeded",
                )
            if not signal_result.accepted:
                journal_event(JournalEventKind.FAILED, "process_release.signal_rejected")
                return self._result(
                    ProcessReleaseStatus.ACTION_REQUIRED,
                    False,
                    results,
                    current,
                    audit,
                    journal,
                    signal_result.code,
                )

        readiness = current.snapshot.disconnect_readiness
        software_ready = bool(
            readiness.applicable
            and readiness.scan_complete
            and readiness.ready
            and not readiness.clients
            and not readiness.storage_in_use
        )
        record(
            "release.final_readiness",
            outcome="cleared" if software_ready else "blocked",
        )
        journal_event(JournalEventKind.COMMITTED, "process_release.committed")
        return self._result(
            ProcessReleaseStatus.COMPLETED,
            software_ready,
            results,
            current,
            audit,
            journal,
            "" if software_ready else "software_blockers_remain",
        )

    @staticmethod
    def _validate_child_parent(
        journal: TransitionJournal, parent_operation_id: str
    ) -> None:
        if (
            journal.operation_id != parent_operation_id
            or journal.terminal
            or not journal.entries
            or journal.entries[0].code != "sleep.requested"
        ):
            raise ValueError("process release parent journal does not match")
        active = next(
            (
                entry
                for entry in reversed(journal.entries)
                if entry.kind is JournalEventKind.STEP_STARTED
            ),
            None,
        )
        if (
            active is None
            or dict(active.details).get("step_code") != "releasing_clients"
            or journal.entries[-1].kind
            not in {
                JournalEventKind.STEP_STARTED,
                JournalEventKind.SUBSTEP_VERIFIED,
            }
        ):
            raise ValueError("process release parent journal step is invalid")

    @staticmethod
    def _result(
        status: ProcessReleaseStatus,
        software_ready: bool,
        results: list[ProcessTargetResult],
        current: VersionedObservation | None,
        audit: list[ProcessReleaseAuditEvent],
        journal: TransitionJournal,
        reason_code: str,
    ) -> ProcessReleaseReplayResult:
        remaining = (
            len(current.snapshot.disconnect_readiness.clients)
            if current is not None
            else None
        )
        return ProcessReleaseReplayResult(
            status=status,
            software_blockers_cleared=software_ready,
            hardware_removal_authorized=False,
            target_results=tuple(results),
            remaining_client_count=remaining,
            audit=tuple(audit),
            journal=journal,
            reason_code=reason_code,
        )


# Compatibility name retained for existing replay tests and external imports.
ProcessReleaseReplaySimulator = ProcessReleaseRunner


@dataclass(frozen=True, slots=True)
class ProcessReleaseRecoveryResult:
    journal: TransitionJournal | None
    action_required: bool
    code: str
    durable: bool


class ProcessReleaseJournalRecovery:
    """Terminalize an interrupted release without ever repeating a signal."""

    def __init__(
        self,
        journal_store: TransitionJournalPort,
        *,
        occurred_at: Callable[[], str],
    ) -> None:
        self._journal_store = journal_store
        self._occurred_at = occurred_at

    def recover(
        self, observation: VersionedObservation | None
    ) -> ProcessReleaseRecoveryResult:
        try:
            journal = self._journal_store.load_current()
        except Exception:
            return ProcessReleaseRecoveryResult(
                None, True, "process_release.journal_unavailable", False
            )
        if journal is None:
            return ProcessReleaseRecoveryResult(
                None, False, "process_release.no_recovery", True
            )
        if not self.is_process_release_journal(journal):
            return ProcessReleaseRecoveryResult(
                journal, True, "process_release.foreign_journal", True
            )
        if journal.terminal:
            terminal = journal.entries[-1]
            return ProcessReleaseRecoveryResult(
                journal,
                terminal.kind in (JournalEventKind.BLOCKED, JournalEventKind.FAILED),
                terminal.code,
                True,
            )
        if not journal.entries and observation is None:
            return ProcessReleaseRecoveryResult(
                journal, True, "process_release.journal_invalid", False
            )
        placement = (
            infer_placement(observation.snapshot)
            if observation is not None
            else journal.entries[-1].placement
        )
        try:
            terminal = append_journal_entry(
                journal,
                kind=JournalEventKind.FAILED,
                occurred_at=self._occurred_at(),
                workflow_state=WorkflowState.ACTION_REQUIRED,
                placement=placement,
                code="process_release.interrupted",
            )
            self._journal_store.save(terminal)
        except Exception:
            return ProcessReleaseRecoveryResult(
                journal, True, "process_release.recovery_persist_failed", False
            )
        return ProcessReleaseRecoveryResult(
            terminal, True, "process_release.interrupted", True
        )

    def acknowledge(self, operation_id: str) -> bool:
        if not TOKEN_RE.fullmatch(operation_id):
            return False
        try:
            journal = self._journal_store.load_current()
            if (
                journal is None
                or not journal.terminal
                or journal.operation_id != operation_id
                or not self.is_process_release_journal(journal)
            ):
                return False
            self._journal_store.clear_terminal(operation_id)
            return True
        except (OSError, ValueError):
            return False

    @staticmethod
    def is_process_release_journal(journal: TransitionJournal) -> bool:
        return bool(
            journal.entries
            and journal.entries[0].code == "process_release.requested"
        )
