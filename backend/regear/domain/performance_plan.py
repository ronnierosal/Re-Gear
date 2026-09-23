"""The contract between a performance resolver and the Game Profile Engine.

A resolver decides *how* a target is reached: native, upscaled, or with frame
generation. The engine decides *which game settings* that means. This plan is
the entire handover, and it is deliberately small: the engine must work the
same whether a plan came from a finished resolver, a fixture, or nothing.

Frame generation is carried as an opaque reference. The engine never imports,
names, configures or reasons about a provider -- LSFG-VK or any other. It
reads exactly one thing from a plan that uses frame generation: that the game
should render ``base_fps_target`` real frames, which becomes the game's own
frame cap. Everything else about the provider passes through untouched for
whoever launches the game.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from .semantic_profiles import Resolution, SemanticProfile, UpscalingMode


PLAN_VERSION = 1
MAX_FPS = 1000


@dataclass(frozen=True, slots=True)
class FrameGenerationRef:
    """Which provider, at which multiplier. Opaque to the engine."""

    provider_id: str
    multiplier: int

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("a frame-generation reference names its provider")
        if not isinstance(self.multiplier, int) or self.multiplier < 2:
            raise ValueError("a frame-generation multiplier is at least 2")


@dataclass(frozen=True, slots=True)
class PerformancePlan:
    """A resolved way to reach one display target.

    Resolved means concrete: ``AUTO`` upscaling is a request, not a plan, and
    is refused here. The display target and the real-frame target must agree
    with the frame-generation multiplier exactly, so a plan cannot claim 60
    shown frames from 30 real ones without saying how.
    """

    target_display_fps: int
    base_fps_target: int
    resolution: Resolution | None = None
    upscaling: UpscalingMode | None = None
    frame_generation: FrameGenerationRef | None = None
    source: str = ""
    plan_version: int = PLAN_VERSION

    def __post_init__(self) -> None:
        if self.plan_version != PLAN_VERSION:
            raise ValueError("performance plan version is not supported")
        for value, name in (
            (self.target_display_fps, "display target"),
            (self.base_fps_target, "base FPS target"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or not 0 < value <= MAX_FPS:
                raise ValueError(f"{name} must be a positive frame rate")
        if self.upscaling is UpscalingMode.AUTO:
            raise ValueError("a resolved plan names a concrete upscaling mode, not AUTO")
        multiplier = self.frame_generation.multiplier if self.frame_generation else 1
        if self.base_fps_target * multiplier != self.target_display_fps:
            raise ValueError(
                "display target must equal the base target times the "
                "frame-generation multiplier"
            )

    def apply_to(self, profile: SemanticProfile) -> SemanticProfile:
        """The profile with this plan's rendering decisions laid over it.

        Graphics qualities are the profile's; resolution, upscaling and the
        game's frame cap are the plan's where it sets them. The frame cap is
        always the *real* frame target -- with frame generation that is lower
        than what the player will see, which is the whole point.
        """
        return dataclasses.replace(
            profile,
            target_fps=self.target_display_fps,
            frame_limit=self.base_fps_target,
            resolution=self.resolution if self.resolution is not None else profile.resolution,
            upscaling=self.upscaling if self.upscaling is not None else profile.upscaling,
        )
