"""Privacy-safe payloads for the dormant Docked-iGPU exit watcher."""

from __future__ import annotations

from ..application.docked_igpu_exit import (
    DockedIgpuExitArmResult,
    DockedIgpuExitWatch,
)


def arm_result_to_payload(result: DockedIgpuExitArmResult) -> dict[str, object]:
    return {
        "schema_version": 1,
        "accepted": result.accepted,
        "code": result.code,
        "watch": watch_to_payload(result.watch) if result.watch is not None else None,
    }


def watch_to_payload(watch: DockedIgpuExitWatch) -> dict[str, object]:
    return {
        "schema_version": 1,
        "watch_id": watch.watch_id,
        "stage": watch.stage.value,
        "reason_code": watch.reason_code,
        "target": watch.target.value if watch.target is not None else "",
        "terminal": watch.terminal,
    }
