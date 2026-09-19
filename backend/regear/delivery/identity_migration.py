"""Offline, fail-closed migration of Re-Gear state-directory identities.

This module is the only runtime source allowed to know the retired directory
addresses.  It performs no service or hardware operation.  Callers must stop
the plugin and its helpers before invoking :meth:`IdentityMigration.apply`.

The transaction journal deliberately lives outside every directory being
moved.  Recovery observes the directory names rather than restoring a copied
snapshot, so rollback always moves the current bytes back to their prior name.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable

from .portable_trial_store import PortableTrialStore


CURRENT_RUNTIME_ROOT = Path("/var/lib/regear/control")
LEGACY_RUNTIME_ROOT = Path("/var/lib/handheld-dock-mode")
CURRENT_USER_ROOT = Path("~/.local/share/regear")
LEGACY_USER_ROOT = Path("~/.local/share/handheld-dock-mode")

JOURNAL_SCHEMA = 1
MAX_JOURNAL_BYTES = 16 * 1024
KNOWN_PHASES = frozenset(("prepared", "applying", "committed", "rolling_back", "rolled_back"))

_HARD_BLOCKERS = frozenset((
    "active-transition.json",
    "whole-dock-claim.json",
    "whole-dock-reset.pending",
))
_PORTABLE_TRIAL_MARKERS = frozenset((
    "portable-vulkan-trial.json",
    "portable-vulkan-trial.consumed",
    "portable-vulkan-trial.steam-consumed",
    "portable-vulkan-trial.gamescope-launch",
))


class IdentityMigrationError(RuntimeError):
    """The identity migration cannot proceed without operator reconciliation."""


class LocationState(str, Enum):
    OLD_ONLY = "old_only"
    CURRENT_ONLY = "current_only"
    BOTH = "both"
    NEITHER = "neither"


@dataclass(frozen=True, slots=True)
class DirectoryMove:
    name: str
    old: Path
    current: Path
    allowed_uids: frozenset[int] | None
    root_mode: int = 0o700

    def __post_init__(self) -> None:
        if not self.name or not self.old.is_absolute() or not self.current.is_absolute():
            raise ValueError("identity migration paths must be named and absolute")
        if self.old == self.current or self.old.parent == self.old or self.current.parent == self.current:
            raise ValueError("identity migration paths must be distinct narrow paths")
        if self.allowed_uids is not None and (
            not self.allowed_uids
            or any(type(uid) is not int or uid < 0 for uid in self.allowed_uids)
        ):
            raise ValueError("identity state roots need a nonempty allowed UID set")
        if self.root_mode not in (0o700, 0o755):
            raise ValueError("identity state roots must use a known exact mode")


@dataclass(frozen=True, slots=True)
class MigrationStatus:
    locations: tuple[tuple[str, LocationState], ...]
    journal_phase: str | None

    def state(self, name: str) -> LocationState:
        try:
            return dict(self.locations)[name]
        except KeyError as error:
            raise ValueError("unknown migration location") from error


def default_moves(home: Path, *, user_uid: int) -> tuple[DirectoryMove, ...]:
    """Return the fixed production identities without touching the filesystem."""
    if not home.is_absolute():
        raise ValueError("home must be absolute")
    shared = home / ".local" / "share"
    decky = home / "homebrew"
    user_owned = frozenset((0, user_uid))
    return (
        DirectoryMove("runtime", LEGACY_RUNTIME_ROOT, CURRENT_RUNTIME_ROOT, frozenset((0,))),
        DirectoryMove(
            "user",
            Path(str(LEGACY_USER_ROOT).replace("~", str(home), 1)),
            Path(str(CURRENT_USER_ROOT).replace("~", str(home), 1)),
            user_owned,
            root_mode=0o755,
        ),
        DirectoryMove(
            "decky_settings",
            decky / "settings" / "HandheldDockMode",
            shared / "regear-decky-settings-archive",
            user_owned,
            root_mode=0o755,
        ),
        DirectoryMove(
            "decky_data",
            decky / "data" / "HandheldDockMode",
            shared / "regear-decky-data-archive",
            user_owned,
            root_mode=0o755,
        ),
        DirectoryMove(
            "decky_logs",
            decky / "logs" / "HandheldDockMode",
            shared / "regear-decky-logs-archive",
            user_owned,
            root_mode=0o755,
        ),
    )


class IdentityMigration:
    """Journaled whole-directory renames with crash recovery and rollback."""

    def __init__(
        self,
        moves: Iterable[DirectoryMove],
        journal: Path,
        *,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._moves = tuple(moves)
        if not self._moves or len({item.name for item in self._moves}) != len(self._moves):
            raise ValueError("identity migration needs uniquely named moves")
        endpoints = tuple(path for item in self._moves for path in (item.old, item.current))
        if len(set(endpoints)) != len(endpoints) or any(
            left.is_relative_to(right)
            for left in endpoints
            for right in endpoints
            if left != right
        ):
            raise ValueError("identity migration directory endpoints must not overlap")
        if not journal.is_absolute() or journal.parent == journal:
            raise ValueError("migration journal must be a narrow absolute path")
        for item in self._moves:
            if journal == item.old or journal == item.current or journal.is_relative_to(item.old) or journal.is_relative_to(item.current):
                raise ValueError("migration journal must be outside moved directories")
        self._journal = journal
        self._token_factory = token_factory or (lambda: secrets.token_hex(16))

    def inspect(self) -> MigrationStatus:
        document = self._load_journal()
        return MigrationStatus(
            tuple((item.name, self._location_state(item)) for item in self._moves),
            None if document is None else document["phase"],
        )

    def apply(self) -> MigrationStatus:
        """Start or resume migration; current-only state is idempotent."""
        with self._hold_external_lock():
            return self._apply_locked()

    def _apply_locked(self) -> MigrationStatus:
        document = self._load_journal()
        planned: tuple[DirectoryMove, ...] | None = None
        if document is None:
            states = {item.name: self._location_state(item) for item in self._moves}
            self._reject_ambiguous(states)
            planned = tuple(item for item in self._moves if states[item.name] is LocationState.OLD_ONLY)
            self._validate_present_roots()
            if not planned:
                return self.inspect()
        else:
            self._validate_document_paths(document)
            if document["phase"] == "committed":
                self._validate_present_roots()
                self._validate_completed(document)
                return self.inspect()
            if document["phase"] in ("rolling_back", "rolled_back"):
                raise IdentityMigrationError("migration journal records rollback; apply is refused")
            self._validate_present_roots()

        with self._hold_state_locks():
            # State may have changed while locks were being discovered.  All
            # validation that authorizes a rename is repeated while the locks
            # remain held through journal publication and parent fsync.
            self._validate_present_roots()
            self._validate_quiescent()
            if document is None:
                assert planned is not None
                # Prove every rename stays on one filesystem before publishing
                # a transaction that could later require recovery.
                for item in planned:
                    self._validate_move(item, item.old)
                document = self._new_document(planned)
                self._write_journal(document)
            else:
                completed = set(document["completed"])
                for item in self._journal_moves(document):
                    if item.name in completed and self._location_state(item) is not LocationState.CURRENT_ONLY:
                        raise IdentityMigrationError("migration journal is ahead of directory state")

            document["phase"] = "applying"
            self._write_journal(document)
            for item in self._journal_moves(document):
                state = self._location_state(item)
                if state is LocationState.OLD_ONLY:
                    self._validate_move(item, item.old)
                    os.rename(item.old, item.current)
                    self._sync_directory(item.old.parent)
                    if item.current.parent != item.old.parent:
                        self._sync_directory(item.current.parent)
                elif state is not LocationState.CURRENT_ONLY:
                    raise IdentityMigrationError(f"{item.name} directory state is ambiguous during apply")
                if item.name not in document["completed"]:
                    document["completed"].append(item.name)
                    self._write_journal(document)

            document["phase"] = "committed"
            self._write_journal(document)
            self._validate_completed(document)
            return self.inspect()

    def rollback(self) -> MigrationStatus:
        """Move the live current directories back; never restore stale copies."""
        with self._hold_external_lock():
            return self._rollback_locked()

    def _rollback_locked(self) -> MigrationStatus:
        document = self._load_journal()
        if document is None:
            raise IdentityMigrationError("no migration journal exists")
        self._validate_document_paths(document)
        if document["phase"] == "rolled_back":
            self._validate_present_roots()
            self._validate_rolled_back(document)
            return self.inspect()
        self._validate_present_roots()
        with self._hold_state_locks():
            self._validate_present_roots()
            self._validate_quiescent()
            document["phase"] = "rolling_back"
            self._write_journal(document)
            for item in reversed(self._journal_moves(document)):
                state = self._location_state(item)
                if state is LocationState.CURRENT_ONLY:
                    self._validate_move(item, item.current)
                    os.rename(item.current, item.old)
                    self._sync_directory(item.current.parent)
                    if item.current.parent != item.old.parent:
                        self._sync_directory(item.old.parent)
                elif state is not LocationState.OLD_ONLY:
                    raise IdentityMigrationError(f"{item.name} directory state is ambiguous during rollback")
            document["phase"] = "rolled_back"
            document["completed"] = []
            self._write_journal(document)
            self._validate_rolled_back(document)
            return self.inspect()

    @staticmethod
    def _location_state(item: DirectoryMove) -> LocationState:
        old = item.old.exists() or item.old.is_symlink()
        current = item.current.exists() or item.current.is_symlink()
        if old and current:
            return LocationState.BOTH
        if old:
            return LocationState.OLD_ONLY
        if current:
            return LocationState.CURRENT_ONLY
        return LocationState.NEITHER

    @staticmethod
    def _reject_ambiguous(states: dict[str, LocationState]) -> None:
        both = sorted(name for name, value in states.items() if value is LocationState.BOTH)
        if both:
            raise IdentityMigrationError("old and current roots both exist: " + ", ".join(both))

    def _validate_present_roots(self) -> None:
        states = {item.name: self._location_state(item) for item in self._moves}
        self._reject_ambiguous(states)
        for item in self._moves:
            state = states[item.name]
            if state is LocationState.OLD_ONLY:
                self._validate_tree(item.old, item)
            elif state is LocationState.CURRENT_ONLY:
                self._validate_tree(item.current, item)

    def _validate_tree(self, root: Path, item: DirectoryMove) -> None:
        root_metadata = root.lstat()
        if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
            raise IdentityMigrationError(f"{item.name} root must be a real directory")
        self._validate_metadata(root_metadata, item, root=True)
        pending = [root]
        while pending:
            directory = pending.pop()
            for child in directory.iterdir():
                metadata = child.lstat()
                if stat.S_ISLNK(metadata.st_mode) or not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)):
                    raise IdentityMigrationError(f"{item.name} state contains a symlink or special file")
                self._validate_metadata(metadata, item, root=False)
                if stat.S_ISDIR(metadata.st_mode):
                    pending.append(child)

    @staticmethod
    def _validate_metadata(metadata: os.stat_result, item: DirectoryMove, *, root: bool) -> None:
        # Windows test filesystems do not expose POSIX ownership or permission
        # semantics.  Production migration is POSIX-only; validate them there.
        if os.name != "posix":
            return
        if item.allowed_uids is not None and metadata.st_uid not in item.allowed_uids:
            raise IdentityMigrationError(f"{item.name} state has unexpected ownership")
        mode = stat.S_IMODE(metadata.st_mode)
        if root and mode != item.root_mode:
            raise IdentityMigrationError(f"{item.name} root has unexpected mode")
        if mode & 0o7022:
            raise IdentityMigrationError(f"{item.name} state has unsafe permissions")

    def _validate_quiescent(self) -> None:
        for item in self._moves:
            state = self._location_state(item)
            if state not in (LocationState.OLD_ONLY, LocationState.CURRENT_ONLY):
                continue
            root = item.old if state is LocationState.OLD_ONLY else item.current
            self._validate_quiescent_root(root)

    def _validate_quiescent_root(self, root: Path) -> None:
        """Validate one already-trusted state tree, including conflict recovery."""
        children = tuple(root.rglob("*"))
        trial_parents = {
            child.parent for child in children if child.name in _PORTABLE_TRIAL_MARKERS
        }
        for parent in trial_parents:
            self._validate_terminal_portable_trial(parent)
        for child in children:
            power_intent = child.name.startswith("dock-power-") and child.name.endswith(".json")
            if child.name in _HARD_BLOCKERS or power_intent:
                raise IdentityMigrationError(f"active state blocks identity migration: {child.name}")
            if child.name == "tdp-session.json":
                self._validate_idle_tdp(child)

    @staticmethod
    def _validate_terminal_portable_trial(root: Path) -> None:
        paths = {name: root / name for name in _PORTABLE_TRIAL_MARKERS}
        if not all(path.exists() and not path.is_symlink() for path in paths.values()):
            raise IdentityMigrationError("partial portable Vulkan trial state blocks identity migration")
        try:
            record = PortableTrialStore(root).read()
            if record is None:
                raise ValueError("missing trial record")
            operation_id = record["operation_id"]
            consumed = IdentityMigration._read_trial_marker(
                paths["portable-vulkan-trial.consumed"]
            )
            steam_consumed = IdentityMigration._read_trial_marker(
                paths["portable-vulkan-trial.steam-consumed"]
            )
            launch = IdentityMigration._read_trial_marker(
                paths["portable-vulkan-trial.gamescope-launch"]
            )
            parts = launch.split("\n")
            if (
                consumed != operation_id
                or steam_consumed != operation_id
                or len(parts) != 2
                or parts[0] != operation_id
                or len(parts[1]) != 32
                or any(character not in "0123456789abcdef" for character in parts[1])
            ):
                raise ValueError("trial terminal receipts do not match")
        except (KeyError, OSError, UnicodeDecodeError, ValueError) as error:
            raise IdentityMigrationError(
                "portable Vulkan trial state is not a coherent terminal quartet"
            ) from error

    @staticmethod
    def _read_trial_marker(path: Path) -> str:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        )
        with os.fdopen(descriptor, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ValueError("trial marker must be a regular file")
            raw = source.read(513)
        if len(raw) > 512:
            raise ValueError("trial marker exceeds byte bound")
        return raw.decode("ascii")

    @contextmanager
    def _hold_external_lock(self):
        lock_path = self._journal.with_name(self._journal.name + ".lock")
        parent = lock_path.parent.lstat()
        if stat.S_ISLNK(parent.st_mode) or not stat.S_ISDIR(parent.st_mode):
            raise IdentityMigrationError("migration lock parent must be a real directory")
        if os.name == "posix" and (
            parent.st_uid != os.geteuid() or stat.S_IMODE(parent.st_mode) & 0o022
        ):
            raise IdentityMigrationError("migration lock parent ownership or mode is unsafe")
        descriptor = self._acquire_lock(lock_path, create=True)
        try:
            yield
        finally:
            if descriptor is not None:
                os.close(descriptor)

    @contextmanager
    def _hold_state_locks(self):
        descriptors: list[int] = []
        try:
            for item in self._moves:
                state = self._location_state(item)
                roots = (
                    (item.old,)
                    if state is LocationState.OLD_ONLY
                    else (item.current,)
                    if state is LocationState.CURRENT_ONLY
                    else (item.old, item.current)
                    if state is LocationState.BOTH
                    else ()
                )
                for root in roots:
                    for child in root.rglob("*"):
                        if child.name.endswith(".lock") and child.is_file():
                            descriptor = self._acquire_lock(child)
                            if descriptor is not None:
                                descriptors.append(descriptor)
            yield
        finally:
            for descriptor in descriptors:
                os.close(descriptor)

    @staticmethod
    def _validate_idle_tdp(path: Path) -> None:
        try:
            raw = path.read_bytes()
            if len(raw) > 8192:
                raise ValueError
            value = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise IdentityMigrationError("TDP journal cannot be proven idle") from error
        if not isinstance(value, dict) or set(value) != {"schema", "record"} or value["schema"] != 1 or value["record"] is not None:
            raise IdentityMigrationError("non-idle TDP session blocks identity migration")

    @staticmethod
    def _acquire_lock(path: Path, *, create: bool = False) -> int | None:
        if os.name != "posix":
            return None
        try:
            import fcntl
            flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
            if create:
                flags |= os.O_CREAT
            descriptor = os.open(path, flags, 0o600)
            try:
                metadata = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_uid != os.geteuid()
                    or stat.S_IMODE(metadata.st_mode) & 0o022
                ):
                    raise IdentityMigrationError(f"lock file is unsafe: {path.name}")
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, IdentityMigrationError) as error:
                os.close(descriptor)
                if isinstance(error, BlockingIOError):
                    raise IdentityMigrationError(f"held lock blocks identity migration: {path.name}") from error
                raise
            return descriptor
        except IdentityMigrationError:
            raise
        except (ImportError, OSError) as error:
            raise IdentityMigrationError(f"lock state cannot be verified: {path.name}") from error

    @staticmethod
    def _validate_move(item: DirectoryMove, source: Path) -> None:
        destination = item.current if source == item.old else item.old
        if destination.exists() or destination.is_symlink():
            raise IdentityMigrationError(f"{item.name} destination already exists")
        try:
            source_device = source.lstat().st_dev
            source_parent = source.parent.lstat()
            parent = destination.parent.lstat()
        except OSError as error:
            raise IdentityMigrationError(f"{item.name} move endpoints are unavailable") from error
        for metadata in (source_parent, parent):
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise IdentityMigrationError(f"{item.name} move parent must be a real directory")
            if os.name == "posix" and (
                (item.allowed_uids is not None and metadata.st_uid not in item.allowed_uids)
                or stat.S_IMODE(metadata.st_mode) & 0o022
            ):
                raise IdentityMigrationError(f"{item.name} move parent has unsafe ownership or mode")
        if source_device != parent.st_dev:
            raise IdentityMigrationError(f"{item.name} migration would cross filesystems")

    def _new_document(self, planned: tuple[DirectoryMove, ...]) -> dict:
        token = self._token_factory()
        if not isinstance(token, str) or len(token) != 32 or any(character not in "0123456789abcdef" for character in token):
            raise ValueError("migration token must be 32 lowercase hex characters")
        return {
            "schema": JOURNAL_SCHEMA,
            "operation_id": token,
            "phase": "prepared",
            "moves": [self._move_dict(item) for item in planned],
            "completed": [],
        }

    @staticmethod
    def _move_dict(item: DirectoryMove) -> dict[str, str]:
        return {"name": item.name, "old": str(item.old), "current": str(item.current)}

    def _journal_moves(self, document: dict) -> tuple[DirectoryMove, ...]:
        by_name = {item.name: item for item in self._moves}
        return tuple(by_name[record["name"]] for record in document["moves"])

    def _load_journal(self) -> dict | None:
        if self._journal.is_symlink():
            raise IdentityMigrationError("migration journal cannot be a symlink")
        try:
            descriptor = os.open(self._journal, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            return None
        except OSError as error:
            raise IdentityMigrationError("migration journal is unavailable") from error
        with os.fdopen(descriptor, "rb") as source:
            metadata = os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode) or (
                os.name == "posix"
                and (metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o022)
            ):
                raise IdentityMigrationError("migration journal ownership or mode is unsafe")
            raw = source.read(MAX_JOURNAL_BYTES + 1)
        if len(raw) > MAX_JOURNAL_BYTES:
            raise IdentityMigrationError("migration journal exceeds its byte bound")
        try:
            document = json.loads(raw, object_pairs_hook=self._unique_object)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise IdentityMigrationError("migration journal is invalid") from error
        self._validate_document(document)
        return document

    @staticmethod
    def _unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise IdentityMigrationError("migration journal contains a duplicate field")
            result[key] = value
        return result

    def _validate_document(self, document: object) -> None:
        if not isinstance(document, dict) or set(document) != {"schema", "operation_id", "phase", "moves", "completed"}:
            raise IdentityMigrationError("migration journal shape is invalid")
        if type(document["schema"]) is not int or document["schema"] != JOURNAL_SCHEMA or document["phase"] not in KNOWN_PHASES:
            raise IdentityMigrationError("migration journal schema or phase is unknown")
        operation_id = document["operation_id"]
        if not isinstance(operation_id, str) or len(operation_id) != 32 or any(character not in "0123456789abcdef" for character in operation_id):
            raise IdentityMigrationError("migration operation identity is invalid")
        if not isinstance(document["moves"], list) or not document["moves"]:
            raise IdentityMigrationError("migration journal has no moves")
        names: list[str] = []
        for record in document["moves"]:
            if not isinstance(record, dict) or set(record) != {"name", "old", "current"} or not all(isinstance(value, str) for value in record.values()):
                raise IdentityMigrationError("migration move record is invalid")
            names.append(record["name"])
        completed = document["completed"]
        if not isinstance(completed, list) or not all(isinstance(name, str) for name in completed):
            raise IdentityMigrationError("migration completion record is invalid")
        if len(set(names)) != len(names) or len(set(completed)) != len(completed) or not set(completed) <= set(names):
            raise IdentityMigrationError("migration journal contains duplicate or unknown moves")

    def _validate_document_paths(self, document: dict) -> None:
        expected = {item.name: self._move_dict(item) for item in self._moves}
        for record in document["moves"]:
            if expected.get(record["name"]) != record:
                raise IdentityMigrationError("migration journal paths do not match this installation")

    def _write_journal(self, document: dict) -> None:
        self._validate_document(document)
        self._validate_document_paths(document)
        parent = self._journal.parent
        metadata = parent.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise IdentityMigrationError("migration journal parent must be a real directory")
        if os.name == "posix" and (
            metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise IdentityMigrationError("migration journal parent ownership or mode is unsafe")
        data = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
        if len(data) > MAX_JOURNAL_BYTES:
            raise IdentityMigrationError("migration journal exceeds its byte bound")
        temporary = parent / f".{self._journal.name}.{self._temporary_token()}.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            with os.fdopen(descriptor, "wb") as target:
                target.write(data)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, self._journal)
            self._sync_directory(parent)
        finally:
            temporary.unlink(missing_ok=True)

    def _temporary_token(self) -> str:
        token = self._token_factory()
        if not isinstance(token, str) or len(token) != 32 or any(character not in "0123456789abcdef" for character in token):
            raise ValueError("migration token must be 32 lowercase hex characters")
        return token

    def _validate_completed(self, document: dict) -> None:
        if document["phase"] != "committed" or set(document["completed"]) != {item.name for item in self._journal_moves(document)}:
            raise IdentityMigrationError("migration journal is not completely committed")
        for item in self._journal_moves(document):
            if self._location_state(item) is not LocationState.CURRENT_ONLY:
                raise IdentityMigrationError("committed migration does not match directory state")

    def _validate_rolled_back(self, document: dict) -> None:
        if document["phase"] != "rolled_back" or document["completed"]:
            raise IdentityMigrationError("rollback journal is incomplete")
        for item in self._journal_moves(document):
            if self._location_state(item) is not LocationState.OLD_ONLY:
                raise IdentityMigrationError("rolled-back migration does not match directory state")

    @staticmethod
    def _sync_directory(path: Path) -> None:
        if os.name != "posix":
            return
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
