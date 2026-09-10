"""Pure player-intent mode profiles; they do not authorize configuration changes.

Mode profiles deliberately describe desired experience separately from observed
placement. A profile is never evidence that a display is active, a game is
using a particular renderer, or a device capability has been verified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .models import OperatingMode


class DisplayPreference(StrEnum):
    INTERNAL = "internal"
    EXTERNAL = "external"
    PRESERVE_CURRENT = "preserve_current"


class FeaturePreference(StrEnum):
    PREFER = "prefer"
    AVOID = "avoid"
    PRESERVE_CURRENT = "preserve_current"


class ExperienceTarget(StrEnum):
    BATTERY = "battery"
    BALANCED = "balanced"
    SMOOTH_60 = "smooth_60"
    QUALITY = "quality"
    PERFORMANCE = "performance"


@dataclass(frozen=True, slots=True)
class DisplayModePreference:
    """A desired physical display mode, not an output-selection command."""

    target: DisplayPreference
    width: int | None = None
    height: int | None = None
    refresh_hz: int | None = None
    hdr: FeaturePreference = FeaturePreference.PRESERVE_CURRENT
    vrr: FeaturePreference = FeaturePreference.PRESERVE_CURRENT

    def __post_init__(self) -> None:
        dimensions = (self.width, self.height)
        if any(value is not None and value <= 0 for value in dimensions):
            raise ValueError("display dimensions must be positive")
        if any(value is None for value in dimensions) and any(
            value is not None for value in dimensions
        ):
            raise ValueError("display width and height must be provided together")
        if self.refresh_hz is not None and self.refresh_hz <= 0:
            raise ValueError("display refresh must be positive")


@dataclass(frozen=True, slots=True)
class GameRenderTarget:
    """Game-side intent kept independent from the physical display mode."""

    width: int | None = None
    height: int | None = None
    target_fps: int | None = None

    def __post_init__(self) -> None:
        dimensions = (self.width, self.height)
        if any(value is not None and value <= 0 for value in dimensions):
            raise ValueError("game render dimensions must be positive")
        if any(value is None for value in dimensions) and any(
            value is not None for value in dimensions
        ):
            raise ValueError("game render width and height must be provided together")
        if self.target_fps is not None and self.target_fps <= 0:
            raise ValueError("game target FPS must be positive")


@dataclass(frozen=True, slots=True)
class ModeProfile:
    """One named set of preferences for a stable high-level operating mode."""

    profile_id: str
    mode: OperatingMode
    display: DisplayModePreference
    game_render: GameRenderTarget = field(default_factory=GameRenderTarget)
    experience_target: ExperienceTarget = ExperienceTarget.BALANCED

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise ValueError("mode profile ID is required")
        if self.mode not in {
            OperatingMode.PORTABLE,
            OperatingMode.BOOSTED_HANDHELD,
            OperatingMode.TV_DOCKED,
        }:
            raise ValueError("mode profiles require a stable operating mode")


@dataclass(frozen=True, slots=True)
class ModeProfileSet:
    """A local preference set. It owns no capability or transition authority."""

    profiles: tuple[ModeProfile, ...]

    def __post_init__(self) -> None:
        if not self.profiles:
            raise ValueError("at least one mode profile is required")
        profile_ids = tuple(profile.profile_id for profile in self.profiles)
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("mode profile IDs must be unique")
        modes = tuple(profile.mode for profile in self.profiles)
        if len(modes) != len(set(modes)):
            raise ValueError("one mode profile is allowed per operating mode")


@dataclass(frozen=True, slots=True)
class ModeProfileResolution:
    """A non-authorizing lookup result for presentation or future planning."""

    profile: ModeProfile | None
    reason: str

    @property
    def available(self) -> bool:
        return self.profile is not None


def resolve_mode_profile(
    profiles: ModeProfileSet, observed_mode: OperatingMode
) -> ModeProfileResolution:
    """Return an exact local preference only for stable observed modes.

    Unknown and degraded evidence never receives a fallback profile. Consumers
    must separately establish capabilities and run their own TRY/VERIFY flow;
    this lookup cannot select a display, tune power, or modify a game.
    """
    if observed_mode in {OperatingMode.UNKNOWN, OperatingMode.DEGRADED}:
        return ModeProfileResolution(None, "mode_profile.observed_mode_unstable")
    for profile in profiles.profiles:
        if profile.mode is observed_mode:
            return ModeProfileResolution(profile, "mode_profile.exact_match")
    return ModeProfileResolution(None, "mode_profile.not_configured")
