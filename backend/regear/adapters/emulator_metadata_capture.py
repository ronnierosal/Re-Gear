"""Explicit metadata inputs only. No discovery, save-content reads or transport.

Native INI/CFG input records only selected configuration declarations. EmuDeck
path descriptions are references, never defaults or proof of this installation:
https://emudeck.github.io/emulators/steamos/ppsspp/
https://emudeck.github.io/emulators/steamos/pcsx2/
Cloud declarations follow the fields described at:
https://partner.steamgames.com/doc/features/cloud
Binary Steam appinfo/shortcuts databases are deliberately unsupported.
"""

from __future__ import annotations

import configparser
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field, fields
from pathlib import Path

from ..domain.emulator_metadata_inventory import (
    CARRIER_APP_ID, MAX_FILES, MAX_FILE_BYTES, MAX_LINK_HOPS, MAX_ROOTS,
    MAX_TOTAL_BYTES, CaptureResult, CloudRuleMetadata, EmulatorMetadata,
    GameMetadata, LaunchMetadata, MetadataError, MetadataInventory, Origin,
    Reason, Role, SaveRootEvidence, SourceEvidence, SteamInstallation, text,
)


@dataclass(frozen=True, slots=True)
class MetadataInput:
    role: Role
    path: str = field(repr=False)

    def __post_init__(self):
        if type(self.role) is not Role:
            raise MetadataError()
        text(self.path)


ALLOWLIST = {
    Role.EMUDECK: {"emudeck-metadata.json"},
    Role.EMULATOR: {"emulator-metadata.json"},
    Role.LAUNCH: {"emulator-launch.json"},
    Role.IDENTITY: {"emulator-game-identity.json"},
    Role.RULES: {"app1118310-cloud-rules.json"},
    Role.INSTALL: {"appmanifest_1118310.acf"},
    Role.CONFIG: {"ppsspp.ini", "PCSX2.ini", "retroarch.cfg"},
    Role.FIXTURE: {"emulator-metadata-fixture.json"},
}


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise MetadataError(Reason.AMBIGUOUS_METADATA)
        result[key] = value
    return result


def _constant(_value):
    raise MetadataError(Reason.MALFORMED_METADATA)


def _decode(data: bytes) -> str:
    if type(data) is not bytes:
        raise MetadataError()
    if len(data) > MAX_FILE_BYTES:
        raise MetadataError(Reason.LIMIT_EXCEEDED)
    failed = False
    try:
        value = data.decode("utf-8")
    except UnicodeError:
        failed = True
    if failed:
        raise MetadataError(Reason.MALFORMED_METADATA)
    if "\x00" in value:
        raise MetadataError(Reason.MALFORMED_METADATA)
    return value


def _json(data: bytes) -> dict:
    content = _decode(data).strip()
    failed = False
    try:
        result = json.loads(content, object_pairs_hook=_object, parse_constant=_constant)
    except (ValueError, RecursionError):
        failed = True
    if failed or type(result) is not dict:
        raise MetadataError(Reason.MALFORMED_METADATA)
    return result


def _construct(cls, value: dict):
    if type(value) is not dict or not set(value) <= {item.name for item in fields(cls)}:
        raise MetadataError(Reason.MALFORMED_METADATA)
    value = dict(value)
    for key in ("game_ids", "selected_slots"):
        if key in value:
            if type(value[key]) is not list:
                raise MetadataError()
            value[key] = tuple(value[key])
    if value.get("root_overrides") is not None:
        rows = value["root_overrides"]
        if type(rows) is not list or any(type(row) is not list for row in rows):
            raise MetadataError()
        value["root_overrides"] = tuple(tuple(row) for row in rows)
    failed = False
    try:
        result = cls(**value)
    except TypeError:
        failed = True
    if failed:
        raise MetadataError(Reason.MALFORMED_METADATA)
    return result


def _manifest(data: bytes) -> dict:
    """Bounded quoted KeyValues reader; appmanifest supplies installation only."""
    content = _decode(data).strip()
    tokens = []
    position = 0
    token = re.compile(r'\s*(?:"((?:[^"\\]|\\["\\])*)"|([{}]))')
    while position < len(content):
        match = token.match(content, position)
        if not match or len(tokens) >= 8192:
            raise MetadataError(Reason.MALFORMED_METADATA)
        value = match.group(1)
        if value is not None:
            if len(value) > 4096:
                raise MetadataError(Reason.LIMIT_EXCEEDED)
            value = re.sub(r'\\(["\\])', r'\1', value)
        tokens.append((value, match.group(2)))
        position = match.end()
    cursor = 0

    def read(depth=0):
        nonlocal cursor
        if depth > 8:
            raise MetadataError(Reason.LIMIT_EXCEEDED)
        result = {}
        while cursor < len(tokens):
            key, marker = tokens[cursor]
            if marker == "}":
                if not depth:
                    raise MetadataError(Reason.MALFORMED_METADATA)
                cursor += 1
                return result
            if key is None or key.casefold() in result:
                raise MetadataError(Reason.MALFORMED_METADATA)
            cursor += 1
            if cursor >= len(tokens):
                raise MetadataError(Reason.MALFORMED_METADATA)
            value, marker = tokens[cursor]
            cursor += 1
            if marker == "{":
                value = read(depth + 1)
            elif value is None:
                raise MetadataError(Reason.MALFORMED_METADATA)
            result[key.casefold()] = value
        if depth:
            raise MetadataError(Reason.MALFORMED_METADATA)
        return result

    result = read()
    if cursor != len(tokens) or set(result) != {"appstate"} or type(result["appstate"]) is not dict:
        raise MetadataError(Reason.MALFORMED_METADATA)
    app = result["appstate"]
    if app.get("appid") != CARRIER_APP_ID:
        raise MetadataError(Reason.MALFORMED_METADATA)
    return {"app_id": app["appid"], "build_id": app.get("buildid"),
            "install_directory": app.get("installdir")}


def _config(data: bytes, filename: str) -> tuple[tuple[str, str], ...]:
    """Configuration declarations only, with no interpretation/execution of paths."""
    content = _decode(data)
    if filename == "retroarch.cfg":
        allowed = {"savefile_directory", "savestate_directory", "libretro_directory"}
        result = {}
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.fullmatch(r'([a-zA-Z0-9_]+)\s*=\s*"([^"\r\n]*)"\s*', line)
            if not match:
                raise MetadataError(Reason.MALFORMED_METADATA)
            key, value = match.groups()
            if key in allowed:
                if key in result:
                    raise MetadataError(Reason.AMBIGUOUS_METADATA)
                text(value)
                result[key] = value
        return tuple(sorted(result.items()))
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    failed = False
    try:
        parser.read_string(content)
    except configparser.Error:
        failed = True
    if failed:
        raise MetadataError(Reason.MALFORMED_METADATA)
    allowed = {"general.memstickdirectory", "folders.memorycards",
               "memorycards.slot1_filename", "memorycards.slot2_filename",
               "memorycards.slot1_enable", "memorycards.slot2_enable"}
    result = {}
    for section in parser.sections():
        for key, value in parser.items(section):
            label = section.casefold() + "." + key.casefold()
            if label in allowed:
                if label in result:
                    raise MetadataError(Reason.AMBIGUOUS_METADATA)
                text(value)
                result[label] = value
    return tuple(sorted(result.items()))


def _assemble(records, origin: Origin, save_roots=()) -> MetadataInventory:
    values = {"origin": origin, "sources": [], "save_roots": tuple(save_roots)}
    seen = set()
    classes = {Role.EMULATOR: ("emulator", EmulatorMetadata), Role.LAUNCH: ("launch", LaunchMetadata),
               Role.IDENTITY: ("game", GameMetadata), Role.INSTALL: ("installation", SteamInstallation),
               Role.RULES: ("rules", CloudRuleMetadata)}
    for role, payload, source in records:
        if role in seen or role is Role.FIXTURE:
            raise MetadataError(Reason.AMBIGUOUS_METADATA)
        seen.add(role)
        values["sources"].append(source)
        if role in classes:
            key, cls = classes[role]
            values[key] = _construct(cls, payload)
        elif role is Role.EMUDECK:
            if type(payload) is not dict or not set(payload) <= {"version", "emulation_root"}:
                raise MetadataError(Reason.MALFORMED_METADATA)
            values["emudeck_version"] = payload.get("version")
            values["emulation_root"] = payload.get("emulation_root")
        elif role is Role.CONFIG:
            values["configuration"] = payload
        else:
            raise MetadataError(Reason.UNSUPPORTED_FILE)
    values["sources"] = tuple(values["sources"])
    return MetadataInventory(**values)


def inventory_from_fixture(data: bytes) -> CaptureResult:
    """Parse synthetic normalized JSON in memory; no caller-controlled origin."""
    try:
        value = _json(data)
        if set(value) != {"schema", "records"} or type(value["schema"]) is not int or value["schema"] != 1:
            raise MetadataError(Reason.MALFORMED_METADATA)
        rows = value["records"]
        if type(rows) is not list or not 1 <= len(rows) <= MAX_FILES:
            raise MetadataError(Reason.LIMIT_EXCEEDED)
        records = []
        for row in rows:
            if type(row) is not dict or set(row) != {"role", "payload"} or type(row["role"]) is not str:
                raise MetadataError(Reason.MALFORMED_METADATA)
            try:
                role = Role(row["role"])
            except ValueError:
                role = None
            if role is None or role in (Role.CONFIG, Role.FIXTURE):
                raise MetadataError(Reason.UNSUPPORTED_FILE)
            payload_bytes = json.dumps(row["payload"], sort_keys=True).encode("utf-8")
            source = SourceEvidence(role, Origin.FIXTURE, hashlib.sha256(payload_bytes).hexdigest(), "fixture")
            records.append((role, row["payload"], source))
        return CaptureResult(inventory=_assemble(records, Origin.FIXTURE))
    except MetadataError as error:
        return CaptureResult(failure=error.reason)


def safe_open_supported() -> bool:
    # Windows reparse-safe descriptor admission is not implemented. Never fall back to Path.read_*.
    return (os.name == "posix" and hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY")
            and os.open in os.supports_dir_fd and os.stat in os.supports_dir_fd
            and os.stat in os.supports_follow_symlinks)


def _absolute(value: str) -> Path:
    text(value)
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or len(path.parts) > 64:
        raise MetadataError(Reason.UNSAFE_PATH)
    return path


def _approved_roots(roots: tuple[str, ...]) -> tuple[Path, ...]:
    if type(roots) is not tuple or not 1 <= len(roots) <= MAX_ROOTS:
        raise MetadataError(Reason.LIMIT_EXCEEDED)
    result = tuple(_absolute(value) for value in roots)
    for index, root in enumerate(result):
        if root == Path(root.anchor):
            raise MetadataError(Reason.UNSAFE_PATH)
        for other in result[:index]:
            if root.is_relative_to(other) or other.is_relative_to(root):
                raise MetadataError(Reason.DUPLICATE_ALIAS)
    return result


def _confined(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path != root and path.is_relative_to(root) for root in roots)


def _signature(value) -> tuple:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
            value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _read_regular(path: Path, aliases: set) -> bytes:
    """POSIX descriptor walk, bounded regular read and post-read name/FD checks."""
    if not safe_open_supported():
        raise MetadataError(Reason.UNSUPPORTED_SAFE_OPEN)
    descriptors = []
    links = []
    directory_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
    error = None
    data = b""
    try:
        parent = os.open(path.anchor, directory_flags)
        descriptors.append(parent)
        for component in path.parts[1:-1]:
            before = os.stat(component, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISDIR(before.st_mode):
                raise MetadataError(Reason.UNSAFE_LINK)
            child = os.open(component, directory_flags, dir_fd=parent)
            descriptors.append(child)
            after = os.fstat(child)
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise MetadataError(Reason.INPUT_CHANGED)
            links.append((parent, component, (after.st_dev, after.st_ino)))
            parent = child
        before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise MetadataError(Reason.UNSAFE_LINK)
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        descriptors.append(descriptor)
        admitted = os.fstat(descriptor)
        if not stat.S_ISREG(admitted.st_mode) or _signature(before) != _signature(admitted):
            raise MetadataError(Reason.INPUT_CHANGED)
        alias = (admitted.st_dev, admitted.st_ino)
        if alias in aliases:
            raise MetadataError(Reason.DUPLICATE_ALIAS)
        aliases.add(alias)
        if admitted.st_size > MAX_FILE_BYTES:
            raise MetadataError(Reason.LIMIT_EXCEEDED)
        pieces = []
        length = 0
        while True:
            piece = os.read(descriptor, min(65536, MAX_FILE_BYTES + 1 - length))
            if not piece:
                break
            pieces.append(piece)
            length += len(piece)
            if length > MAX_FILE_BYTES:
                raise MetadataError(Reason.LIMIT_EXCEEDED)
        if (_signature(admitted) != _signature(os.fstat(descriptor))
                or _signature(admitted) != _signature(os.stat(path.name, dir_fd=parent, follow_symlinks=False))
                or length != admitted.st_size):
            raise MetadataError(Reason.INPUT_CHANGED)
        for ancestor_fd, name, identity in links:
            current = os.stat(name, dir_fd=ancestor_fd, follow_symlinks=False)
            if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != identity:
                raise MetadataError(Reason.INPUT_CHANGED)
        data = b"".join(pieces)
    except MetadataError as caught:
        error = caught.reason
    except OSError:
        error = Reason.READ_UNAVAILABLE
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                error = Reason.READ_UNAVAILABLE
    if error is not None:
        raise MetadataError(error)
    return data


def read_metadata_file(item: MetadataInput, roots: tuple[str, ...], aliases: set | None = None) -> bytes:
    approved = _approved_roots(roots)
    if type(item) is not MetadataInput:
        raise MetadataError()
    path = _absolute(item.path)
    if not _confined(path, approved):
        raise MetadataError(Reason.UNSAFE_PATH)
    if path.name not in ALLOWLIST[item.role]:
        raise MetadataError(Reason.UNSUPPORTED_FILE)
    return _read_regular(path, aliases if aliases is not None else set())


def _save_root_facts(path: Path, roots: tuple[Path, ...]) -> SaveRootEvidence:
    """lstat/readlink only; recorded facts never certify payload safety/completeness."""
    configured = str(path)
    targets = []
    visited = set()
    for _hop in range(MAX_LINK_HOPS):
        if not _confined(path, roots) or path in visited:
            return SaveRootEvidence(configured, tuple(targets), Reason.UNSAFE_LINK)
        visited.add(path)
        # Refuse linked ancestors rather than following an implicit chain.
        for parent in reversed(path.parents):
            info = os.lstat(parent)
            if not stat.S_ISDIR(info.st_mode):
                return SaveRootEvidence(configured, tuple(targets), Reason.UNSAFE_LINK)
        info = os.lstat(path)
        if getattr(info, "st_file_attributes", 0) & 0x400:
            return SaveRootEvidence(configured, tuple(targets), Reason.UNSAFE_LINK)
        if not stat.S_ISLNK(info.st_mode):
            return SaveRootEvidence(configured, tuple(targets))
        target = os.readlink(path)
        text(target)
        targets.append(target)
        if Path(target).is_absolute():
            return SaveRootEvidence(configured, tuple(targets), Reason.UNSAFE_LINK)
        # normpath is lexical only; containment is checked by components next hop.
        path = Path(os.path.normpath(path.parent / target))
    return SaveRootEvidence(configured, tuple(targets), Reason.UNSAFE_LINK)


def _save_root(path: Path, roots: tuple[Path, ...]) -> SaveRootEvidence:
    try:
        return _save_root_facts(path, roots)
    except OSError:
        return SaveRootEvidence(str(path), reason=Reason.READ_UNAVAILABLE)


def capture_metadata(roots: tuple[str, ...], inputs: tuple[MetadataInput, ...],
                     save_roots: tuple[str, ...] = ()) -> CaptureResult:
    try:
        approved = _approved_roots(roots)
        if type(inputs) is not tuple or not 1 <= len(inputs) <= MAX_FILES:
            raise MetadataError(Reason.LIMIT_EXCEEDED)
        if type(save_roots) is not tuple or len(save_roots) > MAX_ROOTS:
            raise MetadataError(Reason.LIMIT_EXCEEDED)
        if any(type(item) is not MetadataInput or item.role is Role.FIXTURE for item in inputs):
            raise MetadataError()
        if len({item.role for item in inputs}) != len(inputs) or len({item.path for item in inputs}) != len(inputs):
            raise MetadataError(Reason.AMBIGUOUS_METADATA)
        if not safe_open_supported():
            raise MetadataError(Reason.UNSUPPORTED_SAFE_OPEN)
        selected_save_roots = tuple(_absolute(value) for value in save_roots)
        if len(set(selected_save_roots)) != len(selected_save_roots):
            raise MetadataError(Reason.DUPLICATE_ALIAS)
        for path in selected_save_roots:
            if not _confined(path, approved):
                raise MetadataError(Reason.UNSAFE_PATH)
        # Admit link facts before metadata reads and exclude every lexical alias.
        evidence = tuple(_save_root(path, approved) for path in selected_save_roots)
        excluded_paths = list(selected_save_roots)
        for item in evidence:
            if item.reason is not Reason.SAVE_PATH_UNVERIFIED:
                raise MetadataError(item.reason)
            alias = Path(item.configured_path)
            for target in item.link_targets:
                alias = Path(os.path.normpath(alias.parent / target))
                excluded_paths.append(alias)
        records = []
        aliases = set()
        total = 0
        for item in inputs:
            metadata_path = _absolute(item.path)
            if any(metadata_path == root or metadata_path.is_relative_to(root) for root in excluded_paths):
                raise MetadataError(Reason.UNSAFE_PATH)
            data = read_metadata_file(item, roots, aliases)
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                raise MetadataError(Reason.LIMIT_EXCEEDED)
            payload = (_manifest(data) if item.role is Role.INSTALL else
                       _config(data, metadata_path.name) if item.role is Role.CONFIG else _json(data))
            source = SourceEvidence(item.role, Origin.LOCAL_METADATA,
                                    hashlib.sha256(data).hexdigest(), item.path)
            records.append((item.role, payload, source))
        return CaptureResult(inventory=_assemble(records, Origin.LOCAL_METADATA, evidence))
    except MetadataError as error:
        return CaptureResult(failure=error.reason)
    except OSError:
        return CaptureResult(failure=Reason.READ_UNAVAILABLE)
