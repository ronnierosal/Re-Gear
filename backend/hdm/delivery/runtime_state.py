"""Hardened fixed state directory for root-owned Re-Gear control state."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from pathlib import Path


DEFAULT_RUNTIME_STATE_ROOT = Path("/var/lib/handheld-dock-mode")
STATE_DIRECTORY_MODE = 0o700


class RootOwnedRuntimeState:
    """Create or validate one non-symlink, root-only, fixed state directory."""

    def __init__(
        self,
        state_root: Path = DEFAULT_RUNTIME_STATE_ROOT,
        *,
        platform_name: str = os.name,
        effective_uid: Callable[[], int] | None = None,
        lstat: Callable[[Path], os.stat_result] | None = None,
    ) -> None:
        if not state_root.is_absolute() or state_root == Path(state_root.anchor):
            raise ValueError("runtime state root must be a narrow absolute path")
        if state_root.name != "handheld-dock-mode":
            raise ValueError("runtime state root must use the fixed HDM directory name")
        self._root = state_root
        self._platform_name = platform_name
        self._effective_uid = effective_uid or getattr(os, "geteuid", lambda: -1)
        self._lstat = lstat or (lambda path: path.lstat())

    @property
    def path(self) -> Path:
        return self._root

    def ensure(self) -> Path:
        if self._platform_name != "posix" or self._effective_uid() != 0:
            raise ValueError("runtime state root requires a POSIX root process")
        parent = self._root.parent
        self._validate_parent(parent)
        try:
            os.mkdir(self._root, STATE_DIRECTORY_MODE)
            os.chmod(self._root, STATE_DIRECTORY_MODE)
            self._sync_directory(parent)
        except FileExistsError:
            pass
        self._validate_root()
        return self._root

    def _validate_parent(self, parent: Path) -> None:
        try:
            metadata = self._lstat(parent)
        except OSError as error:
            raise ValueError("runtime state parent is unavailable") from error
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("runtime state parent must be a real directory")
        if metadata.st_uid != 0:
            raise ValueError("runtime state parent must be root owned")
        if metadata.st_mode & 0o022:
            raise ValueError("runtime state parent cannot be group/world writable")

    def _validate_root(self) -> None:
        try:
            metadata = self._lstat(self._root)
        except OSError as error:
            raise ValueError("runtime state root is unavailable") from error
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("runtime state root must be a real directory")
        if metadata.st_uid != 0:
            raise ValueError("runtime state root must be root owned")
        if stat.S_IMODE(metadata.st_mode) != STATE_DIRECTORY_MODE:
            raise ValueError("runtime state root must use mode 0700")

    @staticmethod
    def _sync_directory(path: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)
