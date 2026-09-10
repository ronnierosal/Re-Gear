"""Pure, categorical health aggregation independent of placement/workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .control_plane import PlacementState, WorkflowState
from .models import Confidence, EgpuLinkState, ObservedSnapshot
from .peripheral_handoff import PeripheralObservation


class HealthState(StrEnum):
    READY = "ready"
    RECOVERING = "recovering"
    DEGRADED = "degraded"
    ATTENTION_REQUIRED = "attention_required"


class HealthComponent(StrEnum):
    PLACEMENT = "placement"
    WORKFLOW = "workflow"
    SESSION = "session"
    DISPLAY = "display"
    EGPU_LINK = "egpu_link"
    STORAGE = "storage"
    CONTROLLER = "controller"
    AUDIO = "audio"


class HealthEvidenceState(StrEnum):
    READY = "ready"
    RECOVERING = "recovering"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class HealthComponentObservation:
    component: HealthComponent
    state: HealthEvidenceState
    reason: str = ""


@dataclass(frozen=True, slots=True)
class HealthAssessment:
    state: HealthState
    components: tuple[HealthComponentObservation, ...] = field(default_factory=tuple)
    blockers: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        components = tuple(component.component for component in self.components)
        if len(components) != len(set(components)):
            raise ValueError("health components must be unique")
        if self.state is HealthState.READY and self.blockers:
            raise ValueError("ready health cannot have blockers")


def assess_health(
    components: tuple[HealthComponentObservation, ...],
) -> HealthAssessment:
    """Aggregate evidence conservatively without inferring omitted components.

    Callers decide which independently observable components belong to a given
    assessment. Unknown evidence always requires attention; it is never folded
    into a healthy placement merely because a device is present.
    """
    seen: set[HealthComponent] = set()
    for component in components:
        if component.component in seen:
            return HealthAssessment(
                HealthState.ATTENTION_REQUIRED,
                (),
                ("health.duplicate_component",),
            )
        seen.add(component.component)

    if not components:
        return HealthAssessment(
            HealthState.ATTENTION_REQUIRED,
            (),
            ("health.no_observations",),
        )

    degraded = tuple(
        f"health.{component.component.value}_degraded"
        for component in components
        if component.state is HealthEvidenceState.DEGRADED
    )
    if degraded:
        return HealthAssessment(HealthState.DEGRADED, components, degraded)

    unknown = tuple(
        f"health.{component.component.value}_unknown"
        for component in components
        if component.state is HealthEvidenceState.UNKNOWN
    )
    if unknown:
        return HealthAssessment(HealthState.ATTENTION_REQUIRED, components, unknown)

    if any(
        component.state is HealthEvidenceState.RECOVERING for component in components
    ):
        return HealthAssessment(HealthState.RECOVERING, components)
    return HealthAssessment(HealthState.READY, components)


def assess_snapshot_health(
    snapshot: ObservedSnapshot,
    placement: PlacementState,
    peripheral: PeripheralObservation | None = None,
    workflow: WorkflowState | None = None,
    *,
    peripheral_unavailable: bool = False,
    workflow_unavailable: bool = False,
) -> HealthAssessment:
    """Assess only current read-only snapshot evidence.

    A caller may add one separately collected peripheral observation. Incomplete
    peripheral mapping/default-output/input evidence remains Attention Required;
    it is never treated as usable merely because sysfs inventory exists. External
    placements retain an unknown eGPU-link component until the read-only
    collector can observe an exact bridge; a connected eGPU is not silently
    considered healthy.
    """
    components = [
        _placement_component(placement),
        _session_component(snapshot),
        _display_component(snapshot),
    ]
    if workflow_unavailable:
        components.append(
            HealthComponentObservation(
                HealthComponent.WORKFLOW,
                HealthEvidenceState.UNKNOWN,
                "workflow.observation_unavailable",
            )
        )
    else:
        workflow_component = _workflow_component(workflow)
        if workflow_component is not None:
            components.append(workflow_component)
    if placement in {
        PlacementState.BOOSTED_HANDHELD,
        PlacementState.DOCKED_EGPU,
    }:
        components.append(_egpu_link_component(snapshot))
    if snapshot.disconnect_readiness.applicable:
        components.append(_storage_component(snapshot))
    if peripheral_unavailable:
        components.extend(
            (
                HealthComponentObservation(
                    HealthComponent.CONTROLLER,
                    HealthEvidenceState.UNKNOWN,
                    "controller.observation_unavailable",
                ),
                HealthComponentObservation(
                    HealthComponent.AUDIO,
                    HealthEvidenceState.UNKNOWN,
                    "audio.observation_unavailable",
                ),
            )
        )
    elif peripheral is not None:
        components.extend((_controller_component(peripheral), _audio_component(peripheral)))
    return assess_health(tuple(components))


def _placement_component(placement: PlacementState) -> HealthComponentObservation:
    if placement is PlacementState.DEGRADED:
        return HealthComponentObservation(
            HealthComponent.PLACEMENT,
            HealthEvidenceState.DEGRADED,
            "placement.degraded",
        )
    if placement is PlacementState.UNKNOWN:
        return HealthComponentObservation(
            HealthComponent.PLACEMENT,
            HealthEvidenceState.UNKNOWN,
            "placement.unknown",
        )
    return HealthComponentObservation(HealthComponent.PLACEMENT, HealthEvidenceState.READY)


def _workflow_component(
    workflow: WorkflowState | None,
) -> HealthComponentObservation | None:
    """Project recovery/action workflow without changing observed placement.

    Most workflow phases express a requested transition, not a fact about
    usability, so they do not alter health. Only explicit recovery or terminal
    attention phases are health-relevant, and callers must supply them from the
    authoritative workflow owner rather than reconstructing them from hardware.
    """
    if workflow in {WorkflowState.RECOVERING, WorkflowState.RETURNING_TO_PORTABLE}:
        return HealthComponentObservation(
            HealthComponent.WORKFLOW,
            HealthEvidenceState.RECOVERING,
            "workflow.recovering",
        )
    if workflow in {WorkflowState.ACTION_REQUIRED, WorkflowState.FAILED}:
        return HealthComponentObservation(
            HealthComponent.WORKFLOW,
            HealthEvidenceState.UNKNOWN,
            "workflow.action_required",
        )
    return None


def _session_component(snapshot: ObservedSnapshot) -> HealthComponentObservation:
    if snapshot.gamescope.running is False:
        return HealthComponentObservation(
            HealthComponent.SESSION,
            HealthEvidenceState.DEGRADED,
            "gamescope.not_running",
        )
    if (
        snapshot.gamescope.running is not True
        or snapshot.gamescope.confidence is not Confidence.VERIFIED
    ):
        return HealthComponentObservation(
            HealthComponent.SESSION,
            HealthEvidenceState.UNKNOWN,
            "gamescope.unverified",
        )
    return HealthComponentObservation(HealthComponent.SESSION, HealthEvidenceState.READY)


def _display_component(snapshot: ObservedSnapshot) -> HealthComponentObservation:
    active = tuple(display for display in snapshot.displays if display.active is True)
    if len(active) != 1:
        return HealthComponentObservation(
            HealthComponent.DISPLAY,
            HealthEvidenceState.UNKNOWN,
            "display.active_ambiguous",
        )
    display = active[0]
    if display.connected is False:
        return HealthComponentObservation(
            HealthComponent.DISPLAY,
            HealthEvidenceState.DEGRADED,
            "display.active_disconnected",
        )
    if (
        display.connected is not True
        or display.confidence is not Confidence.VERIFIED
        or display.connector not in snapshot.gamescope.output_order
    ):
        return HealthComponentObservation(
            HealthComponent.DISPLAY,
            HealthEvidenceState.UNKNOWN,
            "display.unverified",
        )
    return HealthComponentObservation(HealthComponent.DISPLAY, HealthEvidenceState.READY)


def _storage_component(snapshot: ObservedSnapshot) -> HealthComponentObservation:
    readiness = snapshot.disconnect_readiness
    if not readiness.scan_complete:
        return HealthComponentObservation(
            HealthComponent.STORAGE,
            HealthEvidenceState.UNKNOWN,
            "storage.scan_incomplete",
        )
    if readiness.storage_in_use:
        return HealthComponentObservation(
            HealthComponent.STORAGE,
            HealthEvidenceState.DEGRADED,
            "storage.egpu_in_use",
        )
    return HealthComponentObservation(HealthComponent.STORAGE, HealthEvidenceState.READY)


def _egpu_link_component(snapshot: ObservedSnapshot) -> HealthComponentObservation:
    link = snapshot.egpu_link
    if link.applicable and link.state is EgpuLinkState.UP:
        return HealthComponentObservation(
            HealthComponent.EGPU_LINK, HealthEvidenceState.READY, link.reason
        )
    if link.applicable and link.state is EgpuLinkState.DOWN:
        return HealthComponentObservation(
            HealthComponent.EGPU_LINK, HealthEvidenceState.DEGRADED, link.reason
        )
    return HealthComponentObservation(
        HealthComponent.EGPU_LINK,
        HealthEvidenceState.UNKNOWN,
        link.error or "egpu.link_health_unobserved",
    )


def _controller_component(
    peripheral: PeripheralObservation,
) -> HealthComponentObservation:
    controller = peripheral.controller
    if not controller.complete or not controller.exact:
        return HealthComponentObservation(
            HealthComponent.CONTROLLER,
            HealthEvidenceState.UNKNOWN,
            controller.failure_code or "controller.observation_incomplete",
        )
    if controller.builtin_available is False:
        return HealthComponentObservation(
            HealthComponent.CONTROLLER,
            HealthEvidenceState.DEGRADED,
            "controller.builtin_unavailable",
        )
    if controller.builtin_available is not True or not controller.builtin_input_verified:
        return HealthComponentObservation(
            HealthComponent.CONTROLLER,
            HealthEvidenceState.UNKNOWN,
            "controller.builtin_input_unverified",
        )
    return HealthComponentObservation(
        HealthComponent.CONTROLLER,
        HealthEvidenceState.READY,
        "controller.builtin_input_verified",
    )


def _audio_component(peripheral: PeripheralObservation) -> HealthComponentObservation:
    audio = peripheral.audio
    if not audio.complete or not audio.exact:
        return HealthComponentObservation(
            HealthComponent.AUDIO,
            HealthEvidenceState.UNKNOWN,
            audio.failure_code or "audio.observation_incomplete",
        )
    if not audio.current_output_usable_verified:
        return HealthComponentObservation(
            HealthComponent.AUDIO,
            HealthEvidenceState.UNKNOWN,
            "audio.current_output_unverified",
        )
    return HealthComponentObservation(
        HealthComponent.AUDIO,
        HealthEvidenceState.READY,
        "audio.current_output_verified",
    )
