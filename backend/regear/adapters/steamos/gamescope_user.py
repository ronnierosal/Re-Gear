"""Exact Gamescope owner resolution with no username or UID fallback."""

from __future__ import annotations

import re
import stat
from pathlib import Path
from typing import Callable, Protocol

from ...ports.presentation_activation import (
    GamescopeUserContext,
    GamescopeUserResolution,
)
from .gamescope import GamescopeScan


SAFE_USERNAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*[$]?")


class PasswordRecord(Protocol):
    pw_name: str
    pw_uid: int
    pw_gid: int
    pw_dir: str


def _password_for_uid(uid: int) -> PasswordRecord:
    import pwd

    return pwd.getpwuid(uid)


def _session_bus_ready(runtime_directory: Path, bus_path: Path) -> bool:
    try:
        return (
            runtime_directory.is_dir()
            and not runtime_directory.is_symlink()
            and not bus_path.is_symlink()
            and stat.S_ISSOCK(bus_path.stat().st_mode)
        )
    except OSError:
        return False


def resolve_gamescope_user(
    scan: GamescopeScan,
    *,
    password_for_uid: Callable[[int], PasswordRecord] = _password_for_uid,
    session_bus_ready: Callable[[Path, Path], bool] = _session_bus_ready,
) -> GamescopeUserResolution:
    if not scan.ok or scan.process is None or scan.process.uid is None:
        return GamescopeUserResolution(None, "gamescope_identity_unverified")
    uid = scan.process.uid
    if type(uid) is not int or uid <= 0:
        return GamescopeUserResolution(None, "gamescope_user_invalid")
    try:
        record = password_for_uid(uid)
    except (KeyError, ModuleNotFoundError, OSError):
        return GamescopeUserResolution(None, "gamescope_user_unresolved")
    username = str(record.pw_name)
    home = Path(str(record.pw_dir))
    if (
        record.pw_uid != uid
        or type(record.pw_gid) is not int
        or record.pw_gid < 0
        or not SAFE_USERNAME.fullmatch(username)
        or home != Path("/home") / username
    ):
        return GamescopeUserResolution(None, "gamescope_user_mismatch")
    runtime = Path("/run/user") / str(uid)
    bus = runtime / "bus"
    if not session_bus_ready(runtime, bus):
        return GamescopeUserResolution(None, "gamescope_user_bus_unavailable")
    return GamescopeUserResolution(
        GamescopeUserContext(username, uid, record.pw_gid, home, runtime, bus)
    )
