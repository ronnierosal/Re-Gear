"""Identity-free Decky mapping for ephemeral diagnostic logging state."""

from __future__ import annotations

from ..application.diagnostic_logging import DiagnosticLoggingStatus


def diagnostic_logging_status_to_payload(
    status: DiagnosticLoggingStatus,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "enabled": status.enabled,
        "mode": status.mode.value,
        "duration": status.duration.value if status.duration is not None else "",
        "remaining_seconds": status.remaining_seconds,
        "code": status.reason_code,
    }
