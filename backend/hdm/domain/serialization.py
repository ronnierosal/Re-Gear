"""Strict parsing for versioned read-only snapshot payloads."""

from __future__ import annotations

import math
from typing import Any

from .models import (
    Blocker,
    Confidence,
    DisconnectReadinessObservation,
    DisplayKind,
    DisplayObservation,
    EgpuClientKind,
    EgpuClientObservation,
    EgpuLinkObservation,
    EgpuLinkState,
    EgpuResourceKind,
    Evidence,
    GameState,
    GamescopeObservation,
    GpuObservation,
    GpuRole,
    ObservedSnapshot,
    SleepGuardObservation,
    SupportTier,
)


def _evidence_to_dict(values: tuple[Evidence, ...]) -> list[dict[str, Any]]:
    return [
        {
            "source": value.source,
            "confidence": value.confidence.value,
            "detail": value.detail,
        }
        for value in values
    ]


def snapshot_to_dict(snapshot: ObservedSnapshot, *, include_presentation: bool = False) -> dict[str, Any]:
    return {
        "schema_version": snapshot.schema_version,
        "observed_at": snapshot.observed_at,
        "host_profile": snapshot.host_profile,
        "support_tier": snapshot.support_tier.value,
        "game_state": snapshot.game_state.value,
        "gpus": [
            {
                "stable_id": gpu.stable_id,
                "role": gpu.role.value,
                "vendor_device": gpu.vendor_device,
                **({"model_name": gpu.model_name} if include_presentation else {}),
                "present": gpu.present,
                "selected_for_render": gpu.selected_for_render,
                "confidence": gpu.confidence.value,
                "evidence": _evidence_to_dict(gpu.evidence),
            }
            for gpu in snapshot.gpus
        ],
        "displays": [
            {
                "stable_id": display.stable_id,
                "kind": display.kind.value,
                "connector": display.connector,
                "connected": display.connected,
                "active": display.active,
                "edid_ready": display.edid_ready,
                "confidence": display.confidence.value,
                "evidence": _evidence_to_dict(display.evidence),
            }
            for display in snapshot.displays
        ],
        "gamescope": {
            "running": snapshot.gamescope.running,
            "pid": snapshot.gamescope.pid,
            "output_order": list(snapshot.gamescope.output_order),
            "render_gpu_stable_id": snapshot.gamescope.render_gpu_stable_id,
            "render_vendor_device": snapshot.gamescope.render_vendor_device,
            "confidence": snapshot.gamescope.confidence.value,
            "evidence": _evidence_to_dict(snapshot.gamescope.evidence),
        },
        "disconnect_readiness": {
            "applicable": snapshot.disconnect_readiness.applicable,
            "scan_complete": snapshot.disconnect_readiness.scan_complete,
            "ready": snapshot.disconnect_readiness.ready,
            "egpu_stable_id": snapshot.disconnect_readiness.egpu_stable_id,
            "clients": [
                {
                    "instance_id": client.instance_id,
                    "pid": client.pid,
                    "name": client.name,
                    "kind": client.kind.value,
                    "resources": [resource.value for resource in client.resources],
                    "close_eligible": client.close_eligible,
                    "reason": client.reason,
                    "process_start_time": client.process_start_time,
                }
                for client in snapshot.disconnect_readiness.clients
            ],
            "storage_devices": snapshot.disconnect_readiness.storage_devices,
            "storage_in_use": snapshot.disconnect_readiness.storage_in_use,
            "error": snapshot.disconnect_readiness.error,
        },
        "sleep_guard": {
            "required": snapshot.sleep_guard.required,
            "active": snapshot.sleep_guard.active,
            "confidence": snapshot.sleep_guard.confidence.value,
            "reason": snapshot.sleep_guard.reason,
            "error": snapshot.sleep_guard.error,
        },
        "egpu_link": {
            "applicable": snapshot.egpu_link.applicable,
            "state": snapshot.egpu_link.state.value,
            "confidence": snapshot.egpu_link.confidence.value,
            "reason": snapshot.egpu_link.reason,
            "error": snapshot.egpu_link.error,
            "speed_gtps": snapshot.egpu_link.speed_gtps,
            "width_lanes": snapshot.egpu_link.width_lanes,
        },
        "blockers": [
            {"code": blocker.code, "message": blocker.message}
            for blocker in snapshot.blockers
        ],
    }


def _optional_bool(value: Any, field_name: str) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise ValueError(f"{field_name} must be a boolean or null")


def _required_bool(value: Any, field_name: str) -> bool:
    parsed = _optional_bool(value, field_name)
    if parsed is None:
        raise ValueError(f"{field_name} must be a boolean")
    return parsed


def _optional_pid(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("gamescope.pid must be a positive integer or null")
    return value


def _optional_nonnegative_float(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a non-negative number or null")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f"{field_name} must be a non-negative number or null")
    return parsed


def _optional_nonnegative_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer or null")
    return value


def _evidence(values: list[dict[str, Any]] | None) -> tuple[Evidence, ...]:
    return tuple(
        Evidence(
            source=str(value["source"]),
            confidence=Confidence(value["confidence"]),
            detail=str(value.get("detail", "")),
        )
        for value in values or []
    )


def snapshot_from_dict(value: dict[str, Any]) -> ObservedSnapshot:
    version = int(value["schema_version"])
    if version not in (1, 2, 3):
        raise ValueError(f"Unsupported snapshot schema version: {version}")

    gpus = tuple(
        GpuObservation(
            stable_id=str(gpu["stable_id"]),
            role=GpuRole(gpu["role"]),
            vendor_device=str(gpu.get("vendor_device", "")),
            model_name=gpu.get("model_name", "") if isinstance(gpu.get("model_name", ""), str) else "",
            present=_required_bool(gpu["present"], "gpu.present"),
            selected_for_render=_optional_bool(
                gpu.get("selected_for_render"), "gpu.selected_for_render"
            ),
            confidence=Confidence(gpu.get("confidence", "unknown")),
            evidence=_evidence(gpu.get("evidence")),
        )
        for gpu in value["gpus"]
    )
    displays = tuple(
        DisplayObservation(
            stable_id=str(display["stable_id"]),
            kind=DisplayKind(display["kind"]),
            connector=str(display.get("connector", "")),
            connected=_optional_bool(display.get("connected"), "display.connected"),
            active=_optional_bool(display.get("active"), "display.active"),
            edid_ready=_optional_bool(display.get("edid_ready"), "display.edid_ready"),
            confidence=Confidence(display.get("confidence", "unknown")),
            evidence=_evidence(display.get("evidence")),
        )
        for display in value["displays"]
    )
    gamescope_value = value["gamescope"]
    gamescope = GamescopeObservation(
        running=_optional_bool(gamescope_value.get("running"), "gamescope.running"),
        pid=_optional_pid(gamescope_value.get("pid")),
        output_order=tuple(str(item) for item in gamescope_value.get("output_order", [])),
        render_gpu_stable_id=str(gamescope_value.get("render_gpu_stable_id", "")),
        render_vendor_device=str(gamescope_value.get("render_vendor_device", "")),
        confidence=Confidence(gamescope_value.get("confidence", "unknown")),
        evidence=_evidence(gamescope_value.get("evidence")),
    )
    readiness_value = value.get("disconnect_readiness", {})
    clients = tuple(
        EgpuClientObservation(
            instance_id=str(client["instance_id"]),
            pid=int(client["pid"]),
            name=str(client["name"]),
            kind=EgpuClientKind(client["kind"]),
            resources=tuple(EgpuResourceKind(item) for item in client.get("resources", [])),
            close_eligible=_required_bool(
                client["close_eligible"], "disconnect client.close_eligible"
            ),
            reason=str(client.get("reason", "")),
            process_start_time=str(client.get("process_start_time", "")),
        )
        for client in readiness_value.get("clients", [])
    )
    readiness = DisconnectReadinessObservation(
        applicable=_required_bool(
            readiness_value.get("applicable", False), "disconnect.applicable"
        ),
        scan_complete=_required_bool(
            readiness_value.get("scan_complete", True), "disconnect.scan_complete"
        ),
        ready=_required_bool(readiness_value.get("ready", True), "disconnect.ready"),
        egpu_stable_id=str(readiness_value.get("egpu_stable_id", "")),
        clients=clients,
        storage_devices=int(readiness_value.get("storage_devices", 0)),
        storage_in_use=_required_bool(
            readiness_value.get("storage_in_use", False), "disconnect.storage_in_use"
        ),
        error=str(readiness_value.get("error", "")),
    )
    sleep_guard_value = value.get("sleep_guard", {})
    sleep_guard = SleepGuardObservation(
        required=_required_bool(
            sleep_guard_value.get("required", False), "sleep_guard.required"
        ),
        active=_required_bool(
            sleep_guard_value.get("active", False), "sleep_guard.active"
        ),
        confidence=Confidence(sleep_guard_value.get("confidence", "unknown")),
        reason=str(sleep_guard_value.get("reason", "")),
        error=str(sleep_guard_value.get("error", "")),
    )
    link_value = value.get("egpu_link", {})
    egpu_link = EgpuLinkObservation(
        applicable=_required_bool(link_value.get("applicable", False), "egpu_link.applicable"),
        state=EgpuLinkState(link_value.get("state", "unknown")),
        confidence=Confidence(link_value.get("confidence", "unknown")),
        reason=str(link_value.get("reason", "")),
        error=str(link_value.get("error", "")),
        speed_gtps=_optional_nonnegative_float(
            link_value.get("speed_gtps"), "egpu_link.speed_gtps"
        ),
        width_lanes=_optional_nonnegative_int(
            link_value.get("width_lanes"), "egpu_link.width_lanes"
        ),
    )
    blockers = tuple(
        Blocker(code=str(blocker["code"]), message=str(blocker["message"]))
        for blocker in value.get("blockers", [])
    )
    return ObservedSnapshot(
        schema_version=version,
        observed_at=str(value["observed_at"]),
        host_profile=str(value.get("host_profile", "")),
        support_tier=SupportTier(value.get("support_tier", "unknown")),
        game_state=GameState(value["game_state"]),
        gpus=gpus,
        displays=displays,
        gamescope=gamescope,
        disconnect_readiness=readiness,
        sleep_guard=sleep_guard,
        egpu_link=egpu_link,
        blockers=blockers,
    )
