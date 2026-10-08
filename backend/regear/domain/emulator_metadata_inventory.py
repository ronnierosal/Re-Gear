"""Private, immutable metadata evidence; never a save manifest or sync decision."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

MAX_FILES = 16
MAX_FILE_BYTES = 512 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024
MAX_ROOTS = 8
MAX_LINK_HOPS = 16
MAX_TEXT = 4096
PARSER_REVISION = "1"
CARRIER_APP_ID = "1118310"
PSP_DLC_APP_ID = "1234350"


class Reason(StrEnum):
    INVALID_INPUT = "invalid_input"
    LIMIT_EXCEEDED = "limit_exceeded"
    UNSUPPORTED_FILE = "unsupported_file"
    UNSUPPORTED_SAFE_OPEN = "unsupported_safe_open"
    UNSAFE_PATH = "unsafe_path"
    UNSAFE_LINK = "unsafe_link"
    DUPLICATE_ALIAS = "duplicate_alias"
    INPUT_CHANGED = "input_changed"
    READ_UNAVAILABLE = "read_unavailable"
    MALFORMED_METADATA = "malformed_metadata"
    AMBIGUOUS_METADATA = "ambiguous_metadata"
    EMULATOR_UNKNOWN = "emulator_unknown"
    VERSION_UNKNOWN = "version_unknown"
    LAUNCH_UNKNOWN = "launch_unknown"
    GAME_IDENTITY_UNKNOWN = "game_identity_unknown"
    PS2_MEMBERSHIP_UNKNOWN = "ps2_membership_unknown"
    SAVE_PATH_UNVERIFIED = "save_path_unverified"
    SAVE_STATE_SEPARATE = "save_state_separate"
    CLOUD_RULES_UNKNOWN = "cloud_rules_unknown"
    CLOUD_COVERAGE_UNVERIFIED = "cloud_coverage_unverified"


class MetadataError(ValueError):
    """Categorical errors must never include rejected private values."""

    def __init__(self, reason: Reason = Reason.INVALID_INPUT):
        if type(reason) is not Reason:
            reason = Reason.INVALID_INPUT
        self.reason = reason
        super().__init__(reason.value)


class Origin(StrEnum):
    FIXTURE = "fixture"
    LOCAL_METADATA = "local_metadata"


class Role(StrEnum):
    EMUDECK = "emudeck"
    EMULATOR = "emulator"
    CONFIG = "emulator_config"
    LAUNCH = "launch"
    IDENTITY = "identity"
    INSTALL = "steam_install"
    RULES = "cloud_rules"
    FIXTURE = "fixture"


def text(value: object, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if (type(value) is not str or not value or len(value) > MAX_TEXT
            or any(ord(c) < 32 for c in value)):
        raise MetadataError()


def boolean(value: object, *, optional: bool = False) -> None:
    if not (type(value) is bool or (optional and value is None)):
        raise MetadataError()


def app_id(value: object, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if type(value) is not str or not re.fullmatch(r"[1-9][0-9]{0,19}", value):
        raise MetadataError()


def count(value: object, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise MetadataError()


def strings(value: object, maximum: int = 64) -> None:
    if type(value) is not tuple or len(value) > maximum:
        raise MetadataError()
    for item in value:
        text(item)
    if len(set(value)) != len(value):
        raise MetadataError(Reason.AMBIGUOUS_METADATA)


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    role: Role
    origin: Origin
    capture_sha256: str = field(repr=False)
    private_path: str = field(repr=False)
    context: str = field(default="explicit-input", repr=False)
    parser_revision: str = PARSER_REVISION

    def __post_init__(self):
        if type(self.role) is not Role or type(self.origin) is not Origin:
            raise MetadataError()
        if (type(self.capture_sha256) is not str
                or not re.fullmatch(r"[0-9a-f]{64}", self.capture_sha256)):
            raise MetadataError()
        text(self.private_path)
        text(self.context)
        if self.parser_revision != PARSER_REVISION:
            raise MetadataError()


@dataclass(frozen=True, slots=True)
class EmulatorMetadata:
    name: str = field(repr=False)
    distribution: str | None = field(default=None, repr=False)
    version: str | None = field(default=None, repr=False)
    native_format: str | None = field(default=None, repr=False)
    format_version: str | None = field(default=None, repr=False)

    def __post_init__(self):
        text(self.name)
        for value in (self.distribution, self.version, self.native_format, self.format_version):
            text(value, optional=True)


@dataclass(frozen=True, slots=True)
class LaunchMetadata:
    source: str = field(repr=False)
    shortcut_app_id: str | None = field(default=None, repr=False)
    emulator_app_id: str | None = field(default=None, repr=False)
    carrier_app_id: str | None = field(default=None, repr=False)
    dlc_app_id: str | None = field(default=None, repr=False)
    raw_command: str | None = field(default=None, repr=False)

    def __post_init__(self):
        text(self.source)
        for value in (self.shortcut_app_id, self.emulator_app_id, self.carrier_app_id, self.dlc_app_id):
            app_id(value, optional=True)
        text(self.raw_command, optional=True)


@dataclass(frozen=True, slots=True)
class GameMetadata:
    system: str
    unit_kind: str
    unit_id: str = field(repr=False)
    physical_directory: str | None = field(default=None, repr=False)
    game_ids: tuple[str, ...] = field(default=(), repr=False)
    confirmed: bool | None = None
    provenance: str | None = field(default=None, repr=False)
    selected_slots: tuple[str, ...] = field(default=(), repr=False)
    data_kind: str = "ordinary_save"

    def __post_init__(self):
        if type(self.system) is not str or type(self.unit_kind) is not str or self.system not in ("psp", "ps2", "unknown") or self.unit_kind not in (
                "psp_game_directory", "ps2_whole_card", "unknown"):
            raise MetadataError()
        text(self.unit_id)
        text(self.physical_directory, optional=True)
        text(self.provenance, optional=True)
        strings(self.game_ids)
        strings(self.selected_slots, 16)
        boolean(self.confirmed, optional=True)
        if self.data_kind not in ("ordinary_save", "save_state", "unknown"):
            raise MetadataError()
        expected_kind = {"psp": "psp_game_directory", "ps2": "ps2_whole_card"}
        if self.system in expected_kind and self.unit_kind != expected_kind[self.system]:
            raise MetadataError()
        if self.confirmed is True:
            pattern = {"psp": r"[A-Z]{4}[0-9]{5}", "ps2": r"[A-Z]{4}-[0-9]{5}"}.get(self.system)
            if not pattern or not self.provenance or not self.game_ids:
                raise MetadataError()
            if any(not re.fullmatch(pattern, value) for value in self.game_ids):
                raise MetadataError()
            if self.system == "psp" and self.game_ids != (self.unit_id,):
                raise MetadataError()


@dataclass(frozen=True, slots=True)
class SaveRootEvidence:
    configured_path: str = field(repr=False)
    link_targets: tuple[str, ...] = field(default=(), repr=False)
    reason: Reason = Reason.SAVE_PATH_UNVERIFIED

    def __post_init__(self):
        text(self.configured_path)
        strings(self.link_targets, MAX_LINK_HOPS)
        if type(self.reason) is not Reason:
            raise MetadataError()


@dataclass(frozen=True, slots=True)
class SteamInstallation:
    app_id: str
    build_id: str | None = field(default=None, repr=False)
    install_directory: str | None = field(default=None, repr=False)

    def __post_init__(self):
        if self.app_id != CARRIER_APP_ID:
            raise MetadataError()
        for value in (self.build_id, self.install_directory):
            text(value, optional=True)


@dataclass(frozen=True, slots=True)
class CloudRuleMetadata:
    app_id: str
    source_uri: str | None = field(default=None, repr=False)
    source_category: str = "unknown"
    capture_sha256: str | None = field(default=None, repr=False)
    parser_revision: str | None = field(default=None, repr=False)
    freshness: str = "unknown"
    platform: str = "unknown"
    root: str | None = field(default=None, repr=False)
    subdirectory: str | None = field(default=None, repr=False)
    pattern: str | None = field(default=None, repr=False)
    recursive: bool | None = None
    root_overrides: tuple[tuple[str, str, str, str, bool], ...] | None = field(default=None, repr=False)
    byte_quota: int | None = None
    file_quota: int | None = None
    shared_app_id: str | None = field(default=None, repr=False)
    record_complete: bool | None = None

    def __post_init__(self):
        if self.app_id != CARRIER_APP_ID:
            raise MetadataError()
        if self.source_category not in ("publisher_record", "steam_cache", "steamdb", "remote_cache", "unknown"):
            raise MetadataError()
        if self.freshness not in ("current", "stale", "unknown"):
            raise MetadataError()
        if self.platform not in ("linux", "windows", "macos", "unknown"):
            raise MetadataError()
        for value in (self.source_uri, self.parser_revision, self.root, self.subdirectory, self.pattern):
            text(value, optional=True)
        if self.capture_sha256 is not None and (type(self.capture_sha256) is not str
                or not re.fullmatch(r"[0-9a-f]{64}", self.capture_sha256)):
            raise MetadataError()
        boolean(self.recursive, optional=True)
        boolean(self.record_complete, optional=True)
        count(self.byte_quota, optional=True)
        count(self.file_quota, optional=True)
        if self.shared_app_id != "0":
            app_id(self.shared_app_id, optional=True)
        if self.root_overrides is not None:
            if type(self.root_overrides) is not tuple or len(self.root_overrides) > 16:
                raise MetadataError()
            for row in self.root_overrides:
                if type(row) is not tuple or len(row) != 5:
                    raise MetadataError()
                for item in row[:4]:
                    text(item)
                boolean(row[4])

    @property
    def complete_declaration(self) -> bool:
        """Structural completeness only; no authentication or rule verification."""
        return (self.source_category == "publisher_record" and self.freshness == "current"
                and self.platform != "unknown" and self.record_complete is True and all(value is not None for value in (
                    self.source_uri, self.capture_sha256, self.parser_revision, self.root,
                    self.subdirectory, self.pattern, self.recursive, self.root_overrides,
                    self.byte_quota, self.file_quota, self.shared_app_id)))


@dataclass(frozen=True, slots=True)
class MetadataInventory:
    origin: Origin
    sources: tuple[SourceEvidence, ...] = field(default=(), repr=False)
    emulator: EmulatorMetadata | None = field(default=None, repr=False)
    launch: LaunchMetadata | None = field(default=None, repr=False)
    game: GameMetadata | None = field(default=None, repr=False)
    installation: SteamInstallation | None = field(default=None, repr=False)
    rules: CloudRuleMetadata | None = field(default=None, repr=False)
    save_roots: tuple[SaveRootEvidence, ...] = field(default=(), repr=False)
    emudeck_version: str | None = field(default=None, repr=False)
    emulation_root: str | None = field(default=None, repr=False)
    configuration: tuple[tuple[str, str], ...] = field(default=(), repr=False)

    def __post_init__(self):
        if type(self.origin) is not Origin or type(self.sources) is not tuple or len(self.sources) > MAX_FILES:
            raise MetadataError()
        if any(type(item) is not SourceEvidence or item.origin is not self.origin for item in self.sources):
            raise MetadataError()
        if len({item.role for item in self.sources}) != len(self.sources):
            raise MetadataError(Reason.AMBIGUOUS_METADATA)
        for value, expected in ((self.emulator, EmulatorMetadata), (self.launch, LaunchMetadata),
                                (self.game, GameMetadata), (self.installation, SteamInstallation),
                                (self.rules, CloudRuleMetadata)):
            if value is not None and type(value) is not expected:
                raise MetadataError()
        if type(self.save_roots) is not tuple or len(self.save_roots) > MAX_ROOTS:
            raise MetadataError()
        if any(type(item) is not SaveRootEvidence for item in self.save_roots):
            raise MetadataError()
        text(self.emudeck_version, optional=True)
        text(self.emulation_root, optional=True)
        if type(self.configuration) is not tuple or len(self.configuration) > 32:
            raise MetadataError()
        for row in self.configuration:
            if type(row) is not tuple or len(row) != 2:
                raise MetadataError()
            for item in row:
                text(item)
        if len({row[0].casefold() for row in self.configuration}) != len(self.configuration):
            raise MetadataError(Reason.AMBIGUOUS_METADATA)

    @property
    def reasons(self) -> tuple[Reason, ...]:
        # This slice cannot authenticate publisher provenance or verify current UFS rules.
        reasons = [Reason.CLOUD_COVERAGE_UNVERIFIED, Reason.CLOUD_RULES_UNKNOWN]
        if self.emulator is None:
            reasons.append(Reason.EMULATOR_UNKNOWN)
        if self.emulator is None or self.emulator.version is None:
            reasons.append(Reason.VERSION_UNKNOWN)
        if self.launch is None or self.launch.carrier_app_id != CARRIER_APP_ID:
            reasons.append(Reason.LAUNCH_UNKNOWN)
        if self.game is None or self.game.confirmed is not True:
            reasons.append(Reason.GAME_IDENTITY_UNKNOWN)
        if self.game is not None and self.game.system == "ps2" and not self.game.game_ids:
            reasons.append(Reason.PS2_MEMBERSHIP_UNKNOWN)
        if self.game is not None and self.game.data_kind != "ordinary_save":
            reasons.append(Reason.SAVE_STATE_SEPARATE)
        if not self.save_roots:
            reasons.append(Reason.SAVE_PATH_UNVERIFIED)
        reasons.extend(item.reason for item in self.save_roots)
        return tuple(sorted(set(reasons)))


@dataclass(frozen=True, slots=True)
class CaptureResult:
    inventory: MetadataInventory | None = field(default=None, repr=False)
    failure: Reason | None = None

    def __post_init__(self):
        if self.inventory is not None and type(self.inventory) is not MetadataInventory:
            raise MetadataError()
        if self.failure is not None and type(self.failure) is not Reason:
            raise MetadataError()
        if (self.inventory is None) == (self.failure is None):
            raise MetadataError()

    @property
    def exit_code(self) -> int:
        # 0 is help only. All metadata evidence defers actual coverage/readiness.
        if self.failure in (Reason.INVALID_INPUT, Reason.MALFORMED_METADATA, Reason.LIMIT_EXCEEDED):
            return 2
        return 1

    def public_summary(self) -> dict[str, object]:
        inventory = self.inventory
        reasons = inventory.reasons if inventory is not None else (self.failure,)
        versions = []
        for value in (inventory.emudeck_version if inventory else None,
                      inventory.emulator.version if inventory and inventory.emulator else None):
            # Arbitrary version labels can contain private data. Only numeric versions escape.
            if type(value) is str and re.fullmatch(r"[0-9]{1,4}(?:\.[0-9]{1,4}){0,3}", value):
                versions.append(value)
        return {"schema": 1, "status": "invalid" if self.exit_code == 2 else "deferred",
                "reasons": [item.value for item in reasons], "versions": versions,
                "known_records": len(inventory.sources) if inventory else 0,
                "unknown_categories": len(reasons), "cloud_coverage": "unknown",
                "offline_readiness": "unverified"}
