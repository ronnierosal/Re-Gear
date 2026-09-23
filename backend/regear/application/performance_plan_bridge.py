"""Pure preview composition into Claude's engine contract; never invokes a writer.

The raw Decision.profile identifies the measured adapter preset, not final game
settings. Engine-facing previews use PerformancePlan to apply the selected base
cap and rendering choices. No preview here is permission to call engine.apply.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ..domain.graphics_game_adapter import GameSettingsAdapter
from ..domain.frame_generation_provider import FrameGenerationProvider
from ..domain.models import GameState
from ..domain.performance_plan import FrameGenerationRef, PerformancePlan
from ..domain.semantic_profiles import Resolution, UpscalingMode
from ..domain.performance_target_resolver import (
    CompatibilityRecord, Decision, PerformanceIntent, PresentationContext,
    ProviderState, ProviderKind, ProfileBinding, RenderMethod, ScalingLocation, resolve,
)
from .performance_launch_plan import LaunchPlan, OriginalLaunch, build_launch_plan, original_plan


@dataclass(frozen=True, slots=True)
class PerformancePreview:
    decision: Decision
    game_plan: PerformancePlan | None
    launch: LaunchPlan
    output_resolution: Resolution | None
    reasons: tuple[str, ...] = ()
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        if self.execution_allowed is not False:
            raise ValueError("performance previews never authorize execution")

    def disable(self) -> PerformancePreview:
        # Also discard the proposed game cap: keeping 30 after disabling 2x
        # would not preserve the player's original settings.
        return PerformancePreview(self.decision, None, self.launch.disable(),
                                  self.output_resolution, ("disabled; original settings retained",))


def preview_performance(
    intent: PerformanceIntent,
    context: PresentationContext,
    game_state: GameState,
    adapter: GameSettingsAdapter | None,
    records: tuple[CompatibilityRecord, ...],
    states: Mapping[str, ProviderState],
    original: OriginalLaunch,
    providers: Mapping[str, FrameGenerationProvider],
    game_upscaler_bindings: Mapping[ProfileBinding, str] | None = None,
) -> PerformancePreview:
    """Resolve and prepare one inert preview. Provider errors discard BOTH plans.

Runtime initialization is deliberately not attempted: the fake provider's plan
method can simulate a preparation exception, not an in-process crash recovery.
"""
    decision = resolve(intent, context, game_state, adapter, records, states)
    record = decision.record
    launch = original_plan(original, decision.outcome, "no provider launch data")

    def declined(reason: str) -> PerformancePreview:
        return PerformancePreview(decision, None,
                                  original_plan(original, decision.outcome, reason),
                                  context.output_resolution, (reason,))

    if record is None:
        return declined("no selected plan; " + "; ".join(decision.reasons))
    if record.render_resolution is None or context.output_resolution is None:
        return declined("render and output resolution evidence required for engine preview")
    scaling = record.upscalers[0] if record.upscalers else None
    if scaling and scaling.location is ScalingLocation.COMPOSITOR:
        return declined("compositor scaling configuration has no agreed provider seam")
    if scaling and (game_upscaler_bindings or {}).get(record.profile) != scaling.provider_id:
        return declined("game adapter has no reviewed mapping for this exact upscaler/profile binding")
    fg = None
    if record.method is RenderMethod.FRAME_GENERATION:
        if record.provider_kind is ProviderKind.EXTERNAL:
            launch = build_launch_plan(decision, original, providers.get(record.provider_id))
            if not launch.changes_anything:
                return declined("provider preparation failed: " + "; ".join(launch.reasons))
        else:
            launch = LaunchPlan(
                original, decision.outcome,
                unresolved=decision.unresolved + (
                    "native_game_fg_mapping: provider reference does not enable a game-owned key",
                ),
            )
        fg = FrameGenerationRef(record.provider_id, decision.multiplier)
    plan = PerformancePlan(
        target_display_fps=decision.achievable_fps,
        base_fps_target=decision.required_stable_base_fps,
        resolution=record.render_resolution,
        upscaling=scaling.mode if scaling else UpscalingMode.OFF,
        frame_generation=fg,
        source=f"{record.record_id}@{record.evidence_revision}",
    )
    return PerformancePreview(decision, plan, launch, context.output_resolution,
                              decision.reasons + launch.unresolved)
