"""Project canonical sleep reducer states into the durable journal contract.

This module performs no I/O and never resumes sleep. Its restart recovery
policy can only record verified portable recovery or require user action.
"""

from __future__ import annotations

from ..domain.control_plane import PlacementState, WorkflowState
from ..domain.sleep_workflow import SleepFlow, SleepFlowStage
from ..domain.transition_journal import (
    JournalEventKind,
    TransitionJournal,
    append_journal_entry,
)


_INTERMEDIATE_STAGES = frozenset(
    {
        SleepFlowStage.AWAITING_GAME_CONSENT,
        SleepFlowStage.CLOSING_GAME,
        SleepFlowStage.RELEASING_CLIENTS,
        SleepFlowStage.AWAITING_DISCONNECT,
        SleepFlowStage.RESTORING_PORTABLE,
        SleepFlowStage.READY_TO_CONTINUE_SLEEP,
    }
)

_BLOCKED_STAGES = frozenset(
    {
        SleepFlowStage.SHUTDOWN_REQUIRED,
        SleepFlowStage.CANCELLED,
        SleepFlowStage.ACTION_REQUIRED,
    }
)


def start_sleep_journal(
    operation_id: str,
    flow: SleepFlow,
    placement: PlacementState,
    *,
    occurred_at: str,
) -> TransitionJournal:
    journal = TransitionJournal(operation_id, flow.request_id)
    journal = _append(
        journal,
        JournalEventKind.REQUESTED,
        WorkflowState.SLEEP_PENDING_DISCONNECT,
        placement,
        "sleep.requested",
        occurred_at,
    )
    journal = _append(
        journal,
        JournalEventKind.OBSERVED,
        _workflow_for(flow.stage),
        placement,
        "sleep.context_observed",
        occurred_at,
    )
    if flow.stage is SleepFlowStage.ACTION_REQUIRED:
        return _blocked(journal, flow, placement, occurred_at)
    journal = _append(
        journal,
        JournalEventKind.VALIDATED,
        _workflow_for(flow.stage),
        placement,
        "sleep.context_validated",
        occurred_at,
    )
    journal = _append(
        journal,
        JournalEventKind.PLANNED,
        _workflow_for(flow.stage),
        placement,
        "sleep.flow_planned",
        occurred_at,
    )
    if flow.stage in _BLOCKED_STAGES:
        return _blocked(journal, flow, placement, occurred_at)
    if flow.stage is SleepFlowStage.NORMAL_SLEEP_ALLOWED:
        return _append(
            journal,
            JournalEventKind.COMMITTED,
            WorkflowState.IDLE,
            placement,
            "sleep.normal_allowed",
            occurred_at,
        )
    if flow.stage is SleepFlowStage.COMPLETED:
        return _append(
            journal,
            JournalEventKind.COMMITTED,
            WorkflowState.IDLE,
            placement,
            "sleep.completed",
            occurred_at,
        )
    return _start_step(journal, flow, placement, occurred_at)


def advance_sleep_journal(
    journal: TransitionJournal,
    before: SleepFlow,
    after: SleepFlow,
    placement: PlacementState,
    *,
    occurred_at: str,
) -> TransitionJournal:
    _validate_active_sleep_journal(journal, before)
    if after.request_id != before.request_id:
        raise ValueError("sleep flow request identity changed")
    if after.history != (*before.history, before.stage):
        raise ValueError("sleep flow history did not advance exactly once")
    if after.stage in _BLOCKED_STAGES:
        return _blocked(journal, after, placement, occurred_at)
    journal = _append(
        journal,
        JournalEventKind.STEP_VERIFIED,
        _workflow_for(before.stage),
        placement,
        "sleep.step_verified",
        occurred_at,
        (("step_code", before.stage.value),),
    )
    if after.stage is SleepFlowStage.COMPLETED:
        return _append(
            journal,
            JournalEventKind.COMMITTED,
            WorkflowState.IDLE,
            placement,
            "sleep.completed",
            occurred_at,
        )
    if after.stage not in _INTERMEDIATE_STAGES:
        raise ValueError("sleep flow advanced to an unsupported stage")
    return _start_step(journal, after, placement, occurred_at)


def recover_interrupted_sleep_journal(
    journal: TransitionJournal,
    placement: PlacementState,
    *,
    exact_egpu_absence_verified: bool,
    occurred_at: str,
) -> TransitionJournal:
    _validate_sleep_journal(journal)
    if journal.terminal:
        raise ValueError("terminal sleep journal does not require recovery")
    last = journal.entries[-1].kind
    if last in {
        JournalEventKind.REQUESTED,
        JournalEventKind.OBSERVED,
        JournalEventKind.VALIDATED,
        JournalEventKind.PLANNED,
    }:
        return _append(
            journal,
            JournalEventKind.BLOCKED,
            WorkflowState.ACTION_REQUIRED,
            placement,
            "sleep.restart_before_action",
            occurred_at,
            (("blocker_code", "sleep.restart_interrupted"),),
        )
    if last not in {
        JournalEventKind.STEP_STARTED,
        JournalEventKind.SUBSTEP_STARTED,
        JournalEventKind.SUBSTEP_VERIFIED,
        JournalEventKind.STEP_VERIFIED,
    }:
        raise ValueError("sleep journal is not recoverable from its current event")
    journal = _append(
        journal,
        JournalEventKind.RECOVERY_STARTED,
        WorkflowState.RECOVERING,
        placement,
        "sleep.restart_recovery_started",
        occurred_at,
    )
    if placement is PlacementState.PORTABLE and exact_egpu_absence_verified:
        return _append(
            journal,
            JournalEventKind.RECOVERY_VERIFIED,
            WorkflowState.IDLE,
            placement,
            "sleep.restart_portable_verified",
            occurred_at,
        )
    return _append(
        journal,
        JournalEventKind.FAILED,
        WorkflowState.ACTION_REQUIRED,
        placement,
        "sleep.restart_action_required",
        occurred_at,
        (("reason_code", "sleep.portable_recovery_unverified"),),
    )


def _start_step(
    journal: TransitionJournal,
    flow: SleepFlow,
    placement: PlacementState,
    occurred_at: str,
) -> TransitionJournal:
    if flow.stage not in _INTERMEDIATE_STAGES:
        raise ValueError("sleep stage is not an executable journal step")
    return _append(
        journal,
        JournalEventKind.STEP_STARTED,
        _workflow_for(flow.stage),
        placement,
        "sleep.step_started",
        occurred_at,
        (("step_code", flow.stage.value),),
    )


def _blocked(
    journal: TransitionJournal,
    flow: SleepFlow,
    placement: PlacementState,
    occurred_at: str,
) -> TransitionJournal:
    return _append(
        journal,
        JournalEventKind.BLOCKED,
        _workflow_for(flow.stage),
        placement,
        "sleep.blocked",
        occurred_at,
        (("blocker_code", flow.reason_code),),
    )


def _validate_active_sleep_journal(
    journal: TransitionJournal, flow: SleepFlow
) -> None:
    _validate_sleep_journal(journal)
    if journal.terminal:
        raise ValueError("cannot advance a terminal sleep journal")
    if journal.request_id != flow.request_id:
        raise ValueError("sleep journal request identity does not match")
    last = journal.entries[-1]
    if last.kind not in {
        JournalEventKind.STEP_STARTED,
        JournalEventKind.SUBSTEP_VERIFIED,
    }:
        raise ValueError("sleep journal has no active step")
    active = next(
        (
            entry
            for entry in reversed(journal.entries)
            if entry.kind is JournalEventKind.STEP_STARTED
        ),
        None,
    )
    if active is None or dict(active.details).get("step_code") != flow.stage.value:
        raise ValueError("sleep journal active step does not match the flow")


def _validate_sleep_journal(journal: TransitionJournal) -> None:
    if not journal.entries or journal.entries[0].code != "sleep.requested":
        raise ValueError("journal is not a canonical sleep journal")


def _workflow_for(stage: SleepFlowStage) -> WorkflowState:
    if stage is SleepFlowStage.NORMAL_SLEEP_ALLOWED:
        return WorkflowState.IDLE
    if stage is SleepFlowStage.AWAITING_DISCONNECT:
        return WorkflowState.SAFE_TO_DISCONNECT
    if stage is SleepFlowStage.RESTORING_PORTABLE:
        return WorkflowState.RETURNING_TO_PORTABLE
    if stage in {SleepFlowStage.COMPLETED, SleepFlowStage.CANCELLED}:
        return WorkflowState.IDLE
    if stage is SleepFlowStage.ACTION_REQUIRED:
        return WorkflowState.ACTION_REQUIRED
    return WorkflowState.SLEEP_PENDING_DISCONNECT


def _append(
    journal: TransitionJournal,
    kind: JournalEventKind,
    workflow: WorkflowState,
    placement: PlacementState,
    code: str,
    occurred_at: str,
    details: tuple[tuple[str, str], ...] = (),
) -> TransitionJournal:
    return append_journal_entry(
        journal,
        kind=kind,
        occurred_at=occurred_at,
        workflow_state=workflow,
        placement=placement,
        code=code,
        details=details,
    )
