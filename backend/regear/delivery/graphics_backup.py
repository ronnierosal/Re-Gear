"""Bounded backups of a game's configuration, and exact restoration.

A backup is the file's bytes as they were immediately before Re-Gear wrote,
plus enough metadata to prove afterwards that a restore put back exactly those
bytes. Backups are bounded per configuration identity and pruned oldest-first,
because an unbounded backup directory on a handheld is a disk-full bug waiting
for a long play session.

Restoration is byte-for-byte. The digest recorded at backup time is verified
before the restore and again after it; a backup that does not match its own
digest is refused rather than written over a player's working file.
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
        """Copy the file's current bytes into a new bounded backup."""
        self._require_identity(identity)
        payload = self._read_source(source)
        with self._lock:
            directory = self._root / identity
            directory.mkdir(parents=True, exist_ok=True)
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
            )
            self._write_atomic(directory / payload_name, payload)
            self._write_atomic(
                directory / f"{sequence:08d}.{token}{RECORD_SUFFIX}",
                record.as_json().encode("utf-8") + b"\n",
            )
            self._prune_locked(directory)
            return record

    def records(self, identity: str) -> tuple[BackupRecord, ...]:
        """Every readable backup for an identity, oldest first."""
        self._require_identity(identity)
        directory = self._root / identity
        if not directory.is_dir():
            return ()
        found: list[BackupRecord] = []
        for path in sorted(directory.glob(f"*{RECORD_SUFFIX}")):
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
        """Put the backed-up bytes back, atomically, and verify byte equality."""
        payload = self.payload(record)
        if destination.is_symlink():
            raise BackupError("refusing to restore through a symlink")
        self._write_atomic(destination, payload)
        try:
            written = destination.read_bytes()
        except OSError as error:
            raise BackupError(f"restored file is unreadable: {error}") from error
        return written == payload

    def _next_sequence(self, directory: Path) -> int:
        highest = 0
        for path in directory.glob(f"*{RECORD_SUFFIX}"):
            leading = path.name.split(".", 1)[0]
            if leading.isdigit():
                highest = max(highest, int(leading))
        return highest + 1

    def _prune_locked(self, directory: Path) -> None:
        records = sorted(
            (record for record in self._directory_records(directory)),
            key=lambda record: record.sequence,
        )
        for record in records[: max(0, len(records) - self._limit)]:
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
        for path in sorted(directory.glob(f"*{RECORD_SUFFIX}")):
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
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _read_source(source: Path) -> bytes:
        try:
            if source.is_symlink():
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
