"""Compose a performance decision into an inert, reversible launch plan.

The plan is data. It never runs, never writes Steam launch options, never
touches the game's configuration, and cannot be made to: ``execution_allowed``
is fixed at ``False`` and constructing a plan with it set raises. A decision
whose requirements are unresolved -- a base limiter nobody owns yet, an
injection failure nobody can recover from yet -- therefore never becomes
executable authority, however complete the rest of it looks.

The original launch is opaque. Its launch-options string is carried
byte-for-byte: wrappers, quoting, ``%command%`` and all. It is not parsed,
tokenised or rebuilt, because rebuilding a shell string is how a player's
wrapper gets silently broken. Its environment is copied and never edited;
proposed values live in a separate overlay, and only keys the player did not
already set are proposed at all.

Every failure path -- a refused provider, an unexpected exception, disabling
the plan -- returns the original launch exactly. Launching with the player's
own settings is always the fallback, and the one thing this module guarantees.

What it does *not* solve is recorded rather than implied: an injected Vulkan
layer can fail inside the game process after launch, and removing an overlay
beforehand cannot catch that. That is an unmet production gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from ..domain.frame_generation_provider import FrameGenerationProvider
from ..domain.performance_target_resolver import Decision, Outcome


@dataclass(frozen=True, slots=True)
class OriginalLaunch:
    """The player's launch exactly as supplied. Never parsed, never edited."""

    launch_options: str
    environment: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.launch_options, str):
            raise TypeError("launch options are carried as an opaque string")
        frozen = dict(self.environment)
        for key, value in frozen.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise TypeError("environment keys and values must be strings")
        object.__setattr__(self, "environment", MappingProxyType(frozen))


@dataclass(frozen=True, slots=True)
class LaunchPlan:
    """What a launch would carry. Describes; never executes."""

    original: OriginalLaunch
    outcome: Outcome
    environment_overlay: Mapping[str, str] = field(default_factory=dict)
    provider_id: str | None = None
    provider_revision: str | None = None
    reasons: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        if self.execution_allowed is not False:
            raise ValueError(
                "launch plans are inert in this milestone; execution is never allowed"
            )
        clashes = set(self.environment_overlay) & set(self.original.environment)
        if clashes:
            raise ValueError(
                "an overlay may not replace a variable the player already set: "
                + ", ".join(sorted(clashes))
            )
        object.__setattr__(
            self, "environment_overlay", MappingProxyType(dict(self.environment_overlay))
        )

    @property
    def launch_options(self) -> str:
        """Always the original string, byte-for-byte."""
        return self.original.launch_options

    @property
    def proposed_environment(self) -> Mapping[str, str]:
        """Original environment plus the overlay, for review only."""
        merged = dict(self.original.environment)
        merged.update(self.environment_overlay)
        return MappingProxyType(merged)

    @property
    def changes_anything(self) -> bool:
        return bool(self.environment_overlay)

    def disable(self, reason: str = "disabled") -> "LaunchPlan":
        """Return the original launch exactly, with nothing of Re-Gear's."""
        return original_plan(self.original, self.outcome, reason)


def original_plan(
    original: OriginalLaunch, outcome: Outcome, reason: str
) -> LaunchPlan:
    return LaunchPlan(original=original, outcome=outcome, reasons=(reason,))


def build_launch_plan(
    decision: Decision,
    original: OriginalLaunch,
    provider: FrameGenerationProvider | None,
) -> LaunchPlan:
    """Compose a decision into a plan. Raises nothing; falls back to original.

    Native and upscaled decisions carry no launch overlay: their settings are
    game-owned keys, applied (or not) through the accepted graphics-profile
    service, not through the launch. Only frame generation proposes an
    environment overlay, and only via its provider.
    """
    try:
        if decision.outcome is not Outcome.FRAME_GENERATION:
            return original_plan(
                original,
                decision.outcome,
                "no launch overlay: this decision needs none",
            )
        if provider is None:
            return original_plan(
                original, decision.outcome, "no provider was supplied for this decision"
            )
        configuration = provider.plan(decision, original.environment)
        if not configuration.proposes_anything:
            return original_plan(
                original,
                decision.outcome,
                configuration.refused or "the provider proposed nothing",
            )
        return LaunchPlan(
            original=original,
            outcome=decision.outcome,
            environment_overlay=configuration.environment_overlay,
            provider_id=configuration.provider_id,
            provider_revision=configuration.revision,
            reasons=decision.reasons,
            unresolved=configuration.unresolved,
        )
    except Exception as error:  # noqa: BLE001 - the fallback must survive anything
        return original_plan(
            original,
            decision.outcome,
            f"planning failed, so the original launch is kept exactly: {error!r}",
        )
