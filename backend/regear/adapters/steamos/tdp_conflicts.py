"""Bounded, on-demand observations of known competing power controllers.

Installed known plugins are conservative conflicts, not proof they are active.
No matches never proves exclusivity: unknown controllers and races remain possible.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True, slots=True)
class TdpConflictResult:
    complete: bool
    conflicts: tuple[str, ...]
    code: str


_PROCESSES = frozenset(("hhd", "asusd", "powerstation", "ryzenadj"))
_PLUGINS = {"powercontrol": "plugin.powercontrol", "simpledeckytdp": "plugin.simpledeckytdp"}
_PYTHON = re.compile(r"python(?:[0-9]+(?:\.[0-9]+)*)?")


def _plugin(name: str) -> str | None:
    normalized = re.sub(r"[ _-]", "", name).lower()
    return _PLUGINS.get(normalized)


def _executable(value: str) -> str | None:
    name = PurePosixPath(value).name
    if name.endswith(".py"):
        name = name[:-3]
    return f"process.{name}" if name in _PROCESSES else None


def _command_controller(raw: bytes) -> str | None:
    argv = raw.decode("utf-8").split("\0")
    if not argv or not argv[0]:
        return None
    direct = _executable(argv[0])
    if direct:
        return direct
    if not _PYTHON.fullmatch(PurePosixPath(argv[0]).name):
        return None
    index = 1
    while index < len(argv) and argv[index]:
        argument = argv[index]
        if argument == "-m":
            module = argv[index + 1] if index + 1 < len(argv) else ""
            name = module.split(".")[0]
            return f"process.{name}" if name in _PROCESSES else None
        if argument == "-c":
            return None
        if argument in ("-W", "-X"):
            index += 2
            continue
        if argument == "--":
            index += 1
            if index >= len(argv):
                return None
            argument = argv[index]
        elif argument.startswith("-"):
            index += 1
            continue
        script = PurePosixPath(argument)
        if script.name == "__main__.py":
            return _executable(script.parent.name)
        return _executable(argument)
    return None


class KnownTdpControllerScan:
    """Inspect caller-resolved plugin root and procfs without retaining raw data."""

    MAX_PROC_ENTRIES = 4096
    MAX_PLUGIN_ENTRIES = 128
    MAX_COMM_BYTES = 256
    MAX_CMDLINE_BYTES = 8192
    MAX_MANIFEST_BYTES = 16 * 1024

    def __init__(self, *, plugins_root: Path, proc_root: Path = Path("/proc")) -> None:
        self._proc_root = Path(proc_root)
        self._plugins_root = Path(plugins_root)

    @staticmethod
    def _read(path: Path, limit: int) -> bytes:
        with path.open("rb") as stream:
            result = stream.read(limit + 1)
        if len(result) > limit:
            raise ValueError("oversized")
        return result

    @staticmethod
    def _entries(root: Path, limit: int):
        # Count all directory entries to bound work even on an unexpected root.
        with os.scandir(root) as entries:
            for count, entry in enumerate(entries):
                if count >= limit:
                    raise ValueError("too_many_entries")
                yield entry

    @staticmethod
    def _vanished(path: Path) -> bool:
        try:
            path.stat()
        except FileNotFoundError:
            return True
        except OSError:
            pass
        return False

    def scan(self) -> TdpConflictResult:
        complete = True
        conflicts: set[str] = set()
        try:
            for entry in self._entries(self._proc_root, self.MAX_PROC_ENTRIES):
                if re.fullmatch(r"[0-9]+", entry.name) is None:
                    continue
                process = self._proc_root / entry.name
                try:
                    comm = self._read(process / "comm", self.MAX_COMM_BYTES).decode("utf-8").strip()
                    known = _executable(comm)
                    if known:
                        conflicts.add(known)
                    command = self._read(process / "cmdline", self.MAX_CMDLINE_BYTES)
                    known = _command_controller(command)
                    if known:
                        conflicts.add(known)
                except FileNotFoundError:
                    if not self._vanished(process):
                        complete = False
                except (OSError, ValueError, UnicodeError):
                    complete = False
        except (OSError, ValueError):
            complete = False

        try:
            for entry in self._entries(self._plugins_root, self.MAX_PLUGIN_ENTRIES):
                try:
                    if not entry.is_dir():
                        continue
                    known = _plugin(entry.name)
                    if known:
                        conflicts.add(known)
                    raw = self._read(self._plugins_root / entry.name / "plugin.json", self.MAX_MANIFEST_BYTES)
                    manifest = json.loads(raw)
                    if not isinstance(manifest, dict) or not isinstance(manifest.get("name"), str):
                        complete = False
                        continue
                    known = _plugin(manifest["name"])
                    if known:
                        conflicts.add(known)
                except (OSError, ValueError, UnicodeError, RecursionError):
                    complete = False
        except (OSError, ValueError):
            complete = False
        code = "tdp.conflict" if conflicts else (
            "tdp.no_known_conflict" if complete else "tdp.conflict_scan_unavailable"
        )
        return TdpConflictResult(complete, tuple(sorted(conflicts)), code)
