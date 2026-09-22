"""Bounded backups of a game's configuration, and exact restoration.

A backup is the file's bytes as they were immediately before Re-Gear wrote,
plus enough metadata to prove afterwards that a restore put back exactly those
bytes. Backups are bounded per configuration identity and pruned oldest-first,
because an unbounded backup directory on a handheld is a disk-full bug waiting
for a long play session.

One backup is different from the others: the first capture for a target is the
*baseline*, the bytes as the player had them before Re-Gear ever wrote. Pruning
never evicts it, and it is what Restore My Settings restores. Rotating the
baseline out would leave "restore" meaning "go back to the previous Re-Gear
profile", which is not what a player asking for their settings back means.

Restoration is byte-for-byte. The digest recorded at backup time is verified
before the restore and again after it; a backup that does not match its own
digest is refused rather than written over a player's working file. Every
filesystem call here is converted into BackupError: an unwritable backup
directory must become a refused profile, never an exception escaping into a
game launch.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
from dataclasses import dataclass
from pathlib import Path


MAX_BACKUPS = 5
MAX_CONFIG_BYTES = 2 * 1024 * 1024
IDENTITY_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,160}$")
RECORD_SUFFIX = ".json"
PAYLOAD_SUFFIX = ".bak"


class BackupError(RuntimeError):
    """A backup could not be taken or trusted. Callers never write past this."""


@dataclass(frozen=True, slots=True)
class BackupRecord:
    identity: str
    sequence: int
    source_path: str
    mode: str
    digest: str
    size: int
    payload_name: str
    #: The pre-management original. Exactly one per identity, never pruned.
    baseline: bool = False

    def as_json(self) -> str:
        return json.dumps(
            {
                "identity": self.identity,
                "sequence": self.sequence,
                "source_path": self.source_path,
                "mode": self.mode,
                "digest": self.digest,
                "size": self.size,
                "payload_name": self.payload_name,
                "baseline": self.baseline,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


def digest_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class BackupManager:
    """Keep the last few pre-write copies of each managed configuration."""

    def __init__(self, backup_root: Path, limit: int = MAX_BACKUPS) -> None:
        if not backup_root.is_absolute():
            raise ValueError("backup root must be absolute")
        if limit < 1:
            raise ValueError("backup limit must be positive")
        self._root = backup_root
        self._limit = limit
        self._lock = threading.Lock()

    @property
    def root(self) -> Path:
        return self._root

    def capture(self, identity: str, source: Path, mode: str) -> BackupRecord:
        """Copy the file's current bytes into a new bounded backup.

        The first capture for an identity becomes its baseline. Every
        filesystem failure here -- an unwritable root, a root that is a regular
        file, a permission error -- is a BackupError, so the caller can refuse
        the profile instead of propagating an OSError.
        """
        self._require_identity(identity)
        payload = self._read_source(source)
        with self._lock:
            directory = self._root / identity
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise BackupError(f"backup directory is unusable: {error}") from error
            existing = self._directory_records(directory)
            sequence = self._next_sequence(directory)
            token = secrets.token_hex(8)
            payload_name = f"{sequence:08d}.{token}{PAYLOAD_SUFFIX}"
            record = BackupRecord(
                identity=identity,
                sequence=sequence,
                source_path=str(source),
                mode=mode,
                digest=digest_of(payload),
                size=len(payload),
                payload_name=payload_name,
                baseline=not any(item.baseline for item in existing),
            )
            self._write_atomic(directory / payload_name, payload)
            self._write_atomic(
                directory / f"{sequence:08d}.{token}{RECORD_SUFFIX}",
                record.as_json().encode("utf-8") + b"\n",
            )
            self._prune_locked(directory)
            return record

    def baseline(self, identity: str) -> BackupRecord | None:
        """The pre-management original for this target, if one was kept."""
        for record in self.records(identity):
            if record.baseline:
                return record
        return None

    def records(self, identity: str) -> tuple[BackupRecord, ...]:
        """Every readable backup for an identity, oldest first."""
        self._require_identity(identity)
        directory = self._root / identity
        try:
            if not directory.is_dir():
                return ()
            listing = sorted(directory.glob(f"*{RECORD_SUFFIX}"))
        except OSError as error:
            raise BackupError(f"backup directory is unreadable: {error}") from error
        found: list[BackupRecord] = []
        for path in listing:
            record = self._read_record(path)
            if record is not None:
                found.append(record)
        found.sort(key=lambda record: record.sequence)
        return tuple(found)

    def latest(self, identity: str) -> BackupRecord | None:
        records = self.records(identity)
        return records[-1] if records else None

    def payload(self, record: BackupRecord) -> bytes:
        """The backed-up bytes, verified against the recorded digest."""
        path = self._root / record.identity / record.payload_name
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise BackupError(f"backup payload is unreadable: {error}") from error
        if len(payload) != record.size or digest_of(payload) != record.digest:
            raise BackupError("backup payload does not match its recorded digest")
        return payload

    def restore(self, record: BackupRecord, destination: Path) -> bool:
        """Put the backed-up bytes back, atomically, and verify byte equality.

        The record must name this destination. A digest proves a payload is
        intact, not that it belongs to this file, and restoring one game's
        configuration over another's is exactly the mistake a shared identity
        would otherwise allow.
        """
        if record.source_path != str(destination):
            raise BackupError(
                "refusing to restore a backup taken from "
                f"{record.source_path!r} onto {str(destination)!r}"
            )
        payload = self.payload(record)
        try:
            if destination.is_symlink():
                raise BackupError("refusing to restore through a symlink")
        except OSError as error:
            raise BackupError(f"restore destination is unreadable: {error}") from error
        self._write_atomic(destination, payload)
        try:
            written = destination.read_bytes()
        except OSError as error:
            raise BackupError(f"restored file is unreadable: {error}") from error
        return written == payload

    def _next_sequence(self, directory: Path) -> int:
        highest = 0
        try:
            listing = list(directory.glob(f"*{RECORD_SUFFIX}"))
        except OSError as error:
            raise BackupError(f"backup directory is unreadable: {error}") from error
        for path in listing:
            leading = path.name.split(".", 1)[0]
            if leading.isdigit():
                highest = max(highest, int(leading))
        return highest + 1

    def _prune_locked(self, directory: Path) -> None:
        """Drop the oldest rotating copies, never the baseline.

        The limit counts rotating copies only. A store at its limit evicts the
        oldest of those; if the baseline were included in the rotation, the one
        record a player's Restore My Settings depends on would be the first to
        go.
        """
        records = sorted(self._directory_records(directory), key=lambda item: item.sequence)
        rotating = [record for record in records if not record.baseline]
        for record in rotating[: max(0, len(rotating) - self._limit)]:
            stem = record.payload_name[: -len(PAYLOAD_SUFFIX)]
            for suffix in (PAYLOAD_SUFFIX, RECORD_SUFFIX):
                try:
                    (directory / f"{stem}{suffix}").unlink()
                except FileNotFoundError:
                    continue
                except OSError as error:
                    raise BackupError(f"backup pruning failed: {error}") from error

    def _directory_records(self, directory: Path) -> list[BackupRecord]:
        found = []
        try:
            listing = sorted(directory.glob(f"*{RECORD_SUFFIX}"))
        except OSError as error:
            raise BackupError(f"backup directory is unreadable: {error}") from error
        for path in listing:
            record = self._read_record(path)
            if record is not None:
                found.append(record)
        return found

    @staticmethod
    def _read_record(path: Path) -> BackupRecord | None:
        try:
            raw = path.read_text(encoding="utf-8")
            value = json.loads(raw)
        except (OSError, ValueError):
            return None
        if not isinstance(value, dict):
            return None
        try:
            return BackupRecord(
                identity=str(value["identity"]),
                sequence=int(value["sequence"]),
                source_path=str(value["source_path"]),
                mode=str(value["mode"]),
                digest=str(value["digest"]),
                size=int(value["size"]),
                payload_name=str(value["payload_name"]),
                baseline=bool(value.get("baseline", False)),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _read_source(source: Path) -> bytes:
        try:
            if source.is_symlink():  # noqa: SIM102 - distinct refusal reasons
                raise BackupError("refusing to back up through a symlink")
            if not source.is_file():
                raise BackupError("configuration to back up is not a regular file")
            if source.stat().st_size > MAX_CONFIG_BYTES:
                raise BackupError("configuration is too large to back up")
            return source.read_bytes()
        except OSError as error:
            raise BackupError(f"configuration is unreadable: {error}") from error

    @staticmethod
    def _write_atomic(target: Path, payload: bytes) -> None:
        """Write bytes so the target is either the old file or the whole new one."""
        directory = target.parent
        temporary = directory / f".{target.name}.{secrets.token_hex(8)}.tmp"
        try:
            with open(temporary, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
            handle = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(handle)
            finally:
                os.close(handle)
        except OSError as error:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise BackupError(f"atomic write failed: {error}") from error

    @staticmethod
    def _require_identity(identity: str) -> None:
        if not IDENTITY_RE.fullmatch(identity):
            raise ValueError("backup identity is invalid")
