"""The contract between a performance resolver and the Game Profile Engine.

A resolver decides *how* a target is reached: native, upscaled, or with frame
generation. The engine decides *which game settings* that means. This plan is
the entire handover, and it is deliberately small: the engine must work the
same whether a plan came from a finished resolver, a fixture, or nothing.

Version 2 separates what version 1 folded together (primary decision 4fcb4c44):

* **Frame rates.** ``requested_display_fps`` is what the player asked for;
  ``target_display_fps`` is what was selected, and never exceeds it.
  ``base_fps_target`` is how many frames the game renders; the rest of the
  selected rate is generated. Measured presentation belongs to evidence, not
  to a plan, and appears nowhere here. A request for 90 served by a validated
  30 x 2 plan is ``requested=90, target=60, base=30``: the shortfall is kept
  in view rather than rewritten as the player's wish.
* **Resolutions.** Three domains, never inferred from one another:
  ``internal_render`` is what the game shades (a resolution, DYNAMIC, or
  UNKNOWN); ``game_output_resolution`` is the game's swapchain output, which
  the engine writes; ``display_output_resolution`` is the physical
  presentation, read-only context the engine never writes. There is no
  universal "internal <= output" rule: supersampling is legitimate, and any
  limit is the game mapping's to declare.

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

from .semantic_profiles import InternalRender, Resolution, SemanticProfile, UpscalingMode


PLAN_VERSION = 2
#: Plan versions this build can read. Version 1 only through ``from_v1``.
READABLE_PLAN_VERSIONS = (1, 2)
MAX_FPS = 1000


def _fps(value: object, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 < value <= MAX_FPS:
        raise ValueError(f"{name} must be a positive frame rate")


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
    """A resolved way to present one selected frame rate.

    Resolved means concrete: ``AUTO`` upscaling is a request, not a plan, and
    is refused here. The selected rate and the rendered rate must agree with
    the frame-generation multiplier exactly, so a plan cannot claim 60 shown
    frames from 30 real ones without saying how.
    """

    #: What the player asked for. None only for a plan migrated from version
    #: 1, which never recorded it; it is not guessed from the selected rate.
    requested_display_fps: int | None
    #: The selected presentation rate. Never above the request.
    target_display_fps: int
    #: Frames the game renders. The game's own frame cap.
    base_fps_target: int
    game_output_resolution: Resolution | None = None
    internal_render: Resolution | InternalRender = InternalRender.UNKNOWN
    display_output_resolution: Resolution | None = None
    upscaling: UpscalingMode | None = None
    frame_generation: FrameGenerationRef | None = None
    source: str = ""
    plan_version: int = PLAN_VERSION

    def __post_init__(self) -> None:
        if self.plan_version != PLAN_VERSION:
            raise ValueError("performance plan version is not supported; use from_v1 for version 1")
        if self.requested_display_fps is not None:
            _fps(self.requested_display_fps, "requested display rate")
        _fps(self.target_display_fps, "selected display rate")
        _fps(self.base_fps_target, "base FPS target")
        if (
            self.requested_display_fps is not None
            and self.target_display_fps > self.requested_display_fps
        ):
            raise ValueError("a plan never selects more than the player requested")
        for value, name in (
            (self.game_output_resolution, "game output resolution"),
            (self.display_output_resolution, "display output resolution"),
        ):
            if value is not None and not isinstance(value, Resolution):
                raise ValueError(f"{name} is a resolution")
        if not isinstance(self.internal_render, (Resolution, InternalRender)):
            raise ValueError("internal render is a resolution, DYNAMIC or UNKNOWN")
        if self.upscaling is UpscalingMode.AUTO:
            raise ValueError("a resolved plan names a concrete upscaling mode, not AUTO")
        if self.base_fps_target * self.multiplier != self.target_display_fps:
            raise ValueError(
                "the selected display rate must equal the base target times the "
                "frame-generation multiplier"
            )

    @classmethod
    def from_v1(
        cls,
        target_display_fps: int,
        base_fps_target: int,
        resolution: Resolution | None = None,
        upscaling: UpscalingMode | None = None,
        frame_generation: FrameGenerationRef | None = None,
        source: str = "",
    ) -> PerformancePlan:
        """The one deterministic reading of a version 1 plan.

        Version 1 ``resolution`` always meant the game output the engine
        wrote. Internal render stays UNKNOWN even when upscaling is set -- the
        base profile may supply upscaling, so "no upscaling in the plan" never
        proves internal equals output. The request was never recorded, so it
        stays None rather than being copied from the selected rate.
        """
        return cls(
            requested_display_fps=None,
            target_display_fps=target_display_fps,
            base_fps_target=base_fps_target,
            game_output_resolution=resolution,
            upscaling=upscaling,
            frame_generation=frame_generation,
            source=source,
        )

    @property
    def multiplier(self) -> int:
        return self.frame_generation.multiplier if self.frame_generation else 1

    @property
    def generated_fps(self) -> int:
        """Presented frames the game does not render."""
        return self.target_display_fps - self.base_fps_target

    @property
    def is_fallback(self) -> bool:
        """The selected rate is below what the player requested."""
        return (
            self.requested_display_fps is not None
            and self.target_display_fps < self.requested_display_fps
        )

    def explain(self) -> tuple[str, ...]:
        """The plan in a player's terms, shortfalls included."""
        lines: list[str] = []
        if self.is_fallback:
            lines.append(
                f"Requested {self.requested_display_fps} FPS; planned "
                f"{self.target_display_fps} FPS"
            )
        else:
            lines.append(f"Planned {self.target_display_fps} FPS")
        if self.frame_generation is not None:
            lines.append(
                f"{self.base_fps_target} rendered, {self.generated_fps} generated "
                f"(x{self.multiplier})"
            )
        if self.game_output_resolution is not None:
            lines.append(f"Game output {self.game_output_resolution}")
        if isinstance(self.internal_render, Resolution):
            lines.append(f"Internal render {self.internal_render}")
        elif self.internal_render is InternalRender.DYNAMIC:
            lines.append("Internal render dynamic")
        if self.display_output_resolution is not None:
            lines.append(f"Display {self.display_output_resolution}")
        return tuple(lines)

    def apply_to(self, profile: SemanticProfile) -> SemanticProfile:
        """The profile with this plan's rendering decisions laid over it.

        Graphics qualities are the profile's; game output, internal render,
        upscaling and the game's frame cap are the plan's where it states
        them. An UNKNOWN internal render states nothing and leaves the
        profile's own. Display output is never laid over anything: the engine
        does not write it. The frame cap is always the *rendered* rate -- with
        frame generation that is lower than what the player sees.
        """
        internal = profile.internal_render
        if self.internal_render is not InternalRender.UNKNOWN:
            internal = self.internal_render
        return dataclasses.replace(
            profile,
            target_fps=self.target_display_fps,
            frame_limit=self.base_fps_target,
            game_output_resolution=(
                self.game_output_resolution
                if self.game_output_resolution is not None
                else profile.game_output_resolution
            ),
            internal_render=internal,
            upscaling=self.upscaling if self.upscaling is not None else profile.upscaling,
        )
