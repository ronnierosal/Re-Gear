"""Privacy-safe Docked-iGPU watcher lifecycle delivery."""

from __future__ import annotations

from ..application.docked_igpu_lifecycle import (
    DockedIgpuLifecycleInspection,
    DockedIgpuLifecycleStatus,
)


def lifecycle_status_to_payload(
    value: DockedIgpuLifecycleStatus,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "stage": value.stage.value,
        "code": value.code,
        "poll_after_ms": value.poll_after_ms,
        "inspection_available": value.inspection_available,
        "acknowledgement_required": value.acknowledgement_required,
    }


def lifecycle_inspection_to_payload(
    value: DockedIgpuLifecycleInspection,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "accepted": value.accepted,
        "code": value.code,
        "current": value.current.value,
        "target": value.target.value,
        "blockers": list(value.blockers),
    }
