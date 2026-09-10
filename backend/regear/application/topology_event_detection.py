"""Pure, fail-closed topology-event detection over two complete snapshots.

The detector is deliberately not a watcher or transition trigger.  A future
event source must pass its candidate through this contract before the shared
transition/recovery authority can decide whether to act.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from ..domain.event_policy import TopologyEvent
from ..domain.models import Confidence, DisplayKind, GpuRole
from ..ports.transition import VersionedObservation
from ..profiles.registry import ProfileResolutionStatus, resolve_runtime_profiles


REASON_RE = re.compile(r"^[a-z0-9_.-]{1,96}$")


class TopologyDetectionStatus(StrEnum):
    DETECTED = "detected"
    NO_CHANGE = "no_change"
    UNVERIFIED = "unverified"


@dataclass(frozen=True, slots=True)
class TopologyEventDetection:
    """Private trigger binding; no hardware identity is exposed by this type."""

    status: TopologyDetectionStatus
    reason_code: str
    event: TopologyEvent | None = None
    previous_generation: str = ""
    previous_sample_id: str = ""
    current_generation: str = ""
    current_sample_id: str = ""

    def __post_init__(self) -> None:
        if not REASON_RE.fullmatch(self.reason_code):
            raise ValueError("topology detection reason is invalid")
        bindings = (
            self.previous_generation,
            self.previous_sample_id,
            self.current_generation,
            self.current_sample_id,
        )
        if self.status is TopologyDetectionStatus.DETECTED:
            if self.event is None or not all(bindings):
                raise ValueError("detected topology event requires an exact binding")
        elif self.event is not None or any(bindings):
            raise ValueError("non-detected topology event cannot carry a binding")


def detect_topology_event(
    previous: VersionedObservation | None,
    current: VersionedObservation | None,
) -> TopologyEventDetection:
    """Return one exact candidate only; uncertainty never becomes an event."""
    if previous is None or current is None:
        return _unverified("topology.observation_unavailable")
    if (
        previous.generation == current.generation
        or previous.sample_id == current.sample_id
        or not previous.generation
        or not current.generation
        or not previous.sample_id
        or not current.sample_id
    ):
        return _unverified("topology.observation_not_fresh")

    before_profiles = resolve_runtime_profiles(previous.snapshot)
    after_profiles = resolve_runtime_profiles(current.snapshot)
    if not before_profiles.exact_host or not after_profiles.exact_host:
        return _unverified("topology.host_unverified")

    # A USB4 device can appear before its PCI/DRM functions finish
    # enumerating.  Treat the first exact profile after either a verified
    # absence *or* that bounded unknown phase as the attach candidate.  The
    # attach-readiness lifecycle still requires a later fresh sample before a
    # transition can be considered.
    if not before_profiles.exact_egpu and after_profiles.exact_egpu:
        return _detected(TopologyEvent.EGPU_ATTACHED, previous, current)

    if before_profiles.exact_egpu:
        if after_profiles.egpu_status is ProfileResolutionStatus.ABSENT:
            if _exact_egpu_loss(previous, current, before_profiles.egpu_stable_id):
                return _detected(TopologyEvent.EGPU_REMOVED, previous, current)
            return _unverified("topology.removal_unverified")
        if (
            after_profiles.exact_egpu
            and after_profiles.egpu_stable_id == before_profiles.egpu_stable_id
            and _exact_external_display_loss(previous, current)
        ):
            return _detected(TopologyEvent.EXTERNAL_DISPLAY_LOST, previous, current)

    if (
        before_profiles.egpu_status is ProfileResolutionStatus.UNKNOWN
        or after_profiles.egpu_status is ProfileResolutionStatus.UNKNOWN
    ):
        return _unverified("topology.egpu_unverified")
    return TopologyEventDetection(TopologyDetectionStatus.NO_CHANGE, "topology.no_change")


def _exact_egpu_loss(previous, current, stable_id: str) -> bool:
    before = tuple(
        gpu
        for gpu in previous.snapshot.gpus
        if gpu.stable_id == stable_id
        and gpu.role is GpuRole.EXTERNAL
        and gpu.present
        and gpu.confidence is Confidence.VERIFIED
    )
    after = tuple(gpu for gpu in current.snapshot.gpus if gpu.stable_id == stable_id)
    return bool(
        len(before) == 1
        and len(after) == 1
        and after[0].role is GpuRole.EXTERNAL
        and after[0].present is False
        and after[0].confidence is Confidence.VERIFIED
        and not any(
            gpu.present and gpu.role is not GpuRole.INTERNAL
            for gpu in current.snapshot.gpus
        )
    )


def _exact_external_display_loss(previous, current) -> bool:
    before = tuple(
        display
        for display in previous.snapshot.displays
        if display.kind is DisplayKind.EXTERNAL
        and display.connected is True
        and display.active is True
        and display.confidence is Confidence.VERIFIED
    )
    after = tuple(
        display
        for display in current.snapshot.displays
        if display.stable_id == before[0].stable_id
    ) if len(before) == 1 else ()
    return bool(
        len(before) == 1
        and len(after) == 1
        and after[0].kind is DisplayKind.EXTERNAL
        and after[0].connected is False
        and after[0].active is False
        and after[0].confidence is Confidence.VERIFIED
        and not any(
            display.kind is DisplayKind.EXTERNAL
            and (display.connected is not False or display.active is True)
            for display in current.snapshot.displays
        )
    )


def _detected(event, previous, current) -> TopologyEventDetection:
    return TopologyEventDetection(
        TopologyDetectionStatus.DETECTED,
        f"topology.{event.value}",
        event,
        previous.generation,
        previous.sample_id,
        current.generation,
        current.sample_id,
    )


def _unverified(reason: str) -> TopologyEventDetection:
    return TopologyEventDetection(TopologyDetectionStatus.UNVERIFIED, reason)
