"""Normalize durable whole-dock state for read-only presentation.

This module performs no I/O and grants no authority.  In particular, a
``software_down`` claim describes completed software teardown only; it never
means that physically unplugging the dock is safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class WholeDockLifecycleState(StrEnum):
    NONE = "none"
    IN_PROGRESS = "in_progress"
    SOFTWARE_DOWN = "software_down"
    RECONNECTING = "reconnecting"
    RECONNECTED = "reconnected"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class WholeDockLifecycleStatus:
    state: WholeDockLifecycleState
    code: str

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "state": self.state.value,
            "code": self.code,
        }


_TEARDOWN_STAGES = frozenset(
    {
        "claimed",
        "release_intent",
        "gpu_removed",
        "prepared",
        "usb_remove_intent",
        "usb_removed",
        "tunnel_remove_intent",
    }
)


def classify_whole_dock_lifecycle(
    *,
    claim_stage: str | None,
    claim_readable: bool,
    external_gpu_present: bool,
) -> WholeDockLifecycleStatus:
    """Classify one durable claim against the current GPU observation.

    ``external_gpu_present`` is contradiction evidence only.  Transport may
    remain present after a successful software teardown because the cable is
    intentionally still connected, so transport state does not belong here.
    """
    if not claim_readable:
        return WholeDockLifecycleStatus(
            WholeDockLifecycleState.UNKNOWN,
            "whole_dock.claim_unreadable",
        )
    if claim_stage is None:
        return WholeDockLifecycleStatus(
            WholeDockLifecycleState.NONE,
            "whole_dock.no_claim",
        )
    if claim_stage in _TEARDOWN_STAGES:
        return WholeDockLifecycleStatus(
            WholeDockLifecycleState.IN_PROGRESS,
            "whole_dock.teardown_in_progress",
        )
    if claim_stage == "software_down":
        if external_gpu_present:
            return WholeDockLifecycleStatus(
                WholeDockLifecycleState.CONFLICT,
                "whole_dock.software_down_gpu_present",
            )
        return WholeDockLifecycleStatus(
            WholeDockLifecycleState.SOFTWARE_DOWN,
            "whole_dock.software_down",
        )
    if claim_stage == "reauthorize_intent":
        return WholeDockLifecycleStatus(
            WholeDockLifecycleState.RECONNECTING,
            "whole_dock.reconnecting",
        )
    if claim_stage == "software_reconnected":
        if not external_gpu_present:
            return WholeDockLifecycleStatus(
                WholeDockLifecycleState.CONFLICT,
                "whole_dock.reconnected_gpu_absent",
            )
        return WholeDockLifecycleStatus(
            WholeDockLifecycleState.RECONNECTED,
            "whole_dock.reconnected",
        )
    return WholeDockLifecycleStatus(
        WholeDockLifecycleState.UNKNOWN,
        "whole_dock.claim_stage_unknown",
    )
