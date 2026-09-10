"""Read-only readiness watch for one exact eGPU-attach event.

An attach candidate never authorizes a transition. This small application
contract simply waits for a later fresh snapshot to determine whether the same
verified eGPU has a usable external display and a known game state. A future
transition owner must still obtain its own fresh binding and consent.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import StrEnum

from ..domain.event_policy import TopologyEvent
from ..domain.models import Confidence, DisplayKind, EgpuLinkState, GameState
from ..ports.transition import VersionedObservation
from ..profiles.registry import resolve_runtime_profiles
from .topology_event_detection import TopologyDetectionStatus, TopologyEventDetection


class AttachReadinessStage(StrEnum):
    IDLE = "idle"
    SETTLING = "settling"
    WAITING_FOR_EXTERNAL_DISPLAY = "waiting_for_external_display"
    WAITING_FOR_LINK_HEALTH = "waiting_for_link_health"
    READY_IDLE = "ready_idle"
    GAME_RUNNING = "game_running"
    ACTION_REQUIRED = "action_required"


READY_STABILITY_SAMPLES = 4


@dataclass(frozen=True, slots=True)
class AttachReadinessWatch:
    """Private identity binding created only from an exact attach candidate."""

    egpu_stable_id: str
    attached_generation: str
    attached_sample_id: str


@dataclass(frozen=True, slots=True)
class AttachReadinessStatus:
    stage: AttachReadinessStage
    code: str
    poll_after_ms: int

    def __post_init__(self) -> None:
        if self.poll_after_ms <= 0 or self.poll_after_ms > 30_000:
            raise ValueError("attach readiness polling delay is invalid")


def arm_attach_readiness(
    detection: TopologyEventDetection,
    attached: VersionedObservation,
) -> AttachReadinessWatch | None:
    """Bind an exact candidate to the current private eGPU identity."""
    if (
        detection.status is not TopologyDetectionStatus.DETECTED
        or detection.event is not TopologyEvent.EGPU_ATTACHED
        or detection.current_generation != attached.generation
        or detection.current_sample_id != attached.sample_id
    ):
        return None
    profiles = resolve_runtime_profiles(attached.snapshot)
    if not profiles.exact_host or not profiles.exact_egpu or not profiles.egpu_stable_id:
        return None
    return AttachReadinessWatch(
        profiles.egpu_stable_id,
        attached.generation,
        attached.sample_id,
    )


def arm_current_readiness(
    current: VersionedObservation,
) -> AttachReadinessWatch | None:
    """Bind an exact startup candidate without treating USB4 alone as an eGPU."""
    profiles = resolve_runtime_profiles(current.snapshot)
    if not profiles.exact_host or not profiles.exact_egpu or not profiles.egpu_stable_id:
        return None
    return AttachReadinessWatch(
        profiles.egpu_stable_id,
        current.generation,
        current.sample_id,
    )


def observe_attach_readiness(
    watch: AttachReadinessWatch,
    current: VersionedObservation | None,
) -> AttachReadinessStatus:
    """Classify a newer observation without inferring docking permission."""
    if current is None:
        return _status(AttachReadinessStage.ACTION_REQUIRED, "attach.observation_unavailable")
    if current.sample_id == watch.attached_sample_id:
        return _status(AttachReadinessStage.SETTLING, "attach.sample_not_fresh")
    profiles = resolve_runtime_profiles(current.snapshot)
    if (
        not profiles.exact_host
        or not profiles.exact_egpu
        or profiles.egpu_stable_id != watch.egpu_stable_id
    ):
        return _status(AttachReadinessStage.ACTION_REQUIRED, "attach.identity_changed")
    if (
        current.snapshot.gamescope.running is not True
        or current.snapshot.gamescope.confidence is not Confidence.VERIFIED
    ):
        return _status(AttachReadinessStage.ACTION_REQUIRED, "attach.session_unverified")
    if current.snapshot.game_state is GameState.UNKNOWN:
        return _status(AttachReadinessStage.ACTION_REQUIRED, "attach.game_state_unknown")
    external = tuple(
        display
        for display in current.snapshot.displays
        if display.kind is DisplayKind.EXTERNAL
        and display.connected is True
        and display.edid_ready is True
        and display.confidence is Confidence.VERIFIED
    )
    if len(external) != 1:
        return _status(
            AttachReadinessStage.WAITING_FOR_EXTERNAL_DISPLAY,
            "attach.external_display_unready",
        )
    link = current.snapshot.egpu_link
    if not link.applicable or link.state is not EgpuLinkState.UP:
        return _status(
            AttachReadinessStage.WAITING_FOR_LINK_HEALTH,
            "attach.link_down"
            if link.applicable and link.state is EgpuLinkState.DOWN
            else "attach.link_unverified",
        )
    if current.snapshot.game_state is GameState.RUNNING:
        return _status(AttachReadinessStage.GAME_RUNNING, "attach.game_running")
    return _status(AttachReadinessStage.READY_IDLE, "attach.ready_idle")


def _status(stage: AttachReadinessStage, code: str) -> AttachReadinessStatus:
    return AttachReadinessStatus(
        stage,
        code,
        (
            30_000
            if stage is AttachReadinessStage.IDLE
            else 250 if stage is AttachReadinessStage.SETTLING else 1_000
        ),
    )


class AttachReadinessLifecycle:
    """Serialize the one private attach watch beside an existing snapshot loop."""

    def __init__(self) -> None:
        self._watch: AttachReadinessWatch | None = None
        self._status = _status(AttachReadinessStage.IDLE, "attach.idle")
        self._ready_samples = 0
        self._last_ready_sample_id = ""
        self._lock = threading.Lock()

    def status(self) -> AttachReadinessStatus:
        with self._lock:
            return self._status

    def arm_current(self, current: VersionedObservation) -> AttachReadinessStatus:
        """Arm one exact already-attached startup candidate for a later sample."""
        with self._lock:
            if self._watch is None:
                self._watch = arm_current_readiness(current)
                self._reset_ready_stability()
                self._status = (
                    _status(AttachReadinessStage.SETTLING, "attach.startup_observed")
                    if self._watch is not None
                    else _status(AttachReadinessStage.ACTION_REQUIRED, "attach.arm_unverified")
                )
            return self._status

    def update(
        self,
        detection: TopologyEventDetection,
        current: VersionedObservation,
    ) -> AttachReadinessStatus:
        """Consume an already-collected snapshot; never collect or mutate."""
        with self._lock:
            if (
                detection.status is TopologyDetectionStatus.DETECTED
                and detection.event is TopologyEvent.EGPU_ATTACHED
            ):
                self._watch = arm_attach_readiness(detection, current)
                self._reset_ready_stability()
                self._status = (
                    _status(AttachReadinessStage.SETTLING, "attach.observed")
                    if self._watch is not None
                    else _status(AttachReadinessStage.ACTION_REQUIRED, "attach.arm_unverified")
                )
            elif self._watch is not None:
                observed = observe_attach_readiness(self._watch, current)
                if observed.stage is AttachReadinessStage.READY_IDLE:
                    if current.sample_id != self._last_ready_sample_id:
                        self._ready_samples += 1
                        self._last_ready_sample_id = current.sample_id
                    self._status = (
                        observed
                        if self._ready_samples >= READY_STABILITY_SAMPLES
                        else _status(
                            AttachReadinessStage.SETTLING,
                            "attach.ready_stabilizing",
                        )
                    )
                else:
                    self._reset_ready_stability()
                    self._status = observed
            return self._status

    def _reset_ready_stability(self) -> None:
        self._ready_samples = 0
        self._last_ready_sample_id = ""
