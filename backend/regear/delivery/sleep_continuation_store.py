"""Atomic fixed-path persistence for one pending sleep continuation.

The same shape and the same caution as the relaunch intent store, for the
same reason: this record makes a machine do something -- here, sleep -- from a
panel that did not ask for it directly. At most one, replaced rather than
queued, consumed by reading, and every read failure is "nothing recorded",
because a record that cannot be read is not a machine to put to sleep.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from pathlib import Path

from ..domain.sleep_continuation import PendingSleep


FILENAME = "pending-sleep.json"
SCHEMA_VERSION = 1
MAX_BYTES = 1024


class PendingSleepStore:
    """Remember one sleep to finish after the disconnect that carried it."""

    def __init__(self, state_root: Path) -> None:
        if not state_root.is_absolute():
            raise ValueError("pending sleep state root must be absolute")
        self._root = state_root
        self._lock = threading.Lock()

    def record(self, pending: PendingSleep) -> None:
        """Replace any pending continuation with this one."""
        if not pending.boot_hash or len(pending.boot_hash) > 128:
            raise ValueError("pending sleep boot identity is invalid")
        for value in (pending.recorded_monotonic, pending.recorded_boottime):
            if type(value) not in (int, float) or isinstance(value, bool):
                raise ValueError("pending sleep timestamp is invalid")
        raw = (
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "boot_hash": pending.boot_hash,
                    "recorded_monotonic": float(pending.recorded_monotonic),
                    "recorded_boottime": float(pending.recorded_boottime),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("ascii")
        with self._lock:
            self._write_locked(raw)

    def take(self) -> PendingSleep | None:
        """Read the pending continuation and clear it, in that order."""
        with self._lock:
            pending = self._read_locked()
            self._clear_locked()
            return pending

    def clear(self) -> None:
        with self._lock:
            self._clear_locked()

    def _target(self) -> Path:
        target = self._root / FILENAME
        if target.is_symlink():
            raise ValueError("pending sleep record cannot be a symlink")
        return target

    def _read_locked(self) -> PendingSleep | None:
        target = self._target()
        try:
            descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except OSError:
            return None
        with os.fdopen(descriptor, "rb") as source:
            raw = source.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return None
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
            return None
        boot_hash = value.get("boot_hash")
        monotonic = value.get("recorded_monotonic")
        boottime = value.get("recorded_boottime")
        if not isinstance(boot_hash, str) or not boot_hash or len(boot_hash) > 128:
            return None
        for reading in (monotonic, boottime):
            if type(reading) not in (int, float) or isinstance(reading, bool):
                return None
        return PendingSleep(boot_hash, float(monotonic), float(boottime))

    def _clear_locked(self) -> None:
        try:
            self._target().unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def _write_locked(self, raw: bytes) -> None:
        target = self._target()
        temporary = self._root / f".{FILENAME}.{secrets.token_hex(8)}.tmp"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
            os.chmod(target, 0o600)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
