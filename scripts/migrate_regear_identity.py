#!/usr/bin/env python3
"""Inspect or move Re-Gear state identities while every runtime is offline.

This operator tool never stops or starts a service and performs no session or
hardware action. ``apply`` and ``rollback`` refuse while Decky or Gamescope is
active. The operator must establish that supervised offline state separately.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.delivery.identity_migration import (  # noqa: E402
    DirectoryMove,
    IdentityMigration,
    IdentityMigrationError,
    default_moves,
)
from regear.adapters.steamos.gamescope_user import GamescopeUserContext  # noqa: E402
from regear.delivery.gamescope_integration import GamescopeIntegrationStore  # noqa: E402
from regear.delivery.identity_dropin_migration import ManagedDropinMigration  # noqa: E402


JOURNAL = Path("/var/lib/regear/identity-migration-v1.json")
DROPIN_JOURNAL = Path("/var/lib/regear/identity-dropin-migration-v1.json")
COMBINED_JOURNAL = Path("/var/lib/regear/identity-cutover-v1.json")
CONTROL_CONFLICT_JOURNAL = Path("/var/lib/regear/identity-control-conflict-v1.json")
CONTROL_CONFLICT_ARCHIVE = Path("/var/lib/regear/pre-migration-control-v1")
SYSTEMCTL = "/usr/bin/systemctl"
DECK_USER = "deck"
PLUGIN_ROOT = Path("/home/deck/homebrew/plugins/Re-Gear")
CURRENT_GAMESCOPE_STATE = "/home/deck/.local/share/regear"
FORMER_GAMESCOPE_STATE = "/home/deck/.local/share/handheld-dock-mode"
MAX_ENVIRON_BYTES = 1024 * 1024
GAMESCOPE_PROCESS_NAMES = frozenset(("gamescope", "gamescope-wl"))
COMBINED_SCHEMA = 2
CONTROL_CONFLICT_SCHEMA = 1
COMBINED_PHASES = frozenset(
    (
        "prepared",
        "directories_applied",
        "dropin_applied",
        "committed",
        "rolling_back",
        "dropin_rolled_back",
        "rolled_back",
    )
)


def _plugin_loader_state() -> str:
    result = subprocess.run(
        [
            SYSTEMCTL,
            "show",
            "plugin_loader.service",
            "--property=ActiveState",
            "--value",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
        check=False,
    )
    state = result.stdout.strip()
    if result.returncode != 0 or state not in {
        "active",
        "activating",
        "deactivating",
        "inactive",
        "failed",
        "reloading",
    }:
        raise IdentityMigrationError("plugin_loader.service state is unavailable")
    return state


def _active_processes(proc: Path = Path("/proc")) -> tuple[str, ...]:
    active: set[str] = set()
    for entry in proc.iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            comm = (entry / "comm").read_text(encoding="utf-8").strip()
        except (FileNotFoundError, ProcessLookupError):
            continue
        except (PermissionError, OSError) as error:
            raise IdentityMigrationError("process inspection is unavailable") from error
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", "replace"
            )
        except (FileNotFoundError, ProcessLookupError):
            continue
        except (PermissionError, OSError) as error:
            raise IdentityMigrationError("process inspection is unavailable") from error
        if comm in GAMESCOPE_PROCESS_NAMES:
            active.add("gamescope")
        if (
            "/home/deck/homebrew/plugins/Re-Gear/" in command
            or "/home/deck/homebrew/plugins/HandheldDockMode/" in command
        ):
            active.add("regear_backend")
    return tuple(sorted(active))


def _classify_gamescope_environment(environment: dict[str, str]) -> str:
    current = environment.get("REGEAR_STATE_ROOT")
    former = environment.get("HDM_STATE_ROOT")
    if current is not None and former is not None:
        return "ambiguous"
    if former is not None:
        return "former" if former == FORMER_GAMESCOPE_STATE else "unexpected"
    if current is None:
        return "missing"
    return "current" if current == CURRENT_GAMESCOPE_STATE else "unexpected"


def _gamescope_environment_status(proc: Path = Path("/proc")) -> str:
    observations: list[str] = []
    for entry in proc.iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            if (
                (entry / "comm").read_text(encoding="utf-8").strip()
                not in GAMESCOPE_PROCESS_NAMES
            ):
                continue
        except (FileNotFoundError, ProcessLookupError):
            continue
        except (PermissionError, OSError):
            observations.append("unreadable")
            continue
        try:
            data = (entry / "environ").read_bytes()
        except (FileNotFoundError, ProcessLookupError):
            continue
        except (PermissionError, OSError):
            observations.append("unreadable")
            continue
        if len(data) > MAX_ENVIRON_BYTES:
            return "unreadable"
        environment: dict[str, str] = {}
        for item in data.split(b"\0"):
            if not item or b"=" not in item:
                continue
            key, value = item.split(b"=", 1)
            if key in (b"REGEAR_STATE_ROOT", b"HDM_STATE_ROOT"):
                environment[key.decode("ascii")] = value.decode("utf-8", "replace")
        observations.append(_classify_gamescope_environment(environment))
    if not observations:
        return "inactive"
    if len(observations) != 1:
        return "ambiguous"
    return observations[0]


def require_offline() -> None:
    loader_state = _plugin_loader_state()
    if loader_state not in {"inactive", "failed"}:
        raise IdentityMigrationError(
            f"plugin_loader.service must be inactive (observed {loader_state})"
        )
    active = _active_processes()
    if active:
        raise IdentityMigrationError("runtime processes must be stopped: " + ",".join(active))


class CombinedMigrationRecord:
    """Root-owned orchestration record for the two reversible transactions."""

    def __init__(self, path: Path = COMBINED_JOURNAL) -> None:
        self.path = path
        self.lock = path.with_name(path.name + ".lock")

    @contextmanager
    def hold(self):
        self._ensure_parent()
        descriptor = os.open(
            self.lock,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or (
                os.name == "posix"
                and (
                    metadata.st_uid != os.geteuid()
                    or stat.S_IMODE(metadata.st_mode) & 0o022
                )
            ):
                raise IdentityMigrationError("combined migration lock is unsafe")
            if os.name == "posix":
                import fcntl

                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise IdentityMigrationError("combined migration lock is held") from error
            yield
        finally:
            os.close(descriptor)

    def load(self) -> dict[str, object] | None:
        try:
            descriptor = os.open(
                self.path,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            )
        except FileNotFoundError:
            return None
        with os.fdopen(descriptor, "rb") as source:
            metadata = os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode) or (
                os.name == "posix"
                and (
                    metadata.st_uid != os.geteuid()
                    or stat.S_IMODE(metadata.st_mode) & 0o022
                )
            ):
                raise IdentityMigrationError("combined migration journal is unsafe")
            raw = source.read(4097)
        if len(raw) > 4096:
            raise IdentityMigrationError("combined migration journal is oversized")
        try:
            document = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise IdentityMigrationError("combined migration journal is invalid") from error
        self._validate(document)
        return document

    def create(self, *, directories: bool, dropin: bool) -> dict[str, object]:
        document: dict[str, object] = {
            "schema": COMBINED_SCHEMA,
            "operation_id": secrets.token_hex(16),
            "phase": "prepared",
            "directories": directories,
            "dropin": dropin,
            "rollback_directories": None,
            "rollback_dropin": None,
        }
        self.write(document)
        return document

    def write(self, document: dict[str, object]) -> None:
        self._validate(document)
        self._ensure_parent()
        payload = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
        temporary = self.path.with_name(f".{self.path.name}.{secrets.token_hex(8)}")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb") as target:
                target.write(payload)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, self.path)
            if os.name == "posix":
                parent_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _validate(document: object) -> None:
        if not isinstance(document, dict) or set(document) != {
            "schema",
            "operation_id",
            "phase",
            "directories",
            "dropin",
            "rollback_directories",
            "rollback_dropin",
        }:
            raise IdentityMigrationError("combined migration journal shape is invalid")
        operation_id = document["operation_id"]
        rollback_directories = document["rollback_directories"]
        rollback_dropin = document["rollback_dropin"]
        forward = document["phase"] in {
            "prepared",
            "directories_applied",
            "dropin_applied",
            "committed",
        }
        if (
            document["schema"] != COMBINED_SCHEMA
            or document["phase"] not in COMBINED_PHASES
            or type(document["directories"]) is not bool
            or type(document["dropin"]) is not bool
            or (forward and (rollback_directories is not None or rollback_dropin is not None))
            or (
                not forward
                and (
                    type(rollback_directories) is not bool
                    or type(rollback_dropin) is not bool
                )
            )
            or rollback_directories is True and document["directories"] is not True
            or rollback_dropin is True and document["dropin"] is not True
            or not isinstance(operation_id, str)
            or len(operation_id) != 32
            or any(character not in "0123456789abcdef" for character in operation_id)
        ):
            raise IdentityMigrationError("combined migration journal is incompatible")

    def _ensure_parent(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = self.path.parent.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise IdentityMigrationError("combined migration parent is unsafe")
        if os.name == "posix" and (
            metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise IdentityMigrationError(
                "combined migration parent must be authority-owned mode 0700"
            )


class ControlConflictRecord:
    """Journal the one-time preservation of a fresh duplicate control root."""

    def __init__(
        self,
        path: Path = CONTROL_CONFLICT_JOURNAL,
        archive: Path = CONTROL_CONFLICT_ARCHIVE,
    ) -> None:
        self.path = path
        self.archive = archive
        self.lock = path.with_name(path.name + ".lock")

    @contextmanager
    def hold(self):
        parent = self.path.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = parent.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise IdentityMigrationError("control conflict journal parent is unsafe")
        if os.name == "posix" and (
            metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise IdentityMigrationError(
                "control conflict journal parent must be authority-owned mode 0700"
            )
        descriptor = os.open(
            self.lock,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or (
                os.name == "posix"
                and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022)
            ):
                raise IdentityMigrationError("control conflict lock is unsafe")
            if os.name == "posix":
                import fcntl

                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise IdentityMigrationError("control conflict lock is held") from error
            yield
        finally:
            os.close(descriptor)

    def load(self) -> dict[str, object] | None:
        try:
            descriptor = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            return None
        with os.fdopen(descriptor, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or (
                os.name == "posix"
                and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022)
            ):
                raise IdentityMigrationError("control conflict journal is unsafe")
            raw = source.read(16 * 1024 + 1)
        if len(raw) > 16 * 1024:
            raise IdentityMigrationError("control conflict journal is oversized")
        try:
            document = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise IdentityMigrationError("control conflict journal is invalid") from error
        self._validate(document)
        return document

    def create(self, manifest: dict[str, object]) -> dict[str, object]:
        document: dict[str, object] = {
            "schema": CONTROL_CONFLICT_SCHEMA,
            "phase": "prepared",
            "source": str(CONTROL_CONFLICT_ARCHIVE.parent / "control"),
            "archive": str(self.archive),
            "manifest": manifest,
        }
        self.write(document)
        return document

    def write(self, document: dict[str, object]) -> None:
        self._validate(document)
        payload = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
        temporary = self.path.with_name(f".{self.path.name}.{secrets.token_hex(8)}")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb") as target:
                target.write(payload)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, self.path)
            _sync_directory(self.path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def _validate(self, document: object) -> None:
        if not isinstance(document, dict) or set(document) != {
            "schema", "phase", "source", "archive", "manifest"
        }:
            raise IdentityMigrationError("control conflict journal shape is invalid")
        if (
            document["schema"] != CONTROL_CONFLICT_SCHEMA
            or document["phase"] not in {"prepared", "committed"}
            or document["source"] != str(CONTROL_CONFLICT_ARCHIVE.parent / "control")
            or document["archive"] != str(self.archive)
        ):
            raise IdentityMigrationError("control conflict journal is incompatible")
        _validate_fresh_manifest(document["manifest"])


def _sync_directory(path: Path) -> None:
    if os.name == "posix":
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _bounded_file(path: Path, limit: int = 64 * 1024) -> tuple[bytes, os.stat_result]:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise IdentityMigrationError("fresh control file is invalid")
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
    )
    try:
        current = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
            raise IdentityMigrationError("fresh control file changed during inspection")
        data = b""
        while len(data) <= limit:
            chunk = os.read(descriptor, limit + 1 - len(data))
            if not chunk:
                break
            data += chunk
    finally:
        os.close(descriptor)
    if len(data) > limit or len(data) != before.st_size:
        raise IdentityMigrationError("fresh control file changed during inspection")
    return data, before


def _fresh_root_manifest(current: Path) -> tuple[dict[str, object], dict[str, bytes]]:
    root = current.lstat()
    if stat.S_ISLNK(root.st_mode) or not stat.S_ISDIR(root.st_mode):
        raise IdentityMigrationError("fresh control root must be a real directory")
    if os.name == "posix" and (
        root.st_uid != os.geteuid()
        or root.st_gid != os.getegid()
        or stat.S_IMODE(root.st_mode) != 0o700
    ):
        raise IdentityMigrationError("fresh control root metadata is unsafe")
    children = {child.name: child for child in current.iterdir()}
    expected = {"dock-mutation.lock", "whole-dock-claim.lock", "portable-audio.json"}
    if set(children) != expected:
        raise IdentityMigrationError("current control root is not the exact fresh duplicate")
    entries: list[dict[str, object]] = []
    payloads: dict[str, bytes] = {}
    for name in sorted(expected):
        data, info = _bounded_file(children[name])
        payloads[name] = data
        if os.name == "posix" and (
            info.st_uid != os.geteuid()
            or info.st_gid != os.getegid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise IdentityMigrationError("fresh control file metadata is unsafe")
        if name.endswith(".lock") and data:
            raise IdentityMigrationError("fresh control lock is not empty")
        entries.append(
            {
                "name": name,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "device": info.st_dev,
                "inode": info.st_ino,
                "mode": stat.S_IMODE(info.st_mode),
                "uid": info.st_uid,
                "gid": info.st_gid,
            }
        )
    return {
        "root_mode": stat.S_IMODE(root.st_mode),
        "root_uid": root.st_uid,
        "root_gid": root.st_gid,
        "root_device": root.st_dev,
        "root_inode": root.st_ino,
        "entries": entries,
    }, payloads


def _fresh_manifest(current: Path, former: Path) -> dict[str, object]:
    manifest, payloads = _fresh_root_manifest(current)
    former_audio, _ = _bounded_file(former / "portable-audio.json")
    if payloads["portable-audio.json"] != former_audio:
        raise IdentityMigrationError("fresh control audio state differs from former authority")
    return manifest


def _validate_fresh_manifest(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {
        "root_mode", "root_uid", "root_gid", "root_device", "root_inode", "entries"
    }:
        raise IdentityMigrationError("fresh control manifest shape is invalid")
    if any(
        type(value[key]) is not int or value[key] < 0
        for key in ("root_mode", "root_uid", "root_gid", "root_device", "root_inode")
    ):
        raise IdentityMigrationError("fresh control manifest metadata is invalid")
    entries = value["entries"]
    if not isinstance(entries, list) or len(entries) != 3:
        raise IdentityMigrationError("fresh control manifest entries are invalid")
    expected = {"dock-mutation.lock", "whole-dock-claim.lock", "portable-audio.json"}
    names: set[str] = set()
    for item in entries:
        if not isinstance(item, dict) or set(item) != {
            "name", "size", "sha256", "device", "inode", "mode", "uid", "gid"
        }:
            raise IdentityMigrationError("fresh control manifest entry is invalid")
        name, size, digest = item["name"], item["size"], item["sha256"]
        if (
            not isinstance(name, str)
            or type(size) is not int
            or size < 0
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or any(
                type(item[key]) is not int or item[key] < 0
                for key in ("device", "inode", "mode", "uid", "gid")
            )
        ):
            raise IdentityMigrationError("fresh control manifest entry is incompatible")
        names.add(name)
    if names != expected:
        raise IdentityMigrationError("fresh control manifest names are incompatible")


def _manifest_matches(root: Path, former: Path, expected: object) -> bool:
    return _fresh_manifest(root, former) == expected


def require_conflict_resolved_for_apply(
    migration: IdentityMigration,
    record: ControlConflictRecord,
) -> None:
    runtime = next(item for item in migration._moves if item.name == "runtime")
    document = record.load()
    archive_present = record.archive.exists() or record.archive.is_symlink()
    if document is None:
        if archive_present:
            raise IdentityMigrationError(
                "control conflict archive exists without its journal"
            )
        return
    if document["phase"] != "committed":
        raise IdentityMigrationError(
            "control conflict reconciliation is prepared; rerun reconcile-runtime"
        )
    state = migration._location_state(runtime)
    if state.value not in {"old_only", "current_only"}:
        raise IdentityMigrationError("committed control conflict authority is ambiguous")
    authority = runtime.old if state.value == "old_only" else runtime.current
    if not archive_present or not _manifest_matches(
        record.archive, authority, document["manifest"]
    ):
        raise IdentityMigrationError("committed control conflict archive changed")


def reconcile_duplicate_runtime(
    migration: IdentityMigration,
    record: ControlConflictRecord,
) -> dict[str, object]:
    runtime = next(item for item in migration._moves if item.name == "runtime")
    with record.hold(), migration._hold_external_lock(), migration._hold_state_locks():
        document = record.load()
        state = migration._location_state(runtime)
        if document is None:
            if state.value != "both":
                raise IdentityMigrationError("runtime roots are not the expected duplicate pair")
            migration._validate_tree(runtime.old, runtime)
            migration._validate_tree(runtime.current, runtime)
            migration._validate_quiescent_root(runtime.old)
            migration._validate_quiescent_root(runtime.current)
            if record.archive.exists() or record.archive.is_symlink():
                raise IdentityMigrationError("control conflict archive destination is occupied")
            manifest = _fresh_manifest(runtime.current, runtime.old)
            document = record.create(manifest)
        else:
            manifest = document["manifest"]

        if document["phase"] == "committed":
            if state.value != "old_only" or not record.archive.is_dir():
                raise IdentityMigrationError("committed control conflict state diverged")
            if not _manifest_matches(record.archive, runtime.old, manifest):
                raise IdentityMigrationError("preserved control conflict archive changed")
            return document

        if state.value == "both" and not record.archive.exists() and not record.archive.is_symlink():
            migration._validate_tree(runtime.old, runtime)
            migration._validate_tree(runtime.current, runtime)
            migration._validate_quiescent_root(runtime.old)
            migration._validate_quiescent_root(runtime.current)
            if not _manifest_matches(runtime.current, runtime.old, manifest):
                raise IdentityMigrationError("fresh control root changed after journal preparation")
            if runtime.current.lstat().st_dev != record.archive.parent.lstat().st_dev:
                raise IdentityMigrationError("control conflict archive would cross filesystems")
            os.rename(runtime.current, record.archive)
            _sync_directory(record.archive.parent)
            state = migration._location_state(runtime)

        if state.value != "old_only" or not record.archive.is_dir():
            raise IdentityMigrationError("prepared control conflict state is ambiguous")
        if not _manifest_matches(record.archive, runtime.old, manifest):
            raise IdentityMigrationError("preserved control conflict archive changed")
        document["phase"] = "committed"
        record.write(document)
        return document


def build_migration() -> IdentityMigration:
    if sys.platform != "linux" or os.geteuid() != 0:
        raise IdentityMigrationError("identity migration requires Linux root")
    import pwd

    account = pwd.getpwnam(DECK_USER)
    home = Path(account.pw_dir)
    if home != Path("/home/deck") or account.pw_uid <= 0:
        raise IdentityMigrationError("fixed Decky user identity is unavailable")
    return IdentityMigration(default_moves(home, user_uid=account.pw_uid), JOURNAL)


def build_dropin_migration() -> ManagedDropinMigration:
    if sys.platform != "linux" or os.geteuid() != 0:
        raise IdentityMigrationError("identity migration requires Linux root")
    import pwd

    account = pwd.getpwnam(DECK_USER)
    home = Path(account.pw_dir)
    if home != Path("/home/deck") or account.pw_uid <= 0 or account.pw_gid <= 0:
        raise IdentityMigrationError("fixed Decky user identity is unavailable")
    user = GamescopeUserContext(
        DECK_USER,
        account.pw_uid,
        account.pw_gid,
        home,
        Path("/run/user") / str(account.pw_uid),
        Path("/run/user") / str(account.pw_uid) / "bus",
    )
    store = GamescopeIntegrationStore(
        plugin_root=PLUGIN_ROOT,
        user=user,
        effective_uid=os.geteuid,
        set_owner=os.chown,
    )
    return ManagedDropinMigration(store, DROPIN_JOURNAL)


def _preflight_directories(migration: IdentityMigration) -> bool:
    """Run the directory transaction's complete admission without mutation."""
    document = migration._load_journal()
    if document is None:
        states = {
            item.name: migration._location_state(item) for item in migration._moves
        }
        migration._reject_ambiguous(states)
        planned = tuple(
            item
            for item in migration._moves
            if states[item.name].value == "old_only"
        )
        migration._validate_present_roots()
        with migration._hold_state_locks():
            migration._validate_present_roots()
            migration._validate_quiescent()
            for item in planned:
                migration._validate_move(item, item.old)
        return bool(planned)

    migration._validate_document_paths(document)
    if document["phase"] in ("rolling_back", "rolled_back"):
        raise IdentityMigrationError("migration journal records rollback; apply is refused")
    migration._validate_present_roots()
    if document["phase"] == "committed":
        migration._validate_completed(document)
        return True
    with migration._hold_state_locks():
        migration._validate_present_roots()
        migration._validate_quiescent()
        completed = set(document["completed"])
        for item in migration._journal_moves(document):
            state = migration._location_state(item)
            if item.name in completed and state.value != "current_only":
                raise IdentityMigrationError(
                    "migration journal is ahead of directory state"
                )
            if item.name not in completed and state.value == "old_only":
                migration._validate_move(item, item.old)
            elif item.name not in completed and state.value != "current_only":
                raise IdentityMigrationError(
                    f"{item.name} directory state is ambiguous during apply"
                )
    return True


def apply_combined(
    migration: IdentityMigration,
    dropin: ManagedDropinMigration,
    record: CombinedMigrationRecord,
    conflict: ControlConflictRecord | None = None,
) -> tuple[object, dict[str, str | None]]:
    """Preflight both components, then apply under a resumable owner record."""
    with record.hold():
        if conflict is not None:
            require_conflict_resolved_for_apply(migration, conflict)
        document = record.load()
        directories = _preflight_directories(migration)
        dropin_participates = dropin.preflight_apply()
        if document is None:
            if not directories and not dropin_participates:
                return migration.inspect(), dropin.inspect()
            document = record.create(
                directories=directories, dropin=dropin_participates
            )
        else:
            if document["phase"] in ("rolling_back", "dropin_rolled_back", "rolled_back"):
                raise IdentityMigrationError(
                    "combined migration journal records rollback; apply is refused"
                )
            if bool(document["directories"]) != directories:
                raise IdentityMigrationError(
                    "combined migration directory participation changed"
                )
            if bool(document["dropin"]) != dropin_participates:
                raise IdentityMigrationError(
                    "combined migration drop-in participation changed"
                )
            if document["phase"] == "committed":
                return migration.inspect(), dropin.inspect()

        if document["directories"]:
            status = migration.apply()
        else:
            status = migration.inspect()
        document["phase"] = "directories_applied"
        record.write(document)

        if document["dropin"]:
            dropin_status = dropin.apply()
        else:
            dropin_status = dropin.inspect()
        document["phase"] = "dropin_applied"
        record.write(document)
        document["phase"] = "committed"
        record.write(document)
        return status, dropin_status


def rollback_combined(
    migration: IdentityMigration,
    dropin: ManagedDropinMigration,
    record: CombinedMigrationRecord,
) -> tuple[object, dict[str, str | None]]:
    """Rollback exactly the subtransactions recorded as participants.

    A missing combined record is accepted only as recovery for builds that could
    commit a subtransaction before the orchestrator existed.  The discovered
    subjournals are first captured in the new record, so that recovery itself is
    resumable and directory rollback is never gated on a missing drop-in journal.
    """
    with record.hold():
        document = record.load()
        if document is None:
            directory_participates = migration.inspect().journal_phase is not None
            dropin_participates = dropin.inspect()["journal_phase"] is not None
            if not directory_participates and not dropin_participates:
                raise IdentityMigrationError("no identity migration journal exists")
            document = record.create(
                directories=directory_participates, dropin=dropin_participates
            )
            document["phase"] = "committed"
            record.write(document)
        if document["phase"] == "rolled_back":
            return migration.inspect(), dropin.inspect()

        starting_phase = str(document["phase"])
        if starting_phase not in {"rolling_back", "dropin_rolled_back"}:
            directory_journal = migration.inspect().journal_phase
            dropin_journal = dropin.inspect()["journal_phase"]
            if (
                document["directories"]
                and directory_journal is None
                and starting_phase != "prepared"
            ):
                raise IdentityMigrationError(
                    "combined migration lost its directory journal"
                )
            if (
                document["dropin"]
                and dropin_journal is None
                and starting_phase not in {"prepared", "directories_applied"}
            ):
                raise IdentityMigrationError(
                    "combined migration lost its drop-in journal"
                )
            document["rollback_directories"] = bool(
                document["directories"] and directory_journal is not None
            )
            document["rollback_dropin"] = bool(
                document["dropin"] and dropin_journal is not None
            )
            document["phase"] = "rolling_back"
            record.write(document)

        if document["phase"] == "dropin_rolled_back":
            dropin_status = dropin.inspect()
        else:
            if document["rollback_dropin"]:
                dropin_status = dropin.rollback()
            else:
                dropin_status = dropin.inspect()
            document["phase"] = "dropin_rolled_back"
            record.write(document)

        if document["rollback_directories"]:
            status = migration.rollback()
        else:
            status = migration.inspect()
        document["phase"] = "rolled_back"
        record.write(document)
        return status, dropin_status


def _status_payload(
    migration: IdentityMigration,
    dropin: ManagedDropinMigration,
    combined: CombinedMigrationRecord,
) -> dict[str, object]:
    status = migration.inspect()
    combined_document = combined.load()
    conflict = ControlConflictRecord().load()
    return {
        "state": "observed",
        "locations": {name: value.value for name, value in status.locations},
        "journal_phase": status.journal_phase,
        "combined_journal_phase": (
            None if combined_document is None else combined_document["phase"]
        ),
        "control_conflict_phase": None if conflict is None else conflict["phase"],
        "gamescope_dropin": dropin.inspect(),
        "gamescope_environment": _gamescope_environment_status(),
        "hardware_write": False,
        "service_write": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("status", "reconcile-runtime", "apply", "rollback")
    )
    args = parser.parse_args()
    try:
        migration = build_migration()
        dropin = build_dropin_migration()
        combined = CombinedMigrationRecord()
        if args.command == "status":
            result = _status_payload(migration, dropin, combined)
        else:
            require_offline()
            if args.command == "reconcile-runtime":
                document = reconcile_duplicate_runtime(
                    migration, ControlConflictRecord()
                )
                result = {
                    "state": document["phase"],
                    "control_conflict_archive": document["archive"],
                    "hardware_write": False,
                    "service_write": False,
                }
                print(json.dumps(result, sort_keys=True, separators=(",", ":")))
                return 0
            if args.command == "apply":
                status, dropin_status = apply_combined(
                    migration, dropin, combined, ControlConflictRecord()
                )
            else:
                status, dropin_status = rollback_combined(
                    migration, dropin, combined
                )
            result = {
                "state": status.journal_phase or "unchanged",
                "locations": {name: value.value for name, value in status.locations},
                "gamescope_dropin": dropin_status,
                "hardware_write": False,
                "service_write": False,
            }
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (IdentityMigrationError, KeyError, OSError, subprocess.SubprocessError) as error:
        print(
            json.dumps(
                {
                    "state": "refused",
                    "reason": str(error),
                    "hardware_write": False,
                    "service_write": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
