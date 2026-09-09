"""Reversible fixed Gamescope shim integration with conservative conflict checks."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..ports.presentation_activation import GamescopeUserContext
from .user_directory import UserDirectory


DROPIN_NAME = "90-handheld-dock-mode.conf"
MAX_DROPIN_BYTES = 16 * 1024
SHIM_MARKER = "Handheld Dock Mode Gamescope argument shim"
#: The first line of every managed drop-in this project has ever written.
MANAGED_HEADER = "# Managed by Handheld Dock Mode. Remove only through HDM."
#: Recovers the shim directory from a candidate drop-in so it can be
#: re-rendered and compared exactly. Matching only extracts; it decides
#: nothing on its own.
MANAGED_PATH_LINE = re.compile(
    r'^Environment="PATH=(?P<shim>[^:"]+):/usr/local/sbin:',
    re.MULTILINE,
)
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
        set_owner: Callable[[Path | int, int, int], None] | None = None,
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
        self._set_owner = set_owner
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

    def _render(self, shim_directory: str) -> str:
        """Render the managed drop-in for one shim directory."""
        state_root = self._path_text(self._state_root)
        path_value = (
            f"{shim_directory}:/usr/local/sbin:/usr/local/bin:"
            "/usr/bin:/usr/sbin:/bin:/sbin"
        )
        return (
            f"{MANAGED_HEADER}\n"
            "[Service]\n"
            f'Environment="PATH={path_value}"\n'
            f'Environment="HDM_STATE_ROOT={state_root}"\n'
        )

    def expected_text(self) -> str:
        return self._render(self._path_text(self._shim.parent))

    def _stale_managed_rendering(self, actual: str) -> bool:
        """Whether `actual` is one of our own renderings for another plugin path.

        A plugin rename moves the shim directory, so a drop-in this project
        wrote itself stops matching `expected_text` and is indistinguishable,
        by equality alone, from a file the player edited. Refusing to
        overwrite an edited file is correct and stays; this narrows that
        refusal to files we cannot account for.

        Recognition is deliberately exact rather than fuzzy: the candidate
        must equal a rendering of this same template for some other shim
        directory, with our state root and our fixed system PATH tail. Any
        added line, reordered key, altered tail or foreign state root fails
        to match and is still treated as modified.
        """
        match = MANAGED_PATH_LINE.search(actual)
        if match is None:
            return False
        candidate = match.group("shim")
        if not SAFE_POSIX_PATH.fullmatch(candidate):
            return False
        return actual == self._render(candidate)

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
                # Ours, for a plugin path that has since moved, versus one we
                # cannot account for. Only the first is safe to rewrite.
                error = (
                    "managed_dropin_stale"
                    if self._stale_managed_rendering(actual or "")
                    else "managed_dropin_modified"
                )
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
            # A stale rendering is the one error activation may resolve: the
            # file is ours and only its plugin path moved. Every other error
            # still refuses, including a file we cannot account for.
            if before.error_code and before.error_code != "managed_dropin_stale":
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
                if before.error_code == "managed_dropin_stale":
                    # The delivery writer publishes by exclusive create and
                    # cannot replace, deliberately. Migrating therefore reuses
                    # the same compare-and-remove primitive deactivation uses:
                    # the stale file is removed only while its content is still
                    # exactly the rendering that was recognised, so a file that
                    # changed between the check and the act is refused rather
                    # than overwritten.
                    self._remove_exact(self._read_required(self._target))
                if not before.installed or (
                    before.error_code == "managed_dropin_stale"
                ):
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
                with UserDirectory(self._dropin_root, self._user.uid, self._user.gid,
                                   create_from=self._user.home) as directory:
                    directory.remove_matching(self.DROPIN_NAME,
                                              self.expected_text().encode("utf-8"),
                                              MAX_DROPIN_BYTES)
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
        with UserDirectory(self._user.home / relative, self._user.uid, self._user.gid,
                           create_from=self._user.home, create=True,
                           final_mode=final_mode, set_owner=self._set_owner):
            pass

    def _remove_exact(self, expected: str) -> None:
        """Remove the managed drop-in only while it still holds `expected`.

        Shares deactivation's primitive rather than introducing a second way to
        unlink a delivered file: it re-reads through a pinned descriptor,
        checks ownership and content, and confirms the name still refers to the
        same inode before unlinking.
        """
        with UserDirectory(self._dropin_root, self._user.uid, self._user.gid,
                           create_from=self._user.home) as directory:
            directory.remove_matching(
                self.DROPIN_NAME, expected.encode("utf-8"), MAX_DROPIN_BYTES
            )

    def _atomic_write(self, path: Path, value: str) -> None:
        data = value.encode("utf-8")
        if len(data) > MAX_DROPIN_BYTES:
            raise ValueError("managed drop-in exceeds its bound")
        with UserDirectory(path.parent, self._user.uid, self._user.gid,
                           create_from=self._user.home) as directory:
            directory.publish(path.name, data, 0o644)

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
