"""Semantic game profiles: what the player's settings *mean*, per mode.

The graphics-profile foundation writes exact key literals. That is the right
level for a writer and the wrong level for a profile: nobody should have to
know that one game spells "high textures" ``sg.TextureQuality=3`` and another
``TextureQuality=High``. This module adds the missing layer.

Three things are kept apart:

* the **configuration format** -- how a file is parsed and rendered
  (``graphics_config_format``, unchanged);
* the **game mapping** -- how one game, at one adapter version, spells each
  semantic setting in that format;
* the **semantic profile** -- what the player gets per mode and preference,
  in words: textures high, shadows medium, 1600x900, 45 FPS.

A profile only becomes a managed write when the mapping can express *every*
setting in it. If a mapping cannot express one -- volumetrics in a generic
Unreal mapping, say -- the whole profile is Advisor, and the player receives
the full recommendation in plain terms instead. Writing the half Re-Gear can
express would leave the game in a combination nobody chose; that rule is the
foundation's and is kept here.

Everything is pure. Nothing here reads a file or knows which game is running.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping

from .graphics_profiles import GraphicsProfile, ManagedKey, SupportTier
from .mode_profiles import ExperienceTarget
from .models import OperatingMode


MAX_FPS = 1000
MAX_DIMENSION = 16384


class Quality(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EPIC = "epic"


class GraphicsSetting(StrEnum):
    TEXTURES = "textures"
    SHADOWS = "shadows"
    EFFECTS = "effects"
    VIEW_DISTANCE = "view_distance"
    POST_PROCESSING = "post_processing"
    ANTI_ALIASING = "anti_aliasing"
    VOLUMETRICS = "volumetrics"


class UpscalingMode(StrEnum):
    OFF = "off"
    #: Not a concrete setting: "let Re-Gear decide". It needs a resolved
    #: performance plan before any mapping can express it.
    AUTO = "auto"
    QUALITY = "quality"
    BALANCED = "balanced"
    PERFORMANCE = "performance"


class ValidationStatus(StrEnum):
    """How much evidence stands behind a profile document.

    UNVALIDATED profiles are advice at most. FIXTURE is scaffolding for tests
    and is only managed when a caller explicitly opts in. VALIDATED requires
    real, supervised evidence that does not exist for any game yet.
    """

    UNVALIDATED = "unvalidated"
    FIXTURE = "fixture"
    VALIDATED = "validated"


def _fps(value: int | None, name: str) -> None:
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool) or not 0 < value <= MAX_FPS:
        raise ValueError(f"{name} must be a positive frame rate")


@dataclass(frozen=True, slots=True)
class Resolution:
    width: int
    height: int

    def __post_init__(self) -> None:
        for value in (self.width, self.height):
            if not isinstance(value, int) or isinstance(value, bool) or not 0 < value <= MAX_DIMENSION:
                raise ValueError("resolution dimensions must be positive")

    def __str__(self) -> str:
        return f"{self.width}x{self.height}"


@dataclass(frozen=True, slots=True)
class SemanticProfile:
    """One mode-and-preference profile, in the player's vocabulary."""

    graphics: Mapping[GraphicsSetting, Quality] = field(default_factory=dict)
    target_fps: int | None = None
    resolution: Resolution | None = None
    upscaling: UpscalingMode | None = None
    #: The game's own frame cap. Separate from target_fps on purpose: with
    #: frame generation, the game renders fewer real frames than are shown.
    frame_limit: int | None = None

    def __post_init__(self) -> None:
        _fps(self.target_fps, "target FPS")
        _fps(self.frame_limit, "frame limit")
        for setting, quality in self.graphics.items():
            if not isinstance(setting, GraphicsSetting) or not isinstance(quality, Quality):
                raise ValueError("graphics settings map a GraphicsSetting to a Quality")
        object.__setattr__(self, "graphics", dict(self.graphics))

    def recommendations(self) -> tuple[str, ...]:
        """The profile as a player would read it on an Advisor screen."""
        lines: list[str] = []
        if self.target_fps is not None:
            lines.append(f"Target {self.target_fps} FPS")
        if self.resolution is not None:
            lines.append(f"Resolution {self.resolution}")
        for setting in GraphicsSetting:
            quality = self.graphics.get(setting)
            if quality is not None:
                label = setting.value.replace("_", " ").capitalize()
                lines.append(f"{label} {quality.value.capitalize()}")
        if self.upscaling is not None and self.upscaling is not UpscalingMode.OFF:
            lines.append(f"Upscaling {self.upscaling.value.capitalize()}")
        if self.frame_limit is not None:
            lines.append(f"Frame limit {self.frame_limit} FPS")
        return tuple(lines)


@dataclass(frozen=True, slots=True)
class ProfileMetadata:
    """What a profile document was written against. Checked, not just stored."""

    profile_version: int
    adapter_version: int
    tested_game_version: str
    validation: ValidationStatus

    def __post_init__(self) -> None:
        if self.profile_version < 1 or self.adapter_version < 1:
            raise ValueError("profile and adapter versions start at 1")
        if not self.tested_game_version:
            raise ValueError("a profile must name the game version it was tested on")


@dataclass(frozen=True, slots=True)
class GameProfileDocument:
    """Every profile Re-Gear holds for one game, per mode and preference."""

    steam_app_id: str
    mapping_id: str
    metadata: ProfileMetadata
    profiles: Mapping[OperatingMode, Mapping[ExperienceTarget, SemanticProfile]]

    def profile(
        self, mode: OperatingMode, preference: ExperienceTarget
    ) -> SemanticProfile | None:
        return self.profiles.get(mode, {}).get(preference)


@dataclass(frozen=True, slots=True)
class QualityKey:
    """How one semantic setting is spelled by one game."""

    key: ManagedKey
    values: Mapping[Quality, str]

    def __post_init__(self) -> None:
        for literal in self.values.values():
            if not self.key.accepts(literal):
                raise ValueError(f"{self.key.address} cannot hold mapped value {literal!r}")


@dataclass(frozen=True, slots=True)
class GameMapping:
    """One game's translation from semantic settings to its own keys.

    Deliberately separate from the file format: two Unreal games share a
    format and may still disagree on every key and value. A mapping is also
    versioned, because a game patch can keep the file and change the meaning.
    """

    mapping_id: str
    adapter_version: int
    schema_id: str
    config_filename: str
    #: The game's configuration directory, relative to the Proton prefix's
    #: Documents directory or a native install. Per game, never universal.
    relative_dir: str
    quality_keys: Mapping[GraphicsSetting, QualityKey] = field(default_factory=dict)
    resolution_keys: tuple[ManagedKey, ManagedKey] | None = None
    frame_limit_key: ManagedKey | None = None
    #: Render-scale key and its value per concrete upscaling mode, if the game
    #: exposes one. AUTO is never mapped: it must be resolved first.
    upscaling_key: ManagedKey | None = None
    upscaling_values: Mapping[UpscalingMode, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Held as copies so a caller's dict cannot change a validated mapping.
        object.__setattr__(self, "quality_keys", dict(self.quality_keys))
        object.__setattr__(self, "upscaling_values", dict(self.upscaling_values))
        # One address, one meaning. Two settings sharing a key would make
        # translate() keep whichever it wrote last and still call the result
        # complete -- a contradictory profile passing as a managed one.
        addresses = [entry.key.address for entry in self.quality_keys.values()]
        addresses += [
            key.address
            for key in (*(self.resolution_keys or ()), self.frame_limit_key, self.upscaling_key)
            if key is not None
        ]
        duplicates = sorted({address for address in addresses if addresses.count(address) > 1})
        if duplicates:
            raise ValueError("a mapping uses one key for two settings: " + ", ".join(duplicates))
        if UpscalingMode.AUTO in self.upscaling_values:
            raise ValueError("AUTO is a request, not a setting; it cannot be mapped")
        if self.upscaling_values and self.upscaling_key is None:
            raise ValueError("upscaling values need an upscaling key")
        if self.upscaling_key is not None:
            for literal in self.upscaling_values.values():
                if not self.upscaling_key.accepts(literal):
                    raise ValueError("an upscaling value is outside its key's range")

    def managed_keys(self) -> dict[str, ManagedKey]:
        keys = {entry.key.address: entry.key for entry in self.quality_keys.values()}
        for key in (
            *(self.resolution_keys or ()),
            self.frame_limit_key,
            self.upscaling_key,
        ):
            if key is not None:
                keys[key.address] = key
        return keys


@dataclass(frozen=True, slots=True)
class Translation:
    settings: Mapping[str, str]
    unmapped: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.unmapped


def translate(profile: SemanticProfile, mapping: GameMapping) -> Translation:
    """Express a semantic profile in one game's keys, naming what cannot be."""
    settings: dict[str, str] = {}
    unmapped: list[str] = []
    for setting, quality in sorted(profile.graphics.items()):
        entry = mapping.quality_keys.get(setting)
        literal = entry.values.get(quality) if entry is not None else None
        if entry is None or literal is None:
            unmapped.append(f"{setting.value}={quality.value}")
            continue
        settings[entry.key.address] = literal
    if profile.resolution is not None:
        if mapping.resolution_keys is None:
            unmapped.append(f"resolution={profile.resolution}")
        else:
            width_key, height_key = mapping.resolution_keys
            width, height = str(profile.resolution.width), str(profile.resolution.height)
            if width_key.accepts(width) and height_key.accepts(height):
                settings[width_key.address] = width
                settings[height_key.address] = height
            else:
                unmapped.append(f"resolution={profile.resolution}")
    if profile.frame_limit is not None:
        literal = str(profile.frame_limit)
        if mapping.frame_limit_key is None or not mapping.frame_limit_key.accepts(literal):
            unmapped.append(f"frame_limit={profile.frame_limit}")
        else:
            settings[mapping.frame_limit_key.address] = literal
    if profile.upscaling is not None:
        literal = mapping.upscaling_values.get(profile.upscaling)
        if mapping.upscaling_key is None or literal is None:
            # Includes AUTO, which no mapping may express.
            unmapped.append(f"upscaling={profile.upscaling.value}")
        else:
            settings[mapping.upscaling_key.address] = literal
    return Translation(settings, tuple(unmapped))


@dataclass(frozen=True, slots=True)
class SupportDecision:
    """The support level for one game, mode and preference, and why."""

    tier: SupportTier
    reasons: tuple[str, ...]
    recommendations: tuple[str, ...] = ()
    graphics_profile: GraphicsProfile | None = None
    semantic_profile: SemanticProfile | None = None

    @property
    def managed(self) -> bool:
        return self.tier is SupportTier.MANAGED and self.graphics_profile is not None


def decide_support(
    document: GameProfileDocument | None,
    mapping: GameMapping | None,
    mode: OperatingMode,
    preference: ExperienceTarget,
    observed_game_version: str | None,
    allow_fixture_profiles: bool = False,
    profile: SemanticProfile | None = None,
) -> SupportDecision:
    """Level 0, 1 or 2 for this request, and the profile if it is Managed.

    ``profile`` may replace the document's own profile -- that is how a
    resolved performance plan is applied -- but everything else about the
    document still has to hold.
    """
    if document is None:
        return SupportDecision(SupportTier.UNKNOWN, ("no profile exists for this game",))
    semantic = profile or document.profile(mode, preference)
    if semantic is None:
        return SupportDecision(
            SupportTier.UNKNOWN,
            (f"no {preference.value} profile exists for {mode.value}",),
        )
    advice = semantic.recommendations()
    reasons: list[str] = []
    meta = document.metadata
    if mapping is None or mapping.mapping_id != document.mapping_id:
        reasons.append("no validated mapping writes this game's configuration")
    else:
        if mapping.adapter_version != meta.adapter_version:
            reasons.append(
                f"profile targets adapter version {meta.adapter_version}, the "
                f"mapping is version {mapping.adapter_version}"
            )
        translation = translate(semantic, mapping)
        if not translation.complete:
            reasons.append(
                "the mapping cannot express " + ", ".join(translation.unmapped)
            )
    if observed_game_version is None:
        reasons.append("the installed game version is unknown")
    elif observed_game_version != meta.tested_game_version:
        reasons.append(
            f"profile was tested on {meta.tested_game_version}, installed is "
            f"{observed_game_version}"
        )
    if meta.validation is ValidationStatus.UNVALIDATED:
        reasons.append("the profile is not validated")
    elif meta.validation is ValidationStatus.FIXTURE and not allow_fixture_profiles:
        reasons.append("fixture profiles are not managed outside tests")
    if reasons:
        return SupportDecision(
            SupportTier.ADVISOR, tuple(reasons), advice, semantic_profile=semantic
        )
    assert mapping is not None
    translation = translate(semantic, mapping)
    graphics = GraphicsProfile(
        steam_app_id=document.steam_app_id,
        mode=mode,
        config_filename=mapping.config_filename,
        settings=dict(translation.settings),
        profile_version=meta.profile_version,
        schema_id=mapping.schema_id,
    )
    return SupportDecision(
        SupportTier.MANAGED, (), advice, graphics_profile=graphics, semantic_profile=semantic
    )
