"""Resolve a private performance endpoint from exact Steam-scope evidence.

No process-name guess, outer WAYLAND_DISPLAY fallback, socket connection, or
runtime mutation. Matching scope children must agree on the endpoint; their
generation set binds the context without guessing which child is the renderer.
The caller must resolve again after reading and discard a changed context.
The performance reader separately verifies socket ownership and compositor peer.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .game_scopes import GameScopeScan, parse_game_scopes
from .gamescope import GamescopeScan, parse_process_start_time
from .gamescope_performance import PerformanceTarget


@dataclass(frozen=True, slots=True)
class PerformanceTargetResolution:
    code: str
    target: PerformanceTarget | None = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        return self.target is not None and self.code == "performance.target_resolved"

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "context_key": self.target.context_key if self.target else ""}


class GamescopePerformanceTargetResolver:
    MAX_PROC_ENTRIES = 4096
    MAX_STATUS_BYTES = 8192
    MAX_CGROUP_BYTES = 8192
    MAX_STAT_BYTES = 4096
    MAX_ENVIRONMENT_BYTES = 65536

    def __init__(self, proc_root: Path = Path("/proc"), *, runtime_root: Path = Path("/run/user")) -> None:
        self._root = Path(proc_root)
        # Injectable filesystem root for fixtures; the observed environment must
        # still contain the exact Linux /run/user/<uid> runtime directory.
        self._runtime_root = Path(runtime_root)

    @staticmethod
    def _read(path: Path, limit: int) -> bytes:
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("Oversized evidence")
        return raw

    def _boot(self) -> bytes:
        boot = self._read(self._root / "sys/kernel/random/boot_id", 37).strip()
        if re.fullmatch(rb"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", boot) is None:
            raise ValueError("Invalid boot identity")
        return boot

    def _uid(self, process: Path) -> int:
        raw = self._read(process / "status", self.MAX_STATUS_BYTES)
        rows = [line for line in raw.splitlines() if line.startswith(b"Uid:")]
        if len(rows) != 1 or re.fullmatch(rb"Uid:[ \t]+[0-9]{1,10}(?:[ \t]+[0-9]{1,10}){3}[ \t]*", rows[0]) is None:
            raise ValueError("Invalid process owner")
        ids = tuple(int(value) for value in rows[0].split()[1:])
        if len(set(ids)) != 1:
            raise ValueError("Mixed process credentials")
        return ids[0]

    def _generation(self, process: Path, pid: int) -> int:
        raw = self._read(process / "stat", self.MAX_STAT_BYTES).decode("utf-8")
        ticks = parse_process_start_time(raw, pid)
        fields = raw[raw.rfind(")") + 1:].split()
        if not ticks or not fields or fields[0] not in ("R", "S", "D", "T", "t", "W", "K", "P", "I"):
            raise ValueError("Invalid process generation")
        return ticks

    def _cgroup(self, process: Path) -> str:
        raw = self._read(process / "cgroup", self.MAX_CGROUP_BYTES).decode("utf-8")
        rows = [row for row in raw.splitlines() if row.startswith("0::/")]
        if len(rows) != 1:
            raise ValueError("Unified cgroup evidence unavailable")
        value = rows[0][3:]
        if any(part in (".", "..") for part in value.split("/")):
            raise ValueError("Invalid cgroup path")
        return value

    @staticmethod
    def _in_scope(cgroup: str, uid: int, scope: str) -> bool:
        parts = cgroup.split("/")
        prefix = ["", "user.slice", f"user-{uid}.slice", f"user@{uid}.service"]
        return parts[:4] == prefix and parts[4:].count(scope) == 1

    def _endpoint(self, process: Path, uid: int) -> str | None:
        raw = self._read(process / "environ", self.MAX_ENVIRONMENT_BYTES)
        if raw and not raw.endswith(b"\0"):
            raise ValueError("Truncated environment")
        selected: dict[bytes, bytes] = {}
        for part in raw.split(b"\0"):
            name, _, value = part.partition(b"=")
            if name in (b"GAMESCOPE_WAYLAND_DISPLAY", b"XDG_RUNTIME_DIR"):
                if name in selected:
                    raise ValueError("Duplicate endpoint environment")
                selected[name] = value
        display = selected.get(b"GAMESCOPE_WAYLAND_DISPLAY")
        if display is None:
            return None
        runtime = selected.get(b"XDG_RUNTIME_DIR")
        if runtime != f"/run/user/{uid}".encode("ascii"):
            raise ValueError("Runtime directory is not bound to process owner")
        if re.fullmatch(rb"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,99}", display) is None:
            raise ValueError("Endpoint must be an observed local socket basename")
        return display.decode("ascii")

    @staticmethod
    def _vanished(path: Path) -> bool:
        try:
            path.stat()
        except FileNotFoundError:
            return True
        except OSError:
            pass
        return False

    def resolve(self, game: GameScopeScan, gamescope: GamescopeScan) -> PerformanceTargetResolution:
        if not isinstance(game, GameScopeScan) or not game.ok or not game.active_app_id or len(game.scopes) != 1:
            return PerformanceTargetResolution("performance.game_unverified")
        scope = game.scopes[0]
        if type(scope) is not str or len(scope) > 255 or type(game.active_app_id) is not str:
            return PerformanceTargetResolution("performance.game_unverified")
        parsed = parse_game_scopes(scope)
        if parsed.scopes != (scope,) or parsed.active_app_id != game.active_app_id:
            return PerformanceTargetResolution("performance.game_unverified")
        if not isinstance(gamescope, GamescopeScan) or not gamescope.ok:
            return PerformanceTargetResolution("performance.compositor_unverified")
        compositor = gamescope.process
        uid, compositor_pid, ticks = compositor.uid, compositor.pid, compositor.start_time_ticks
        if any(type(v) is not int or not 0 < v <= 0xFFFFFFFF for v in (uid, compositor_pid)) or type(ticks) is not int or ticks <= 0:
            return PerformanceTargetResolution("performance.compositor_unverified")
        if re.fullmatch(r"[1-9][0-9]{0,9}", game.active_app_id) is None or int(game.active_app_id) > 0xFFFFFFFF:
            return PerformanceTargetResolution("performance.game_unverified")
        try:
            boot = self._boot()
            compositor_path = self._root / str(compositor_pid)
            if self._uid(compositor_path) != uid or self._generation(compositor_path, compositor_pid) != ticks:
                return PerformanceTargetResolution("performance.context_changed")
            members: list[tuple[int, int, str, str | None]] = []
            endpoints: set[str] = set()
            with os.scandir(self._root) as entries:
                for count, entry in enumerate(entries):
                    if count >= self.MAX_PROC_ENTRIES:
                        return PerformanceTargetResolution("performance.target_unavailable")
                    if re.fullmatch(r"[1-9][0-9]{0,9}", entry.name) is None:
                        continue
                    pid = int(entry.name)
                    process = self._root / entry.name
                    try:
                        cgroup = self._cgroup(process)
                        if not self._in_scope(cgroup, uid, scope):
                            continue
                        before = self._generation(process, pid)
                        if self._uid(process) != uid:
                            raise ValueError("Scope member owner mismatch")
                        endpoint = self._endpoint(process, uid)
                        if self._generation(process, pid) != before or self._uid(process) != uid or self._cgroup(process) != cgroup:
                            return PerformanceTargetResolution("performance.context_changed")
                        members.append((pid, before, cgroup, endpoint))
                        if endpoint is not None:
                            endpoints.add(endpoint)
                    except FileNotFoundError:
                        if not self._vanished(process):
                            raise
            if not members or not endpoints:
                return PerformanceTargetResolution("performance.endpoint_unavailable")
            if len(endpoints) != 1:
                return PerformanceTargetResolution("performance.endpoint_ambiguous")
            for pid, before, cgroup, endpoint in members:
                process = self._root / str(pid)
                if self._uid(process) != uid or self._generation(process, pid) != before or self._cgroup(process) != cgroup or self._endpoint(process, uid) != endpoint:
                    return PerformanceTargetResolution("performance.context_changed")
            if self._boot() != boot or self._uid(compositor_path) != uid or self._generation(compositor_path, compositor_pid) != ticks:
                return PerformanceTargetResolution("performance.context_changed")
            endpoint = next(iter(endpoints))
            identity = [boot.decode("ascii"), str(uid), str(compositor_pid), str(ticks), scope, endpoint]
            identity.extend(f"{pid}:{generation}" for pid, generation, _, _ in sorted(members))
            key = hashlib.sha256("\0".join(identity).encode("utf-8")).hexdigest()
            target = PerformanceTarget(self._runtime_root / str(uid) / endpoint, uid, compositor_pid, int(game.active_app_id), key, ticks)
            return PerformanceTargetResolution("performance.target_resolved", target)
        except (OSError, ValueError, UnicodeError, IndexError):
            return PerformanceTargetResolution("performance.target_unavailable")
