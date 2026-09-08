"""Reversible fixed Gamescope shim integration with conservative conflict checks."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..ports.presentation_activation import GamescopeUserContext


DROPIN_NAME = "90-handheld-dock-mode.conf"
MAX_DROPIN_BYTES = 16 * 1024
SHIM_MARKER = "Handheld Dock Mode Gamescope argument shim"
SAFE_POSIX_PATH = re.compile(r"^/[A-Za-z0-9_.@+/-]+$")


@dataclass(frozen=True, slots=True)
class GamescopeIntegrationStatus:
    installed: bool
    matches: bool
    shim_ready: bool
    state_root_ready: bool
    conflicts: tuple[str, ...] = ()
    error_code: str = ""

    @property
    def ready(self) -> bool:
        return (
            self.installed
            and self.matches
            and self.shim_ready
            and self.state_root_ready
            and not self.conflicts
            and not self.error_code
        )


@dataclass(frozen=True, slots=True)
class GamescopeIntegrationResult:
    changed: bool
    status: GamescopeIntegrationStatus

    @property
    def ok(self) -> bool:
        return self.status.ready and not self.status.error_code


class GamescopeIntegrationStore:
    SERVICE = 'gamescope-session.service'
    SHIM_NAME = 'gamescope'
    SHIM_MARKER = SHIM_MARKER
    DROPIN_NAME = DROPIN_NAME
    def __init__(
        self,
        *,
        plugin_root: Path,
        user: GamescopeUserContext,
        effective_uid: Callable[[], int] | None = None,
        set_owner: Callable[[Path, int, int], None] | None = None,
    ) -> None:
        if not plugin_root.is_absolute() or not user.home.is_absolute():
            raise ValueError("Gamescope integration paths must be absolute")
        self._plugin_root = plugin_root
        self._user = user
        self._shim = plugin_root / "bin" / self.SHIM_NAME
        self._state_root = user.home / ".local" / "share" / "handheld-dock-mode"
        self._dropin_root = (
            user.home
            / ".config"
            / "systemd"
            / "user"
            / (self.SERVICE + '.d')
        )
        self._target = self._dropin_root / self.DROPIN_NAME
        self._effective_uid = effective_uid or getattr(os, "geteuid", lambda: -1)
        self._set_owner = set_owner or self._chown
        self._lock = threading.Lock()
        self._validate_rendered_paths()

    @property
    def state_root(self) -> Path:
        return self._state_root

    @property
    def user(self) -> GamescopeUserContext:
        return self._user

    @property
    def target(self) -> Path:
        return self._target

    def expected_text(self) -> str:
        shim_directory = self._path_text(self._shim.parent)
        state_root = self._path_text(self._state_root)
        path_value = (
            f"{shim_directory}:/usr/local/sbin:/usr/local/bin:"
            "/usr/bin:/usr/sbin:/bin:/sbin"
        )
        return (
            "# Managed by Handheld Dock Mode. Remove only through HDM.\n"
            "[Service]\n"
            f'Environment="PATH={path_value}"\n'
            f'Environment="HDM_STATE_ROOT={state_root}"\n'
        )

    def activation_fingerprint(self) -> str:
        if not self._shim_ready():
            raise ValueError("Gamescope shim is unavailable")
        data = self._shim.read_bytes()
        if len(data) > MAX_DROPIN_BYTES:
            raise ValueError("Gamescope shim exceeds its bound")
        digest = hashlib.sha256()
        digest.update(data)
        digest.update(b"\0")
        digest.update(self.expected_text().encode("utf-8"))
        return digest.hexdigest()

    def status(self) -> GamescopeIntegrationStatus:
        try:
            conflicts = self._conflicts()
            actual = self._read_optional(self._target)
            installed = actual is not None
            matches = actual == self.expected_text() if installed else False
            managed_safe = self._managed_file_safe(self._target) if installed else True
            shim_ready = self._shim_ready()
            state_ready = self._owned_real_directory(self._state_root)
            error = ""
            if installed and not matches:
                error = "managed_dropin_modified"
            elif installed and not managed_safe:
                error = "managed_dropin_unsafe"
            elif conflicts:
                error = "path_override_conflict"
            return GamescopeIntegrationStatus(
                installed,
                matches,
                shim_ready,
                state_ready,
                conflicts,
                error,
            )
        except (OSError, UnicodeDecodeError, ValueError):
            return GamescopeIntegrationStatus(
                False, False, False, False, error_code="inspection_failed"
            )

    def activate(self) -> GamescopeIntegrationResult:
        if self._effective_uid() != 0:
            return GamescopeIntegrationResult(
                False,
                GamescopeIntegrationStatus(
                    False, False, False, False, error_code="root_required"
                ),
            )
        with self._lock:
            before = self.status()
            if before.ready:
                return GamescopeIntegrationResult(False, before)
            if before.error_code:
                return GamescopeIntegrationResult(False, before)
            if not before.shim_ready:
                return GamescopeIntegrationResult(
                    False,
                    GamescopeIntegrationStatus(
                        before.installed,
                        before.matches,
                        False,
                        before.state_root_ready,
                        before.conflicts,
                        "shim_unavailable",
                    ),
                )
            try:
                self._ensure_relative_directory(
                    Path(".local") / "share" / "handheld-dock-mode", 0o700
                )
                self._ensure_relative_directory(
                    Path(".config")
                    / "systemd"
                    / "user"
                    / (self.SERVICE + '.d'),
                    0o700,
                )
                if not before.installed:
                    self._atomic_write(self._target, self.expected_text())
            except (OSError, ValueError):
                return GamescopeIntegrationResult(
                    False,
                    GamescopeIntegrationStatus(
                        False, False, True, False, error_code="activation_failed"
                    ),
                )
            after = self.status()
            return GamescopeIntegrationResult(True, after)

    def deactivate(self) -> GamescopeIntegrationResult:
        if self._effective_uid() != 0:
            return GamescopeIntegrationResult(
                False,
                GamescopeIntegrationStatus(
                    False, False, False, False, error_code="root_required"
                ),
            )
        with self._lock:
            before = self.status()
            if not before.installed:
                return GamescopeIntegrationResult(False, before)
            if not before.matches:
                return GamescopeIntegrationResult(False, before)
            try:
                if self._target.is_symlink():
                    raise ValueError("managed drop-in cannot be a symlink")
                self._target.unlink()
                self._sync_directory(self._dropin_root)
            except (OSError, ValueError):
                return GamescopeIntegrationResult(
                    False,
                    GamescopeIntegrationStatus(
                        True,
                        True,
                        before.shim_ready,
                        before.state_root_ready,
                        before.conflicts,
                        "deactivation_failed",
                    ),
                )
            return GamescopeIntegrationResult(True, self.status())

    def _validate_rendered_paths(self) -> None:
        self._path_text(self._shim.parent)
        self._path_text(self._state_root)
        if self._user.home == Path(self._user.home.anchor):
            raise ValueError("Gamescope user home is too broad")

    @staticmethod
    def _path_text(path: Path) -> str:
        value = path.as_posix()
        if os.name == "nt" and re.fullmatch(r"[A-Za-z]:/[A-Za-z0-9_.@+ /-]+", value):
            return value
        if not SAFE_POSIX_PATH.fullmatch(value):
            raise ValueError("Gamescope integration path is unsafe")
        return value

    def _shim_ready(self) -> bool:
        try:
            if self._shim.is_symlink() or not self._shim.is_file():
                return False
            mode = self._shim.stat().st_mode
            if os.name != "nt" and not mode & stat.S_IXUSR:
                return False
            data = self._shim.read_bytes()
            return len(data) <= MAX_DROPIN_BYTES and self.SHIM_MARKER.encode() in data
        except OSError:
            return False

    def _conflicts(self) -> tuple[str, ...]:
        if not self._dropin_root.exists():
            return ()
        if not self._owned_real_directory(self._dropin_root):
            raise ValueError("Gamescope drop-in root is unsafe")
        conflicts: list[str] = []
        for candidate in sorted(self._dropin_root.glob("*.conf")):
            if candidate == self._target:
                continue
            raw = self._read_required(candidate)
            for line in raw.splitlines():
                normalized = line.strip()
                if re.match(r"^EnvironmentFile\s*=", normalized):
                    conflicts.append(candidate.name)
                    break
                directive = re.match(
                    r"^(Environment|PassEnvironment|UnsetEnvironment)\s*=\s*(.*)$",
                    normalized,
                )
                if directive and re.search(
                    r"(?:^|[\s\"'])PATH(?:=|[\s\"']|$)", directive.group(2)
                ):
                    conflicts.append(candidate.name)
                    break
        return tuple(conflicts)

    def _read_optional(self, path: Path) -> str | None:
        try:
            return self._read_required(path)
        except FileNotFoundError:
            return None

    @staticmethod
    def _read_required(path: Path) -> str:
        if path.is_symlink():
            raise ValueError("Gamescope integration file cannot be a symlink")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as source:
            data = source.read(MAX_DROPIN_BYTES + 1)
        if len(data) > MAX_DROPIN_BYTES:
            raise ValueError("Gamescope integration file exceeds its bound")
        return data.decode("utf-8")

    def _ensure_relative_directory(self, relative: Path, final_mode: int) -> None:
        if not self._owned_real_directory(self._user.home):
            raise ValueError("Gamescope user home is unsafe")
        current = self._user.home
        parts = relative.parts
        for index, part in enumerate(parts):
            if part in {"", ".", ".."}:
                raise ValueError("Gamescope integration directory is unsafe")
            current = current / part
            mode = final_mode if index == len(parts) - 1 else 0o700
            if current.exists():
                if not self._owned_real_directory(current):
                    raise ValueError("Gamescope integration directory is unsafe")
            else:
                current.mkdir(mode=mode)
                self._own(current)

    def _atomic_write(self, path: Path, value: str) -> None:
        if path.is_symlink() or path.exists():
            raise ValueError("managed drop-in already exists")
        data = value.encode("utf-8")
        if len(data) > MAX_DROPIN_BYTES:
            raise ValueError("managed drop-in exceeds its bound")
        temporary = path.parent / f".{self.DROPIN_NAME}.{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as target:
                target.write(data)
                target.flush()
                os.fsync(target.fileno())
            os.chmod(temporary, 0o644)
            self._own(temporary)
            os.replace(temporary, path)
            self._sync_directory(path.parent)
        except Exception:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    @staticmethod
    def _real_directory(path: Path) -> bool:
        return path.is_dir() and not path.is_symlink()

    def _owned_real_directory(self, path: Path) -> bool:
        if not self._real_directory(path):
            return False
        try:
            return os.name == "nt" or path.stat().st_uid == self._user.uid
        except (AttributeError, OSError):
            return False

    def _managed_file_safe(self, path: Path) -> bool:
        try:
            value = path.stat(follow_symlinks=False)
            return (
                not path.is_symlink()
                and stat.S_ISREG(value.st_mode)
                and (os.name == "nt" or value.st_uid == self._user.uid)
                and (
                    os.name == "nt"
                    or not value.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
                )
            )
        except (AttributeError, OSError):
            return False

    def _own(self, path: Path) -> None:
        self._set_owner(path, self._user.uid, self._user.gid)

    @staticmethod
    def _chown(path: Path, uid: int, gid: int) -> None:
        os.chown(path, uid, gid, follow_symlinks=False)

    @staticmethod
    def _sync_directory(path: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
