"""One Linux process may own Re-Gear TDP writes in the shared state directory."""

from __future__ import annotations

import os
import stat
from pathlib import Path


class FileTdpWriterLease:
    def __init__(self, state_root: Path) -> None:
        if not state_root.is_absolute():
            raise ValueError("TDP lease root must be absolute")
        self._root = state_root
        self._descriptor: int | None = None

    @property
    def held(self) -> bool:
        return self._descriptor is not None

    def acquire(self) -> bool:
        if self.held:
            return True
        try:
            import fcntl
            root = self._root.lstat()
            if not stat.S_ISDIR(root.st_mode) or root.st_uid != os.geteuid() or root.st_mode & 0o022:
                return False
            descriptor = os.open(self._root / "tdp-writer.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022:
                    raise ValueError("Invalid TDP lease file")
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except Exception:
                os.close(descriptor)
                return False
            self._descriptor = descriptor
            return True
        except (ImportError, OSError, ValueError):
            return False

    def close(self) -> None:
        if self._descriptor is not None:
            os.close(self._descriptor)
            self._descriptor = None
