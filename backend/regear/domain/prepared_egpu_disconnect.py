"""Pure contract for a fan-safe, two-phase eGPU disconnect.

Preparation keeps the GPU driver and transport alive.  Full software teardown is
an intentionally short transition to physical cable removal, never a stable
connected state and never a software-reconnect opportunity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class EgpuCoolingEvidence:
    attachment_binding: str
    generation: str
    gpu_bdf: str
    device_present: bool
    driver_name: str
    scan_complete: bool
    temperatures_c: tuple[float, ...] = ()
    fan_rpm: int | None = None
    automatic_fan_control: bool | None = None


class PreparedDisconnectStage(StrEnum):
    REFUSED = "refused"
    PREPARED_CONNECTED = "prepared_connected"
    UNPLUG_REQUIRED = "unplug_required"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class PreparedDisconnectDecision:
    stage: PreparedDisconnectStage
    code: str
    stable_while_connected: bool = False
    may_start_final_teardown: bool = False
    unplug_required: bool = False
    complete: bool = False
    safe_to_unplug: bool = False


def _cooling_verified(evidence: EgpuCoolingEvidence) -> bool:
    return (
        type(evidence) is EgpuCoolingEvidence
        and bool(evidence.attachment_binding)
        and bool(evidence.generation)
        and evidence.device_present is True
        and evidence.driver_name == "amdgpu"
        and evidence.scan_complete is True
        and bool(evidence.temperatures_c)
        and all(
            type(value) in (int, float)
            and not isinstance(value, bool)
            and math.isfinite(value)
            and 0 <= value <= 200
            for value in evidence.temperatures_c
        )
        and type(evidence.fan_rpm) is int
        and 0 <= evidence.fan_rpm <= 1_000_000
        and evidence.automatic_fan_control is True
    )


def decide_prepared_disconnect(
    *,
    cooling: EgpuCoolingEvidence,
    display_on_handheld: bool,
    clients_released: bool,
    tunnel_authorized: bool | None,
) -> PreparedDisconnectDecision:
    """Decide whether the dock may wait in the prepared, still-connected phase.

    This decision authorizes no sysfs write.  It deliberately requires the GPU
    and its automatic cooling path to remain present; deauthorization is the
    later final step, after another explicit player action.
    """
    if display_on_handheld is not True:
        return PreparedDisconnectDecision(
            PreparedDisconnectStage.REFUSED,
            "prepared_disconnect.handheld_display_unverified",
        )
    if clients_released is not True:
        return PreparedDisconnectDecision(
            PreparedDisconnectStage.REFUSED,
            "prepared_disconnect.clients_not_released",
        )
    if tunnel_authorized is not True:
        return PreparedDisconnectDecision(
            PreparedDisconnectStage.REFUSED,
            "prepared_disconnect.transport_not_active",
        )
    if not _cooling_verified(cooling):
        return PreparedDisconnectDecision(
            PreparedDisconnectStage.REFUSED,
            "prepared_disconnect.cooling_unverified",
        )
    return PreparedDisconnectDecision(
        PreparedDisconnectStage.PREPARED_CONNECTED,
        "prepared_disconnect.ready_connected",
        stable_while_connected=True,
        may_start_final_teardown=True,
    )


def decide_post_teardown(
    *,
    software_down: bool,
    physical_transport_absent_verified: bool,
) -> PreparedDisconnectDecision:
    """Classify the state after final teardown without granting unplug safety.

    Once software-down, Re-Gear no longer has evidence that GPU-owned telemetry
    or fan control is available.  Cable-present software-down therefore remains
    an urgent transitional state.  Completion requires independent physical
    transport-absence evidence.
    """
    if physical_transport_absent_verified is True:
        return PreparedDisconnectDecision(
            PreparedDisconnectStage.COMPLETE,
            "prepared_disconnect.physical_removal_verified",
            complete=True,
        )
    if software_down is True:
        return PreparedDisconnectDecision(
            PreparedDisconnectStage.UNPLUG_REQUIRED,
            "prepared_disconnect.unplug_required",
            unplug_required=True,
        )
    return PreparedDisconnectDecision(
        PreparedDisconnectStage.REFUSED,
        "prepared_disconnect.final_teardown_unverified",
    )
