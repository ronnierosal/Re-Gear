"""Pure fail-closed policy for asynchronous topology and input events."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .control_plane import PlacementState, WorkflowState


class TopologyEvent(StrEnum):
    EGPU_ATTACHED = "egpu_attached"
    EGPU_REMOVED = "egpu_removed"
    EXTERNAL_DISPLAY_LOST = "external_display_lost"
    EXTERNAL_CONTROLLER_LOST = "external_controller_lost"
    TIMEOUT = "timeout"


class RecoveryDirective(StrEnum):
    OBSERVE_STABILITY = "observe_stability"
    RECOVER_PORTABLE = "recover_portable"
    RESTORE_BUILTIN_CONTROLLER = "restore_builtin_controller"
    ACTION_REQUIRED = "action_required"


@dataclass(frozen=True, slots=True)
class EventDecision:
    directives: tuple[RecoveryDirective, ...]
    next_workflow: WorkflowState
    reason_code: str


def decide_topology_event(
    *,
    event: TopologyEvent,
    placement: PlacementState,
    workflow: WorkflowState,
    builtin_controller_available: bool | None = None,
) -> EventDecision:
    if event is TopologyEvent.EGPU_ATTACHED:
        return EventDecision(
            (RecoveryDirective.OBSERVE_STABILITY,),
            WorkflowState.CONNECTING,
            "egpu.attached_observe",
        )

    if event is TopologyEvent.EGPU_REMOVED:
        if placement is PlacementState.PORTABLE:
            return EventDecision(
                (RecoveryDirective.OBSERVE_STABILITY,),
                WorkflowState.IDLE,
                "egpu.removed_already_portable",
            )
        if placement in {PlacementState.UNKNOWN, PlacementState.DEGRADED}:
            return EventDecision(
                (RecoveryDirective.ACTION_REQUIRED,),
                WorkflowState.ACTION_REQUIRED,
                "egpu.removed_placement_unverified",
            )
        return EventDecision(
            (RecoveryDirective.RECOVER_PORTABLE,),
            WorkflowState.RETURNING_TO_PORTABLE,
            (
                "egpu.removed_sleep_pending_recover"
                if workflow is WorkflowState.SLEEP_PENDING_DISCONNECT
                else "egpu.removed_unexpected_recover"
            ),
        )

    if event is TopologyEvent.EXTERNAL_CONTROLLER_LOST:
        if builtin_controller_available is True:
            return EventDecision(
                (RecoveryDirective.RESTORE_BUILTIN_CONTROLLER,),
                workflow,
                "controller.restore_builtin",
            )
        return EventDecision(
            (RecoveryDirective.ACTION_REQUIRED,),
            WorkflowState.ACTION_REQUIRED,
            "controller.fallback_unknown",
        )

    if event is TopologyEvent.EXTERNAL_DISPLAY_LOST and placement in (
        PlacementState.DOCKED_IGPU,
        PlacementState.DOCKED_EGPU,
    ):
        return EventDecision(
            (RecoveryDirective.RECOVER_PORTABLE,),
            WorkflowState.RETURNING_TO_PORTABLE,
            "display.external_lost",
        )

    return EventDecision(
        (RecoveryDirective.ACTION_REQUIRED,),
        WorkflowState.ACTION_REQUIRED,
        "event.state_unverified",
    )
