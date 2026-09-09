"""Atomic fixed-path persistence for one pending relaunch intent.

At most one, replaced rather than queued: two games cannot both be the game
that was closed, and a queue of intents is a queue of games that might start
themselves. Reading consumes it, so an intent that is acted on cannot be acted
on twice, and one that is refused is discarded rather than retried.

Every read failure is "nothing recorded". Failing the other way -- treating an
unreadable file as a game to launch -- would start something nobody asked for,
which is the failure this whole record is written carefully to avoid. The one
exception is a symlink, refused loudly, because that is not corruption but
someone redirecting a root-written file.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from pathlib import Path

from ..domain.game_compatibility import STEAM_APP_ID_RE
from ..domain.relaunch_intent import RelaunchIntent


FILENAME = "relaunch-intent.json"
SCHEMA_VERSION = 1
MAX_BYTES = 1024
TOKEN_RE = STEAM_APP_ID_RE


class RelaunchIntentStore:
    """Remember one game to reopen after the disconnect that closed it."""

    def __init__(self, state_root: Path) -> None:
        if not state_root.is_absolute():
            raise ValueError("relaunch intent state root must be absolute")
        self._root = state_root
        self._lock = threading.Lock()

    def record(self, intent: RelaunchIntent) -> None:
        """Replace any pending intent with this one."""
        if not TOKEN_RE.fullmatch(intent.steam_app_id):
            raise ValueError("relaunch intent app id is invalid")
        if not intent.boot_hash or len(intent.boot_hash) > 128:
            raise ValueError("relaunch intent boot identity is invalid")
        if not isinstance(intent.recorded_boot_seconds, (int, float)):
            raise ValueError("relaunch intent timestamp is invalid")
        raw = (
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "steam_app_id": intent.steam_app_id,
                    "boot_hash": intent.boot_hash,
                    "recorded_boot_seconds": float(intent.recorded_boot_seconds),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("ascii")
        with self._lock:
            self._write_locked(raw)

    def take(self) -> RelaunchIntent | None:
        """Read the pending intent and clear it, in that order.

        Clearing even when the caller goes on to refuse it: an intent that
        could not be honoured now is not one to keep offering.
        """
        with self._lock:
            intent = self._read_locked()
            self._clear_locked()
            return intent

    def peek(self) -> RelaunchIntent | None:
        """Read without consuming. For reporting, never for acting."""
        with self._lock:
            return self._read_locked()

    def clear(self) -> None:
        with self._lock:
            self._clear_locked()

    def _target(self) -> Path:
        target = self._root / FILENAME
        if target.is_symlink():
            raise ValueError("relaunch intent cannot be a symlink")
        return target

    def _read_locked(self) -> RelaunchIntent | None:
        target = self._target()
        try:
            descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            return None
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
        app_id = value.get("steam_app_id")
        boot_hash = value.get("boot_hash")
        recorded = value.get("recorded_boot_seconds")
        if not isinstance(app_id, str) or not TOKEN_RE.fullmatch(app_id):
            return None
        if not isinstance(boot_hash, str) or not boot_hash or len(boot_hash) > 128:
            return None
        if type(recorded) not in (int, float) or isinstance(recorded, bool):
            return None
        return RelaunchIntent(app_id, boot_hash, float(recorded))

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
