"""Immutable per-placement Auto TDP intent with exact, non-authorizing lookup.

Preferences are player configuration, not observations, hardware presets, or
evidence that an automatic session may start. Provider bounds and all runtime
admission checks remain independent.
"""

from __future__ import annotations

from dataclasses import dataclass

from .auto_tdp import AutoTdpPolicy
from .control_plane import PlacementState


STABLE_PLACEMENTS = frozenset(
    {
        PlacementState.PORTABLE,
        PlacementState.BOOSTED_HANDHELD,
        PlacementState.DOCKED_IGPU,
        PlacementState.DOCKED_EGPU,
    }
)


@dataclass(frozen=True, slots=True)
class AutoTdpModePreference:
    """One explicit policy for one stable observed placement."""

    placement: PlacementState
    policy: AutoTdpPolicy

    def __post_init__(self) -> None:
        if type(self.placement) is not PlacementState or self.placement not in STABLE_PLACEMENTS:
            raise ValueError("Auto TDP preference requires a stable placement")
        if type(self.policy) is not AutoTdpPolicy:
            raise ValueError("Auto TDP preference requires a validated policy")
        if self.policy.maximum_watts > 0xFFFFFFFF or self.policy.target_fps > 1000:
            raise ValueError("Auto TDP preference exceeds public control bounds")

    @property
    def target_fps(self) -> float:
        return self.policy.target_fps

    @property
    def minimum_watts(self) -> int:
        return self.policy.minimum_watts

    @property
    def maximum_watts(self) -> int:
        return self.policy.maximum_watts


@dataclass(frozen=True, slots=True)
class AutoTdpPreferenceSet:
    preferences: tuple[AutoTdpModePreference, ...]

    def __post_init__(self) -> None:
        if type(self.preferences) is not tuple or not self.preferences:
            raise ValueError("At least one immutable Auto TDP preference is required")
        if any(type(preference) is not AutoTdpModePreference for preference in self.preferences):
            raise ValueError("Auto TDP preference set contains an invalid entry")
        placements = tuple(preference.placement for preference in self.preferences)
        if len(placements) != len(set(placements)):
            raise ValueError("Only one Auto TDP preference is allowed per placement")


@dataclass(frozen=True, slots=True)
class AutoTdpPreferenceResolution:
    preference: AutoTdpModePreference | None
    code: str

    @property
    def available(self) -> bool:
        return self.preference is not None

    @property
    def authorizes_activation(self) -> bool:
        return False


def resolve_auto_tdp_preference(
    preferences: AutoTdpPreferenceSet,
    observed_placement: PlacementState,
) -> AutoTdpPreferenceResolution:
    """Resolve only an exact stable observation; never substitute another mode."""
    if type(preferences) is not AutoTdpPreferenceSet:
        return AutoTdpPreferenceResolution(None, "auto_tdp_preference.set_invalid")
    if type(observed_placement) is not PlacementState:
        return AutoTdpPreferenceResolution(None, "auto_tdp_preference.placement_invalid")
    if observed_placement in (PlacementState.UNKNOWN, PlacementState.DEGRADED):
        return AutoTdpPreferenceResolution(None, "auto_tdp_preference.placement_unresolved")
    for preference in preferences.preferences:
        if preference.placement is observed_placement:
            return AutoTdpPreferenceResolution(preference, "auto_tdp_preference.exact_match")
    return AutoTdpPreferenceResolution(None, "auto_tdp_preference.not_configured")


@dataclass(frozen=True, slots=True)
class AutoTdpProviderBounds:
    """Supplied current provider bounds, not a capability or support claim."""

    minimum_watts: int
    maximum_watts: int

    def __post_init__(self) -> None:
        if any(type(value) is not int or not 0 < value <= 0xFFFFFFFF for value in (self.minimum_watts, self.maximum_watts)):
            raise ValueError("Provider bounds require positive unsigned integer watts")
        if self.minimum_watts > self.maximum_watts:
            raise ValueError("Provider bounds are reversed")


@dataclass(frozen=True, slots=True)
class AutoTdpPreferenceValidation:
    fits_provider_bounds: bool
    code: str

    @property
    def authorizes_activation(self) -> bool:
        return False


def validate_auto_tdp_preference_bounds(
    preference: AutoTdpModePreference,
    bounds: AutoTdpProviderBounds,
) -> AutoTdpPreferenceValidation:
    """Check one range against supplied bounds without granting capability."""
    if type(preference) is not AutoTdpModePreference or type(bounds) is not AutoTdpProviderBounds:
        return AutoTdpPreferenceValidation(False, "auto_tdp_preference.bounds_invalid")
    fits = (
        bounds.minimum_watts <= preference.minimum_watts
        <= preference.maximum_watts <= bounds.maximum_watts
    )
    return AutoTdpPreferenceValidation(
        fits,
        "auto_tdp_preference.within_provider_bounds"
        if fits
        else "auto_tdp_preference.outside_provider_bounds",
    )
