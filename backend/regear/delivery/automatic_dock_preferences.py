"""Atomic fixed-path persistence for the player's automatic-dock opt-in."""

from __future__ import annotations

import json
import os
import secrets
import threading
from pathlib import Path


FILENAME = "automatic-dock.json"
MAX_BYTES = 1024


class AutomaticDockPreferenceStore:
    def __init__(self, state_root: Path) -> None:
        if not state_root.is_absolute():
            raise ValueError("automatic dock state root must be absolute")
        self._root = state_root
        self._lock = threading.Lock()

    def load(self) -> bool:
        with self._lock:
            target = self._root / FILENAME
            if target.is_symlink():
                raise ValueError("automatic dock preference cannot be a symlink")
            try:
                descriptor = os.open(
                    target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                )
            except FileNotFoundError:
                return False
            with os.fdopen(descriptor, "rb") as source:
                raw = source.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("automatic dock preference is too large")
            value = json.loads(raw.decode("utf-8"))
            if (
                not isinstance(value, dict)
                or value.get("schema_version") != 1
                or type(value.get("enabled")) is not bool
            ):
                raise ValueError("automatic dock preference is invalid")
            return value["enabled"]

    def save(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ValueError("automatic dock preference must be boolean")
        with self._lock:
            target = self._root / FILENAME
            if target.is_symlink():
                raise ValueError("automatic dock preference cannot be a symlink")
            raw = (
                json.dumps(
                    {"schema_version": 1, "enabled": enabled},
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("ascii")
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
