"""Privacy-safe payload mapping for the dormant canonical sleep facade."""

from __future__ import annotations

from ..application.canonical_sleep import CanonicalSleepResult, CanonicalSleepStatus
from ..application.sleep_recovery_checkpoint import SleepRecoveryCheckpoint


def result_to_payload(result: CanonicalSleepResult) -> dict[str, object]:
    flow = result.flow
    return {
        "schema_version": 1,
        "accepted": result.accepted,
        "code": result.code,
        "operation_id": result.operation_id,
        "stage": flow.stage.value if flow is not None else "",
        "directives": (
            [directive.value for directive in flow.directives]
            if flow is not None
            else []
        ),
        "original_request_pending": bool(
            flow is not None and flow.original_request_pending
        ),
        "durable": result.durable,
        "action_required": result.action_required,
    }


def status_to_payload(status: CanonicalSleepStatus) -> dict[str, object]:
    return {
        "schema_version": 1,
        "code": status.code,
        "operation_id": status.operation_id,
        "source": status.source.value if status.source is not None else "",
        "stage": status.stage.value if status.stage is not None else "",
        "acknowledgement_required": status.acknowledgement_required,
        "action_required": status.action_required,
        "durable": status.durable,
    }


def recovery_checkpoint_to_payload(
    checkpoint: SleepRecoveryCheckpoint,
) -> dict[str, object]:
    """Deliver a restart outcome without journal, hardware, or session identity."""
    return {
        "schema_version": 1,
        "kind": checkpoint.kind.value,
        "code": checkpoint.code,
        "acknowledgement_required": checkpoint.acknowledgement_required,
    }
