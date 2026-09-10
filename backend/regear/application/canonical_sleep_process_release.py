"""Compose guarded process release as a canonical sleep child step."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.process_release import ReleasePhase
from ..domain.sleep_workflow import SleepFlowEvent
from .canonical_sleep import CanonicalSleepResult, CanonicalSleepWorkflowService
from .guarded_process_release import (
    GuardedProcessReleaseExecution,
    GuardedProcessReleasePreview,
    GuardedProcessReleaseService,
)


@dataclass(frozen=True, slots=True)
class CanonicalSleepProcessExecution:
    process: GuardedProcessReleaseExecution
    sleep: CanonicalSleepResult | None = None


class CanonicalSleepProcessReleaseCoordinator:
    """Bind process approvals to one active sleep transaction.

    This coordinator has no Decky RPC. The backend obtains the parent operation
    identity from the sleep service; neither a frontend nor a caller supplies it.
    """

    def __init__(
        self,
        sleep: CanonicalSleepWorkflowService,
        process: GuardedProcessReleaseService,
    ) -> None:
        self._sleep = sleep
        self._process = process

    def preview(
        self,
        request_id: str,
        phase: ReleasePhase,
        *,
        user_confirmed: bool,
        graceful_receipt_token: str = "",
    ) -> GuardedProcessReleasePreview:
        parent = self._sleep.release_parent_operation_id(request_id)
        if not parent:
            return GuardedProcessReleasePreview(
                phase, blockers=("sleep.client_release_step_inactive",)
            )
        return self._process.preview(
            phase,
            user_confirmed=user_confirmed,
            graceful_receipt_token=graceful_receipt_token,
            parent_operation_id=parent,
        )

    def execute(
        self,
        request_id: str,
        approval_token: str,
    ) -> CanonicalSleepProcessExecution:
        parent = self._sleep.release_parent_operation_id(request_id)
        if not parent:
            return CanonicalSleepProcessExecution(
                GuardedProcessReleaseExecution(
                    False, "sleep.client_release_step_inactive", action_required=True
                )
            )
        process = self._process.execute(approval_token)
        result = process.result
        if (
            not process.accepted
            or process.action_required
            or result is None
            or not result.software_blockers_cleared
        ):
            return CanonicalSleepProcessExecution(process)
        sleep = self._sleep.advance(
            request_id,
            SleepFlowEvent.SOFTWARE_CLIENTS_RELEASED,
        )
        return CanonicalSleepProcessExecution(process, sleep)
