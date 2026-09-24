"""A bounded local catalog of semantic game profiles, with their provenance.

A catalog entry is *data only*: which game, which reviewed mapping it targets,
what the player gets per mode and preference, and where that claim came from.
It names no file, path, key or command. How a game spells a setting stays in a
reviewed in-code ``GameMapping``; an entry can only point at one by id. That
keeps a future import format from ever becoming a way to write arbitrary
files.

Provenance is kept apart from validation:

* **source** -- who produced the entry: this device, the community, a
  community review, or a Re-Gear review;
* **validation** -- what evidence stands behind it, and for which modes.

Community entries are candidate evidence, never authority: whatever they
claim, they are admitted as UNVALIDATED, so the engine offers them as advice
and writes nothing. A VALIDATED claim is admitted only from a local or
Re-Gear-reviewed source, only with an evidence id, and only for the modes that
evidence covers; every other mode of the same entry is advice. No real game
has such evidence yet, so in practice this catalog serves fixtures -- which the
engine still manages only behind its explicit test opt-in.

Loading is per file, and a file is named after its game, so a game has at
most one entry. One malformed entry is rejected with its reason and the rest
still load.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from ..domain.game_compatibility import STEAM_APP_ID_RE
from ..domain.mode_profiles import ExperienceTarget
from ..domain.models import OperatingMode
from ..domain.semantic_profiles import (
    GameProfileDocument,
    GraphicsSetting,
    ProfileMetadata,
    InternalRender,
    Quality,
    Resolution,
    SemanticProfile,
    UpscalingMode,
    ValidationStatus,
)


#: Version 2 names game output and internal render separately. A version 1
#: entry is refused, not reinterpreted: its single resolution is ambiguous.
CATALOG_VERSION = 2
MAX_ENTRY_BYTES = 32 * 1024
MAX_ENTRIES = 256
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
ENTRY_NAME_RE = re.compile(r"^[1-9][0-9]{0,9}\.json$")

_ENTRY_FIELDS = {
    "catalog_version",
    "steam_app_id",
    "mapping_id",
    "profile_version",
    "adapter_version",
    "tested_game_version",
    "validation",
    "provenance",
    "profiles",
}
_PROVENANCE_FIELDS = {"source", "evidence_id", "validated_modes"}
_PROFILE_FIELDS = {
    "graphics",
    "target_fps",
    "game_output_resolution",
    "internal_render",
    "upscaling",
    "frame_limit",
}


class ProfileSource(StrEnum):
    LOCAL = "local"
    COMMUNITY = "community"
    COMMUNITY_REVIEWED = "community_reviewed"
    REGEAR_REVIEWED = "regear_reviewed"


#: Sources whose VALIDATED claim may be believed at all.
AUTHORITATIVE_SOURCES = (ProfileSource.LOCAL, ProfileSource.REGEAR_REVIEWED)


@dataclass(frozen=True, slots=True)
class ProfileProvenance:
    source: ProfileSource
    evidence_id: str = ""
    validated_modes: frozenset[OperatingMode] = frozenset()


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    document: GameProfileDocument
    provenance: ProfileProvenance

    def admitted(self, mode: OperatingMode) -> tuple[GameProfileDocument, tuple[str, ...]]:
        """The document as the engine may see it for ``mode``, and why it was limited.

        Admission can only lower a claim, never raise it. The engine then applies
        its own checks -- mapping, adapter and game version, schema, fixture
        opt-in -- to the admitted document, unchanged.
        """
        claimed = self.document.metadata.validation
        if claimed is not ValidationStatus.VALIDATED:
            return self.document, ()
        reasons: list[str] = []
        if self.provenance.source not in AUTHORITATIVE_SOURCES:
            reasons.append(
                f"a {self.provenance.source.value} profile is a candidate, not validated here"
            )
        if not self.provenance.evidence_id:
            reasons.append("the validation claim names no evidence")
        if mode not in self.provenance.validated_modes:
            reasons.append(f"the evidence does not cover {mode.value}")
        if not reasons:
            return self.document, ()
        metadata = dataclasses.replace(
            self.document.metadata, validation=ValidationStatus.UNVALIDATED
        )
        return dataclasses.replace(self.document, metadata=metadata), tuple(reasons)


@dataclass(frozen=True, slots=True)
class CatalogLoad:
    entries: Mapping[str, CatalogEntry]
    rejected: tuple[tuple[str, str], ...] = ()


class CatalogError(ValueError):
    pass


def load_catalog(directory: Path) -> CatalogLoad:
    """Read every entry under ``directory``. Never raises for a bad entry."""
    try:
        names = sorted(
            entry.name for entry in os.scandir(directory) if entry.name.endswith(".json")
        )
    except FileNotFoundError:
        return CatalogLoad({})
    except OSError as error:
        return CatalogLoad({}, (("*", f"catalog is unreadable: {error}"),))
    rejected: list[tuple[str, str]] = []
    if len(names) > MAX_ENTRIES:
        rejected.append(("*", f"catalog holds more than {MAX_ENTRIES} entries; the rest are ignored"))
        names = names[:MAX_ENTRIES]
    entries: dict[str, CatalogEntry] = {}
    for name in names:
        try:
            if not ENTRY_NAME_RE.fullmatch(name):
                raise CatalogError("entry file is not named <steam app id>.json")
            entry = decode_entry(_read(directory / name))
            if f"{entry.document.steam_app_id}.json" != name:
                raise CatalogError("entry file name and app id disagree")
        except CatalogError as error:
            rejected.append((name, str(error)))
            continue
        entries[entry.document.steam_app_id] = entry
    return CatalogLoad(entries, tuple(rejected))


def _read(path: Path) -> Any:
    if path.is_symlink():
        raise CatalogError("entry is a symlink")
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
        with os.fdopen(descriptor, "rb") as source:
            raw = source.read(MAX_ENTRY_BYTES + 1)
    except OSError as error:
        raise CatalogError(f"entry is unreadable: {error}") from error
    if len(raw) > MAX_ENTRY_BYTES:
        raise CatalogError("entry is oversized")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise CatalogError(f"entry is not JSON: {error}") from error


def decode_entry(value: Any) -> CatalogEntry:
    """Strictly decode one entry. Unknown fields are refused, not ignored."""
    try:
        return _decode_entry(value)
    except CatalogError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise CatalogError(f"entry is invalid: {error}") from error


def _fields(value: Any, allowed: set[str], what: str) -> dict:
    if not isinstance(value, dict):
        raise CatalogError(f"{what} is not an object")
    unknown = set(value) - allowed
    if unknown:
        raise CatalogError(f"{what} has unknown fields: {', '.join(sorted(unknown))}")
    return value


def _identifier(value: Any, what: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER_RE.fullmatch(value):
        raise CatalogError(f"{what} is not a plain identifier")
    return value


def _decode_entry(value: Any) -> CatalogEntry:
    entry = _fields(value, _ENTRY_FIELDS, "entry")
    if entry.get("catalog_version") != CATALOG_VERSION:
        raise CatalogError("catalog version is not one this build reads")
    app_id = entry["steam_app_id"]
    if not isinstance(app_id, str) or not STEAM_APP_ID_RE.fullmatch(app_id):
        raise CatalogError("entry needs a Steam app id")
    for name in ("profile_version", "adapter_version"):
        if type(entry[name]) is not int:
            raise CatalogError(f"{name} is not an integer")
    metadata = ProfileMetadata(
        profile_version=entry["profile_version"],
        adapter_version=entry["adapter_version"],
        tested_game_version=_identifier(entry["tested_game_version"], "tested game version"),
        validation=ValidationStatus(entry["validation"]),
    )
    provenance_value = _fields(entry["provenance"], _PROVENANCE_FIELDS, "provenance")
    evidence = provenance_value.get("evidence_id", "")
    if evidence:
        _identifier(evidence, "evidence id")
    modes = provenance_value.get("validated_modes", [])
    if not isinstance(modes, list):
        raise CatalogError("validated modes are not a list")
    provenance = ProfileProvenance(
        ProfileSource(provenance_value["source"]),
        evidence,
        frozenset(_mode(mode) for mode in modes),
    )
    profiles_value = entry["profiles"]
    if not isinstance(profiles_value, dict) or not profiles_value:
        raise CatalogError("an entry needs at least one profile")
    profiles: dict[OperatingMode, dict[ExperienceTarget, SemanticProfile]] = {}
    for mode_name, by_preference in profiles_value.items():
        mode = _mode(mode_name)
        if not isinstance(by_preference, dict) or not by_preference:
            raise CatalogError(f"{mode.value} has no profiles")
        profiles[mode] = {
            ExperienceTarget(preference): _profile(profile)
            for preference, profile in by_preference.items()
        }
    document = GameProfileDocument(
        steam_app_id=app_id,
        mapping_id=_identifier(entry["mapping_id"], "mapping id"),
        metadata=metadata,
        profiles=profiles,
    )
    return CatalogEntry(document, provenance)


def _mode(value: Any) -> OperatingMode:
    mode = OperatingMode(value)
    if mode in (OperatingMode.UNKNOWN, OperatingMode.DEGRADED):
        raise CatalogError("profiles exist only for known, healthy modes")
    return mode


def _profile(value: Any) -> SemanticProfile:
    profile = _fields(value, _PROFILE_FIELDS, "profile")
    graphics_value = profile.get("graphics", {})
    if not isinstance(graphics_value, dict):
        raise CatalogError("graphics is not an object")
    output = _pair(profile.get("game_output_resolution"), "game output resolution")
    internal_value = profile.get("internal_render")
    if isinstance(internal_value, str):
        internal = InternalRender(internal_value)
    else:
        internal = _pair(internal_value, "internal render")
    upscaling = profile.get("upscaling")
    for name in ("target_fps", "frame_limit"):
        if profile.get(name) is not None and type(profile[name]) is not int:
            raise CatalogError(f"{name} is not an integer")
    return SemanticProfile(
        graphics={GraphicsSetting(key): Quality(level) for key, level in graphics_value.items()},
        target_fps=profile.get("target_fps"),
        game_output_resolution=output,
        internal_render=internal,
        upscaling=UpscalingMode(upscaling) if upscaling is not None else None,
        frame_limit=profile.get("frame_limit"),
    )


def _pair(value: Any, what: str) -> Resolution | None:
    if value is None:
        return None
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(type(item) is not int for item in value)
    ):
        raise CatalogError(f"{what} is a [width, height] pair")
    return Resolution(*value)
