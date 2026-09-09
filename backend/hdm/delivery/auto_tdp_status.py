"""Small public Auto TDP status; no raw configuration or hardware identities."""

from .tdp_runtime import TdpRuntime


def auto_tdp_status(code: str, runtime: TdpRuntime | None = None) -> dict[str, object]:
    status = runtime.auto_status() if runtime is not None else None
    policy = runtime.auto_policy if runtime is not None else None
    running = status is not None and status.running
    stopping = running and status.stopping
    enabled = bool(running and not stopping and status.last_result and status.last_result.enabled)
    return {
        "schema_version": 1,
        "can_start": code == "auto_tdp.ready" and not running,
        "enabled": enabled, "running": bool(running), "stopping": bool(stopping),
        "code": code,
        "activity_code": status.last_result.code if status and status.last_result else None,
        "target_fps": policy.target_fps if policy else None,
        "minimum_watts": policy.minimum_watts if policy else None,
        "maximum_watts": policy.maximum_watts if policy else None,
    }
