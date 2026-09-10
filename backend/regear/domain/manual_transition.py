"""Pure fail-closed planning for one future manual presentation transition."""

from __future__ import annotations

from dataclasses import dataclass

from .control_plane import (
    CapabilitySupport,
    EffectiveCapabilities,
    ExperimentalTransitionPermit,
    PlacementState,
    PlannedStep,
    TransitionBinding,
    TransitionPlan,
    TransitionStepCode,
    WorkflowState,
)
from .inference import infer_placement
from .models import Confidence, DisplayKind, GameState, GpuRole, ObservedSnapshot


@dataclass(frozen=True, slots=True)
class ManualTransitionEvidence:
    observed_generation: str
    host_profile_id: str
    egpu_profile_id: str
    egpu_stable_id: str
    internal_gpu_stable_id: str
    external_gpu_stable_id: str
    internal_display_stable_id: str
    external_display_stable_id: str
    external_display_ready_verified: bool
    egpu_render_ready_verified: bool
    internal_display_ready_verified: bool
    source_recovery_ready_verified: bool
    game_state: GameState

    def __post_init__(self) -> None:
        if not self.observed_generation:
            raise ValueError("manual transition generation is required")

    def binding(self) -> TransitionBinding | None:
        try:
            return TransitionBinding(
                host_profile_id=self.host_profile_id,
                egpu_profile_id=self.egpu_profile_id,
                egpu_stable_id=self.egpu_stable_id,
                internal_gpu_stable_id=self.internal_gpu_stable_id,
                external_gpu_stable_id=self.external_gpu_stable_id,
                internal_display_stable_id=self.internal_display_stable_id,
                external_display_stable_id=self.external_display_stable_id,
            )
        except ValueError:
            return None


@dataclass(frozen=True, slots=True)
class ManualPlanDecision:
    plan: TransitionPlan | None
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if (self.plan is None) == (not self.blockers):
            raise ValueError("manual plan decision requires either a plan or blockers")


def evidence_from_snapshot(
    snapshot: ObservedSnapshot,
    *,
    observed_generation: str,
    capabilities: EffectiveCapabilities,
) -> ManualTransitionEvidence:
    internal_gpus = tuple(
        gpu
        for gpu in snapshot.gpus
        if gpu.role is GpuRole.INTERNAL
        and gpu.present
        and gpu.confidence is Confidence.VERIFIED
    )
    external_gpus = tuple(
        gpu
        for gpu in snapshot.gpus
        if gpu.role is GpuRole.EXTERNAL
        and gpu.present
        and gpu.confidence is Confidence.VERIFIED
    )
    internal_displays = tuple(
        display
        for display in snapshot.displays
        if display.kind is DisplayKind.INTERNAL
        and display.connected is True
        and display.confidence is Confidence.VERIFIED
    )
    external_displays = tuple(
        display
        for display in snapshot.displays
        if display.kind is DisplayKind.EXTERNAL
        and display.connected is True
        and display.edid_ready is True
        and display.confidence is Confidence.VERIFIED
    )
    internal_gpu = internal_gpus[0] if len(internal_gpus) == 1 else None
    external_gpu = external_gpus[0] if len(external_gpus) == 1 else None
    internal_display = internal_displays[0] if len(internal_displays) == 1 else None
    external_display = external_displays[0] if len(external_displays) == 1 else None
    placement = infer_placement(snapshot)
    source_recovery_ready = (
        placement is PlacementState.PORTABLE
        and internal_gpu is not None
        and internal_display is not None
    ) or (
        placement is PlacementState.DOCKED_EGPU
        and external_gpu is not None
        and external_display is not None
    ) or (
        placement is PlacementState.DOCKED_IGPU
        and internal_gpu is not None
        and external_gpu is not None
        and external_display is not None
    )
    egpu_stable_id = external_gpu.stable_id if external_gpu is not None else ""
    return ManualTransitionEvidence(
        observed_generation=observed_generation,
        host_profile_id=(
            snapshot.host_profile
            if snapshot.host_profile == capabilities.host_profile_id
            else ""
        ),
        egpu_profile_id=(
            capabilities.egpu_profile_id if external_gpu is not None else ""
        ),
        egpu_stable_id=egpu_stable_id,
        internal_gpu_stable_id=internal_gpu.stable_id if internal_gpu else "",
        external_gpu_stable_id=egpu_stable_id,
        internal_display_stable_id=(
            internal_display.stable_id if internal_display else ""
        ),
        external_display_stable_id=(
            external_display.stable_id if external_display else ""
        ),
        external_display_ready_verified=external_display is not None,
        egpu_render_ready_verified=external_gpu is not None,
        internal_display_ready_verified=internal_display is not None,
        source_recovery_ready_verified=source_recovery_ready,
        game_state=snapshot.game_state,
    )


def _experimental_permit_matches(
    permit: ExperimentalTransitionPermit | None,
    *,
    plan_id: str,
    target: PlacementState,
    capabilities: EffectiveCapabilities,
    evidence: ManualTransitionEvidence,
) -> bool:
    return bool(
        permit is not None
        and permit.plan_id == plan_id
        and permit.observed_generation == evidence.observed_generation
        and permit.target_placement is target
        and permit.host_profile_id == capabilities.host_profile_id
        and permit.egpu_profile_id == capabilities.egpu_profile_id
        and permit.egpu_stable_id == evidence.egpu_stable_id
    )


def plan_manual_transition(
    *,
    plan_id: str,
    request_id: str,
    current: PlacementState,
    target: PlacementState,
    capabilities: EffectiveCapabilities,
    evidence: ManualTransitionEvidence,
    experimental_permit: ExperimentalTransitionPermit | None = None,
    step_deadline_ms: int = 15_000,
    recovery_deadline_ms: int = 15_000,
) -> ManualPlanDecision:
    if step_deadline_ms <= 0 or recovery_deadline_ms <= 0:
        raise ValueError("manual transition deadlines must be positive")
    blockers: list[str] = []
    if current in {PlacementState.UNKNOWN, PlacementState.DEGRADED}:
        blockers.append("placement.current_unverified")
    if target not in {PlacementState.PORTABLE, PlacementState.DOCKED_EGPU}:
        blockers.append("placement.target_unsupported")
    if current not in {
        PlacementState.PORTABLE,
        PlacementState.DOCKED_IGPU,
        PlacementState.DOCKED_EGPU,
    }:
        blockers.append("placement.path_unsupported")
    if evidence.host_profile_id != capabilities.host_profile_id:
        blockers.append("identity.host_unverified")
    if blockers:
        return ManualPlanDecision(None, tuple(blockers))

    workflow = (
        WorkflowState.CONNECTING
        if target is PlacementState.DOCKED_EGPU
        else WorkflowState.RETURNING_TO_PORTABLE
    )
    if current is target:
        return ManualPlanDecision(
            TransitionPlan(
                plan_id=plan_id,
                request_id=request_id,
                observed_generation=evidence.observed_generation,
                from_placement=current,
                target_placement=target,
                workflow_state=workflow,
                recovery_deadline_ms=recovery_deadline_ms,
            ),
            (),
        )

    experimental = capabilities.display_handoff is CapabilitySupport.EXPERIMENTAL
    if capabilities.display_handoff is not CapabilitySupport.VERIFIED:
        if not (
            experimental
            and _experimental_permit_matches(
                experimental_permit,
                plan_id=plan_id,
                target=target,
                capabilities=capabilities,
                evidence=evidence,
            )
        ):
            blockers.append("capability.display_handoff_unverified")
    if evidence.game_state is GameState.UNKNOWN:
        blockers.append("game.state_unknown")
    elif evidence.game_state is GameState.RUNNING:
        blockers.append("game.running")
    if not evidence.source_recovery_ready_verified:
        blockers.append("recovery.source_unverified")

    if target is PlacementState.DOCKED_EGPU:
        if (
            evidence.egpu_profile_id != capabilities.egpu_profile_id
            or not evidence.egpu_stable_id
        ):
            blockers.append("identity.egpu_unverified")
        if not evidence.external_display_ready_verified:
            blockers.append("display.external_unready")
        if not evidence.egpu_render_ready_verified:
            blockers.append("render.egpu_unready")
        step_code = TransitionStepCode.PRESENTATION_APPLY_DOCKED_EGPU
    else:
        if not evidence.internal_display_ready_verified:
            blockers.append("display.internal_unready")
        step_code = TransitionStepCode.PRESENTATION_RESTORE_PORTABLE

    binding = evidence.binding()
    if binding is None:
        blockers.append("identity.transition_binding_incomplete")

    if blockers:
        return ManualPlanDecision(None, tuple(blockers))
    return ManualPlanDecision(
        TransitionPlan(
            plan_id=plan_id,
            request_id=request_id,
            observed_generation=evidence.observed_generation,
            from_placement=current,
            target_placement=target,
            workflow_state=workflow,
            steps=(
                PlannedStep(
                    step_code,
                    step_deadline_ms,
                    expected_placement=target,
                ),
            ),
            recovery_deadline_ms=recovery_deadline_ms,
            binding=binding,
            experimental=experimental,
            experimental_authorization_id=(
                experimental_permit.permit_id
                if experimental_permit is not None and experimental
                else ""
            ),
        ),
        (),
    )
