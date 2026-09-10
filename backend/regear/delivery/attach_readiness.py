"""Identity-free delivery for the read-only eGPU attach readiness watch."""

from __future__ import annotations

from ..application.attach_readiness import AttachReadinessStatus


def attach_readiness_to_payload(value: AttachReadinessStatus) -> dict[str, object]:
    return {
        "schema_version": 1,
        "stage": value.stage.value,
        "code": value.code,
        "poll_after_ms": value.poll_after_ms,
    }
