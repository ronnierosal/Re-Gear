"""Inert emulator-save inventory and byte manifests; no discovery or I/O.

Paths and cloud declarations are supplied metadata, never resolved or verified.
These contracts concern ordinary saves. Save-state compatibility is separate.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum

MAX_FILES = 512
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_UNIT_BYTES = 128 * 1024 * 1024
MAX_TEXT = 1024
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def text(value: object, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if type(value) is not str or not value or len(value) > MAX_TEXT:
        raise ValueError("invalid bounded text")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("control character in metadata")


def token(value: object) -> None:
    if type(value) is not str or TOKEN.fullmatch(value) is None:
        raise ValueError("invalid identity token")


def optional_bool(value: object) -> None:
    if value is not None and type(value) is not bool:
        raise ValueError("invalid evidence boolean")


class SaveUnitKind(StrEnum):
    PS2_WHOLE_CARD = "ps2_whole_card"
    PSP_GAME_DIRECTORY = "psp_game_directory"


class SaveDataKind(StrEnum):
    ORDINARY_SAVE = "ordinary_save"
    SAVE_STATE = "save_state"


@dataclass(frozen=True, slots=True)
class SaveBinding:
    """Stable save unit identity, independent of ROM name and carrier filename."""

    kind: SaveUnitKind
    unit_id: str
    game_ids: tuple[str, ...]
    emulator: str
    emulator_version: str | None
    native_format: str
    format_version: str | None
    data_kind: SaveDataKind = SaveDataKind.ORDINARY_SAVE

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SaveUnitKind) or not isinstance(self.data_kind, SaveDataKind):
            raise ValueError("invalid save kind")
        token(self.unit_id)
        token(self.emulator)
        token(self.native_format)
        text(self.emulator_version, optional=True)
        text(self.format_version, optional=True)
        if type(self.game_ids) is not tuple or len(self.game_ids) > 64:
            raise ValueError("invalid game identities")
        for game_id in self.game_ids:
            token(game_id)
        if len(set(self.game_ids)) != len(self.game_ids):
            raise ValueError("duplicate game identity")
        if self.kind is SaveUnitKind.PSP_GAME_DIRECTORY and self.game_ids != (self.unit_id,):
            raise ValueError("PSP unit must be keyed by its game ID")


@dataclass(frozen=True, slots=True)
class LaunchIdentity:
    source: str | None
    provenance: str | None
    shortcut_app_id: str | None
    emulator_app_id: str | None
    carrier_app_id: str | None

    def __post_init__(self) -> None:
        text(self.source, optional=True)
        text(self.provenance, optional=True)
        for app_id in (self.shortcut_app_id, self.emulator_app_id, self.carrier_app_id):
            if app_id is not None and (
                type(app_id) is not str or re.fullmatch(r"[1-9][0-9]{0,19}", app_id) is None
            ):
                raise ValueError("invalid supplied AppID")


@dataclass(frozen=True, slots=True)
class SavePathEvidence:
    configured: str | None
    canonical_target: str | None
    symlink_targets: tuple[str, ...] = ()
    resolved: bool | None = None
    confined: bool | None = None

    def __post_init__(self) -> None:
        text(self.configured, optional=True)
        text(self.canonical_target, optional=True)
        if type(self.symlink_targets) is not tuple or len(self.symlink_targets) > 16:
            raise ValueError("invalid symlink evidence")
        for target in self.symlink_targets:
            text(target)
        optional_bool(self.resolved)
        optional_bool(self.confined)
        if len(set(self.symlink_targets)) != len(self.symlink_targets):
            raise ValueError("cyclic supplied symlink evidence")


@dataclass(frozen=True, slots=True)
class CloudRuleEvidence:
    """Declaration only. No rule matching, Steam access or coverage assertion."""

    source: str | None
    capture_sha256: str | None
    platform: str | None
    root: str | None
    pattern: str | None
    recursive: bool | None
    quota_bytes: int | None
    matches_save_unit: bool | None

    def __post_init__(self) -> None:
        for value in (self.source, self.platform, self.root, self.pattern):
            text(value, optional=True)
        if self.capture_sha256 is not None and (
            type(self.capture_sha256) is not str or SHA256.fullmatch(self.capture_sha256) is None
        ):
            raise ValueError("invalid cloud-rule capture hash")
        optional_bool(self.recursive)
        optional_bool(self.matches_save_unit)
        if self.quota_bytes is not None and (
            type(self.quota_bytes) is not int or not 0 <= self.quota_bytes <= 2**63 - 1
        ):
            raise ValueError("invalid declared quota")


def relative_save_path(value: object) -> None:
    text(value)
    if (
        value.startswith("/") or "\\" in value or ":" in value
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise ValueError("invalid relative save member")


@dataclass(frozen=True, slots=True)
class SaveMember:
    name: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        relative_save_path(self.name)
        if type(self.size) is not int or not 0 <= self.size <= MAX_FILE_BYTES:
            raise ValueError("invalid save member size")
        if type(self.sha256) is not str or SHA256.fullmatch(self.sha256) is None:
            raise ValueError("invalid save member hash")


def manifest_digest(members: tuple[SaveMember, ...]) -> str:
    """Length-safe canonical tree digest; excludes mtime and transport names."""
    serialized = json.dumps(
        [[member.name, member.size, member.sha256] for member in members],
        ensure_ascii=True, separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("ascii")).hexdigest()


@dataclass(frozen=True, slots=True)
class SaveManifest:
    binding: SaveBinding
    members: tuple[SaveMember, ...]
    complete: bool
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.binding, SaveBinding) or type(self.complete) is not bool:
            raise ValueError("invalid manifest metadata")
        if type(self.members) is not tuple or not 1 <= len(self.members) <= MAX_FILES:
            raise ValueError("invalid manifest member count")
        if any(not isinstance(member, SaveMember) for member in self.members):
            raise ValueError("invalid manifest member")
        names = tuple(member.name for member in self.members)
        if names != tuple(sorted(names)) or len(set(name.casefold() for name in names)) != len(names):
            raise ValueError("manifest names must be sorted and unambiguous")
        if sum(member.size for member in self.members) > MAX_UNIT_BYTES:
            raise ValueError("save unit exceeds byte bound")
        if self.binding.kind is SaveUnitKind.PS2_WHOLE_CARD and names != ("card",):
            raise ValueError("PS2 whole card is exactly one logical card member")
        if self.sha256 != manifest_digest(self.members):
            raise ValueError("corrupt manifest digest")


def build_save_manifest(
    binding: SaveBinding, files: dict[str, bytes], *, complete: bool
) -> SaveManifest:
    """Hash supplied bytes only; logical card name preserves transport neutrality."""
    if type(files) is not dict or not 1 <= len(files) <= MAX_FILES:
        raise ValueError("invalid supplied save files")
    total = 0
    for name, data in files.items():
        relative_save_path(name)
        if type(data) is not bytes or len(data) > MAX_FILE_BYTES:
            raise ValueError("invalid supplied save bytes")
        total += len(data)
        if total > MAX_UNIT_BYTES:
            raise ValueError("save unit exceeds byte bound")
    members = tuple(
        SaveMember(name, len(files[name]), hashlib.sha256(files[name]).hexdigest())
        for name in sorted(files)
    )
    return SaveManifest(binding, members, complete, manifest_digest(members))


@dataclass(frozen=True, slots=True)
class EmulatorSaveInventory:
    binding: SaveBinding
    launch: LaunchIdentity
    paths: SavePathEvidence
    cloud_rule: CloudRuleEvidence
    manifest: SaveManifest
    origin: str = "fixture"

    def __post_init__(self) -> None:
        for value, expected in (
            (self.binding, SaveBinding), (self.launch, LaunchIdentity),
            (self.paths, SavePathEvidence), (self.cloud_rule, CloudRuleEvidence),
            (self.manifest, SaveManifest),
        ):
            if not isinstance(value, expected):
                raise ValueError("invalid inventory contract")
        if self.origin != "fixture" or self.manifest.binding != self.binding:
            raise ValueError("inventory must retain its fixture origin and binding")

    @property
    def unknowns(self) -> tuple[str, ...]:
        reasons = []
        if self.binding.emulator_version is None or self.binding.format_version is None:
            reasons.append("version_unknown")
        if self.launch.source is None or self.launch.provenance is None:
            reasons.append("launch_unknown")
        if self.launch.carrier_app_id is None:
            reasons.append("carrier_app_id_unknown")
        if (
            self.paths.configured is None or self.paths.canonical_target is None
            or self.paths.resolved is not True or self.paths.confined is not True
        ):
            reasons.append("path_target_unverified")
        if (
            self.cloud_rule.source is None or self.cloud_rule.capture_sha256 is None
            or self.cloud_rule.platform is None or self.cloud_rule.root is None
            or self.cloud_rule.pattern is None or self.cloud_rule.recursive is None
            or self.cloud_rule.matches_save_unit is not True
        ):
            reasons.append("cloud_rule_unverified")
        if not self.manifest.complete:
            reasons.append("save_unit_incomplete")
        return tuple(reasons)
