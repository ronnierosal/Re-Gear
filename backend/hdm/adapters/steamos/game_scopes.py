"""Fail-closed Steam game detection through user systemd scopes."""

from __future__ import annotations

import os
import math
import re
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol, Sequence

from ...domain.models import GameState
from .commands import CommandResult, ReadOnlyCommandRunner


LEGACY_SCOPE_PATTERNS = (
    re.compile(r"app-steam-(?P<appid>[1-9][0-9]*)\.scope"),
    re.compile(r"steam-app-(?P<appid>[1-9][0-9]*)\.scope"),
)
CURRENT_SCOPE_PATTERN = re.compile(
    r"app-steam-app(?P<appid>[1-9][0-9]*)-[A-Za-z0-9_-]+\.scope"
)
CURRENT_SCOPE_PREFIX = "app-steam-app"


def is_game_scope_path(value: str) -> bool:
    """Return true only for a recognized Steam game scope path component."""
    names = (part for part in "/".join(value.split("\\")).split("/") if part)
    return any(
        any(pattern.fullmatch(name) for pattern in LEGACY_SCOPE_PATTERNS)
        or CURRENT_SCOPE_PATTERN.fullmatch(name) is not None
        or name.startswith(CURRENT_SCOPE_PREFIX)
        for name in names
    )


class Runner(Protocol):
    def run(self, argv: Sequence[str]) -> CommandResult: ...


@dataclass(frozen=True, slots=True)
class GameScopeScan:
    state: GameState
    scopes: tuple[str, ...] = field(default_factory=tuple)
    app_ids: tuple[str, ...] = field(default_factory=tuple)
    unparsed_current_scopes: tuple[str, ...] = field(default_factory=tuple)
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.state is not GameState.UNKNOWN and not self.error

    @property
    def active_app_id(self) -> str:
        if (
            self.state is GameState.RUNNING
            and len(self.app_ids) == 1
            and not self.unparsed_current_scopes
        ):
            return self.app_ids[0]
        return ""


def parse_game_scopes(output: str) -> GameScopeScan:
    unit_names = tuple(
        line.split(maxsplit=1)[0]
        for line in output.splitlines()
        if line.strip() and line.split(maxsplit=1)[0].endswith(".scope")
    )
    known: list[str] = []
    app_ids: list[str] = []
    unparsed_current: list[str] = []
    for name in unit_names:
        match = next(
            (
                candidate
                for pattern in (*LEGACY_SCOPE_PATTERNS, CURRENT_SCOPE_PATTERN)
                if (candidate := pattern.fullmatch(name)) is not None
            ),
            None,
        )
        if match is not None:
            known.append(name)
            app_ids.append(match.group("appid"))
        elif name.startswith(CURRENT_SCOPE_PREFIX):
            unparsed_current.append(name)
    running = tuple(sorted(set(known + unparsed_current)))
    return GameScopeScan(
        GameState.RUNNING if running else GameState.IDLE,
        running,
        tuple(sorted(set(app_ids), key=int)),
        tuple(sorted(set(unparsed_current))),
    )


class LaunchGameScopeDiscovery:
    """Bounded recognized-Steam-scope scan for an authenticated waiting user.

    Caller supplies the authenticated UID. IDLE means no recognized Steam
    scope in this complete traversal, not absence of arbitrary workloads.
    This collector never invokes a command or requires a running Gamescope.
    """
    MAX_ENTRIES = 4096
    MAX_DEPTH = 16

    def __init__(self, cgroup_root=Path('/sys/fs/cgroup'), *, clock=time.monotonic):
        self._root=Path(cgroup_root)
        self._clock=clock

    def scan(self, user_uid, *, deadline):
        if (type(user_uid) is not int or user_uid<0 or type(deadline) not in (int,float)
                or not math.isfinite(deadline) or deadline<0):
            return GameScopeScan(GameState.UNKNOWN,error='Invalid authenticated scope scan input.')
        descriptors=[];anchors=[];names=[];seen=set();entries=0;previous=None
        traversed=[]
        def check():
            nonlocal previous
            now=self._clock()
            if (type(now) not in (int,float) or not math.isfinite(now) or now<0
                    or now>=deadline or (previous is not None and now<previous)):
                raise ValueError('scope deadline unavailable')
            previous=now
        def identity(info):return info.st_dev,info.st_ino
        flags=os.O_RDONLY|getattr(os,'O_DIRECTORY',0x10000)|getattr(os,'O_NOFOLLOW',0x20000)|getattr(os,'O_CLOEXEC',0x80000)
        def open_directory(name,parent=None):
            check()
            fd=os.open(name,flags,**({} if parent is None else {'dir_fd':parent}))
            descriptors.append(fd)
            info=os.fstat(fd)
            if not stat.S_ISDIR(info.st_mode):raise ValueError('scope directory required')
            anchors.append((name,parent,fd,identity(info)))
            return fd
        def walk(fd,depth):
            nonlocal entries
            check()
            if depth>self.MAX_DEPTH:raise ValueError('scope depth exceeded')
            before=os.fstat(fd)
            key=identity(before)
            traversed.append((fd,before.st_mtime_ns,before.st_ctime_ns))
            if key in seen:raise ValueError('scope directory repeated')
            seen.add(key)
            with os.scandir(fd) as source:
                for entry in source:
                    check();entries+=1
                    if entries>self.MAX_ENTRIES:raise ValueError('scope entry bound exceeded')
                    info=entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode):raise ValueError('scope symlink rejected')
                    if stat.S_ISDIR(info.st_mode):
                        child=open_directory(entry.name,fd)
                        if identity(os.fstat(child))!=identity(info):raise ValueError('scope changed while opening')
                        if entry.name.endswith('.scope'):names.append(entry.name)
                        walk(child,depth+1)
        try:
            check()
            if not self._root.is_absolute() or '..' in self._root.parts:raise ValueError('absolute scope root required')
            fd=open_directory(self._root.anchor)
            for part in self._root.parts[1:]:fd=open_directory(part,fd)
            for part in ('user.slice',f'user-{user_uid}.slice',f'user@{user_uid}.service'):
                fd=open_directory(part,fd)
            walk(fd,0)
            for name,parent,fd,expected in anchors:
                check()
                current=os.stat(name,follow_symlinks=False,**({} if parent is None else {'dir_fd':parent}))
                if not stat.S_ISDIR(current.st_mode) or identity(current)!=expected or identity(os.fstat(fd))!=expected:
                    raise ValueError('scope root or directory changed')
            result=parse_game_scopes('\n'.join(names))
            # Detect directory-entry changes during traversal. This is bounded
            # consistency evidence, not an atomic filesystem snapshot.
            for observed_fd,mtime,ctime in traversed:
                check()
                current=os.fstat(observed_fd)
                if (current.st_mtime_ns,current.st_ctime_ns)!=(mtime,ctime):
                    raise ValueError('scope inventory changed during traversal')
            check()
        except (OSError,ValueError,OverflowError):
            result=GameScopeScan(GameState.UNKNOWN,error='Could not completely inspect bounded Steam game scopes.')
        finally:
            failed=False
            for fd in reversed(descriptors):
                try:os.close(fd)
                except OSError:failed=True
            if failed:result=GameScopeScan(GameState.UNKNOWN,error='Scope descriptor cleanup unconfirmed.')
        try:check()
        except ValueError:result=GameScopeScan(GameState.UNKNOWN,error='Scope observation expired.')
        return result


class SystemdGameScopeDiscovery:
    COMMAND = ("systemctl", *ReadOnlyCommandRunner.SYSTEMCTL_SCOPE_QUERY)

    def __init__(
        self,
        runner: Runner | None = None,
        effective_uid: Callable[[], int] | None = None,
        username_for_uid: Callable[[int], str] | None = None,
        cgroup_root: Path = Path("/sys/fs/cgroup"),
    ) -> None:
        self._runner = runner or ReadOnlyCommandRunner()
        self._effective_uid = effective_uid or getattr(os, "geteuid", lambda: -1)
        self._username_for_uid = username_for_uid or self._resolve_username
        self._cgroup_root = cgroup_root

    @staticmethod
    def _resolve_username(uid: int) -> str:
        import pwd

        return pwd.getpwuid(uid).pw_name

    @classmethod
    def command_for_user(cls, uid: int, username: str) -> tuple[str, ...]:
        return (
            "/usr/bin/runuser",
            "-u",
            username,
            "--",
            "/usr/bin/env",
            f"XDG_RUNTIME_DIR=/run/user/{uid}",
            f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
            "/usr/bin/systemctl",
            *ReadOnlyCommandRunner.SYSTEMCTL_SCOPE_QUERY,
        )

    def scan(self, user_uid: int | None = None) -> GameScopeScan:
        if user_uid is not None:
            cgroup_scan = self._scan_cgroups(user_uid)
            if cgroup_scan is not None:
                return cgroup_scan
        command = self.COMMAND
        if self._effective_uid() == 0 and user_uid is not None:
            try:
                command = self.command_for_user(user_uid, self._username_for_uid(user_uid))
                ReadOnlyCommandRunner.validate(command)
            except (KeyError, ModuleNotFoundError, OSError, ValueError) as error:
                return GameScopeScan(
                    GameState.UNKNOWN,
                    error=f"Could not resolve Gamescope user session: {error}",
                )
        result = self._runner.run(command)
        if not result.ok:
            detail = (
                "command unavailable"
                if result.error
                else f"query exited with status {result.returncode}"
            )
            return GameScopeScan(
                GameState.UNKNOWN,
                error=f"Could not verify Steam game scopes: {detail}",
            )
        return parse_game_scopes(result.stdout)

    def _scan_cgroups(self, user_uid: int) -> GameScopeScan | None:
        """Read current user-unit cgroups without crossing a privilege boundary."""
        user_service = (
            self._cgroup_root
            / "user.slice"
            / f"user-{user_uid}.slice"
            / f"user@{user_uid}.service"
        )
        if not user_service.is_dir():
            return None
        errors: list[OSError] = []
        scope_names: list[str] = []

        def record_error(error: OSError) -> None:
            errors.append(error)

        for _, directories, _ in os.walk(
            user_service, topdown=True, onerror=record_error, followlinks=False
        ):
            scope_names.extend(name for name in directories if name.endswith(".scope"))
        if errors:
            return GameScopeScan(
                GameState.UNKNOWN,
                error="Could not completely inspect Steam game cgroups.",
            )
        return parse_game_scopes("\n".join(scope_names))
