"""Privacy-safe Decky payloads for the guarded process-release service."""

from __future__ import annotations

from typing import Any

from ..application.guarded_process_release import (
    GuardedProcessReleaseExecution,
    GuardedProcessReleasePreview,
    GuardedProcessReleaseStatus,
)


def preview_to_payload(preview: GuardedProcessReleasePreview) -> dict[str, Any]:
    details = preview.details
    return {
        "schema_version": 1,
        "phase": preview.phase.value,
        "ready": preview.ready,
        "approval_token": details.token if details is not None else "",
        "expires_in_seconds": (
            details.expires_in_seconds if details is not None else 0
        ),
        "targets": (
            [
                {
                    "name": target.name,
                    "resources": [resource.value for resource in target.resources],
                }
                for target in details.targets
            ]
            if details is not None
            else []
        ),
        "protected_client_count": (
            details.protected_client_count if details is not None else 0
        ),
        "blockers": list(preview.blockers),
        "confirmation_required": bool(
            preview.ready and details is not None and not details.token
        ),
    }


def execution_to_payload(
    execution: GuardedProcessReleaseExecution,
) -> dict[str, Any]:
    result = execution.result
    return {
        "schema_version": 1,
        "accepted": execution.accepted,
        "code": execution.code,
        "acknowledgement_id": execution.operation_id,
        "status": result.status.value if result is not None else "",
        "software_blockers_cleared": bool(
            result is not None and result.software_blockers_cleared
        ),
        "hardware_removal_authorized": False,
        "remaining_client_count": (
            result.remaining_client_count if result is not None else None
        ),
        "force_receipt_token": execution.force_receipt_token,
        "action_required": execution.action_required,
    }


def status_to_payload(status: GuardedProcessReleaseStatus) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "code": status.code,
        "acknowledgement_required": status.acknowledgement_required,
        "action_required": status.action_required,
        "acknowledgement_id": status.operation_id,
        "durable": status.durable,
    }
