"""Root-owned private state for exact portable-audio rollback."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


NODE_NAME_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,256}$")
MAX_STATE_BYTES = 1024
STATE_FILE_MODE = 0o600


class PortableAudioStateStore:
    def __init__(self, root: Path) -> None:
        if not root.is_absolute() or root == Path(root.anchor):
            raise ValueError("audio state root must be a bounded absolute path")
        self._root = root
        self._target = root / "portable-audio.json"

    def load(self) -> str:
        try:
            if self._target.is_symlink() or not self._target.is_file():
                return ""
            if self._target.stat().st_size > MAX_STATE_BYTES:
                return ""
            value = json.loads(self._target.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or set(value) != {
                "schema_version",
                "sink_name",
            }:
                return ""
            if value.get("schema_version") != 1:
                return ""
            name = value.get("sink_name", "")
            return name if isinstance(name, str) and NODE_NAME_RE.fullmatch(name) else ""
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return ""

    def save(self, sink_name: str) -> None:
        if not NODE_NAME_RE.fullmatch(sink_name):
            raise ValueError("portable audio sink name is invalid")
        if self.load() == sink_name:
            return
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self._root.is_symlink() or not self._root.is_dir():
            raise ValueError("audio state root is unsafe")
        temporary = self._root / ".portable-audio.tmp"
        data = json.dumps(
            {"schema_version": 1, "sink_name": sink_name}, separators=(",", ":")
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, STATE_FILE_MODE)
        try:
            os.write(descriptor, data.encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.chmod(temporary, STATE_FILE_MODE)
        os.replace(temporary, self._target)

    def clear(self) -> None:
        try:
            if self._target.is_symlink():
                return
            self._target.unlink()
        except FileNotFoundError:
            pass
