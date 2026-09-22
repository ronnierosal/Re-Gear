"""Semantic mode intent translated into one game's own keys, and the resolver.

Re-Gear's profiles are written in the vocabulary of what a player wants -- the
experience targets in `mode_profiles.py` -- not in a game's key names. A game
adapter is the only thing that knows both, and it holds a *declared* table: the
values it writes are ones its author wrote down for that game and schema.

Nothing here derives, tunes or measures a setting. An adapter that has no entry
for a mode simply does not offer a profile for it, which is how Boosted Handheld
behaves until someone declares one. An empty table is a missing adapter, never a
reason to guess a value, because a guessed "optimal" setting is a claim about
hardware Re-Gear has not measured.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .graphics_profiles import GraphicsProfile, ManagedKey, SUPPORTED_MODES
from .graphics_schema import GameSchema
from .mode_profiles import ExperienceTarget
from .models import OperatingMode


@dataclass(frozen=True, slots=True)
class GameSettingsAdapter:
    """Translate a mode's experience target into one game's owned keys."""

    adapter_id: str
    steam_app_ids: tuple[str, ...]
    config_filename: str
    #: The directory holding the configuration, relative to the Proton prefix's
    #: documents directory or a native game's install directory.
    relative_dir: str
    schema: GameSchema
    owned_keys: Mapping[str, ManagedKey]
    #: Declared, per experience target. Absent target means no profile.
    declared_settings: Mapping[ExperienceTarget, Mapping[str, str]]
    profile_version: int = 1

    def __post_init__(self) -> None:
        if not self.steam_app_ids:
            raise ValueError("a game adapter must name at least one AppID")
        for target, settings in self.declared_settings.items():
            if not isinstance(target, ExperienceTarget):
                raise ValueError("declared settings are keyed by experience target")
            unknown = set(settings) - set(self.owned_keys)
            if unknown:
                raise ValueError(
                    "a game adapter may only declare values for keys it owns: "
                    + ", ".join(sorted(unknown))
                )

    def serves(self, steam_app_id: str) -> bool:
        return steam_app_id in self.steam_app_ids

    def profile_for(
        self, steam_app_id: str, mode: OperatingMode, target: ExperienceTarget
    ) -> GraphicsProfile | None:
        """The profile this adapter declares, or ``None`` if it declares none."""
        if not self.serves(steam_app_id) or mode not in SUPPORTED_MODES:
            return None
        settings = self.declared_settings.get(target)
        if not settings:
            return None
        return GraphicsProfile(
            steam_app_id=steam_app_id,
            mode=mode,
            config_filename=self.config_filename,
            settings=dict(settings),
            profile_version=self.profile_version,
            schema_id=self.schema.schema_id,
        )


@dataclass(frozen=True, slots=True)
class ModePreference:
    """What the player wants in one placement. Supplied, never inferred."""

    mode: OperatingMode
    target: ExperienceTarget


@dataclass(frozen=True, slots=True)
class ResolvedProfile:
    profile: GraphicsProfile | None
    reason: str = ""


class ProfileResolver:
    """Choose the profile for an observed mode, or decline to choose one.

    The observed mode is an input from whoever already owns mode observation.
    This class does not look at hardware, and an unrecognised placement selects
    nothing at all: no profile is safer than the wrong player's profile.
    """

    def __init__(
        self,
        adapters: tuple[GameSettingsAdapter, ...],
        preferences: Mapping[OperatingMode, ExperienceTarget],
    ) -> None:
        self._adapters = adapters
        self._preferences = dict(preferences)

    def adapter_for(self, steam_app_id: str) -> GameSettingsAdapter | None:
        for adapter in self._adapters:
            if adapter.serves(steam_app_id):
                return adapter
        return None

    def resolve(self, steam_app_id: str, observed_mode: OperatingMode) -> ResolvedProfile:
        if observed_mode not in SUPPORTED_MODES:
            return ResolvedProfile(None, f"{observed_mode.value} selects no profile")
        adapter = self.adapter_for(steam_app_id)
        if adapter is None:
            return ResolvedProfile(None, "no game adapter serves this AppID")
        target = self._preferences.get(observed_mode)
        if target is None:
            return ResolvedProfile(None, f"no preference recorded for {observed_mode.value}")
        profile = adapter.profile_for(steam_app_id, observed_mode, target)
        if profile is None:
            return ResolvedProfile(
                None,
                f"{adapter.adapter_id} declares no settings for {target.value} "
                f"in {observed_mode.value}",
            )
        return ResolvedProfile(profile)
