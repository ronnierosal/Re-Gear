"""Atomic recovery persistence for one TDP service owner, at a fixed filename.

The caller supplies an existing private state directory, never a frontend path.
The runtime must own one service instance; this is not a cross-process lock.
"""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from dataclasses import asdict
from pathlib import Path

from ..ports.tdp import TdpReading, TdpRegister, TdpSessionRecord


MAX_BYTES = 8192
FILENAME = "tdp-session.json"


def _reading(value: object) -> TdpReading:
    if not isinstance(value, dict) or set(value) != {"binding", "sustained", "slow", "fast"}:
        raise ValueError("Invalid TDP reading shape")
    if not isinstance(value["binding"], str) or re.fullmatch(r"[0-9a-f]{64}", value["binding"]) is None:
        raise ValueError("Invalid TDP binding")
    registers = []
    for name in ("sustained", "slow", "fast"):
        item = value[name]
        if not isinstance(item, dict) or set(item) != {"current", "minimum", "maximum"}:
            raise ValueError("Invalid TDP register shape")
        registers.append(TdpRegister(**item))
    return TdpReading(value["binding"], *registers)


def _decode(value: object) -> TdpSessionRecord | None:
    if not isinstance(value, dict) or set(value) != {"schema", "record"} or type(value["schema"]) is not int or value["schema"] != 1:
        raise ValueError("Invalid TDP journal schema")
    item = value["record"]
    if item is None:
        return None
    if not isinstance(item, dict) or set(item) != {"baseline", "applied", "phase", "pending_watts"}:
        raise ValueError("Invalid TDP journal shape")
    return TdpSessionRecord(_reading(item["baseline"]), _reading(item["applied"]), item["phase"], item["pending_watts"])


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate TDP journal key")
        result[key] = value
    return result


class FileTdpJournal:
    def __init__(self, state_root: Path) -> None:
        if not state_root.is_absolute():
            raise ValueError("TDP state root must be absolute")
        self._root = state_root
        self._target = state_root / FILENAME

    def _validate(self) -> None:
        metadata = self._root.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or self._root.is_symlink():
            raise ValueError("TDP state root must be a real directory")
        if os.name != "nt" and (metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022):
            raise ValueError("TDP state root must be private to its owner")
        try:
            target = self._target.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISREG(target.st_mode) or self._target.is_symlink():
            raise ValueError("TDP journal must be a regular file")
        if os.name != "nt" and (target.st_uid != os.geteuid() or target.st_mode & 0o022):
            raise ValueError("TDP journal must be private to its owner")

    def load(self) -> TdpSessionRecord | None:
        self._validate()
        try:
            descriptor = os.open(self._target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            return None
        with os.fdopen(descriptor, "rb") as source:
            raw = source.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("TDP journal exceeds byte bound")
        return _decode(json.loads(raw, object_pairs_hook=_unique_pairs))

    def save(self, record: TdpSessionRecord | None) -> None:
        self._validate()
        value = {"schema": 1, "record": None if record is None else asdict(record)}
        _decode(value)  # Validate the exact public persistence shape before writing.
        raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
        if len(raw) > MAX_BYTES:
            raise ValueError("TDP journal exceeds byte bound")
        descriptor, name = tempfile.mkstemp(prefix=".tdp-session.", suffix=".tmp", dir=self._root)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as target:
                target.write(raw)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, self._target)
            if os.name != "nt":
                directory = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)
