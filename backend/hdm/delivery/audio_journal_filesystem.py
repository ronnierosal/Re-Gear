"""Linux directory, locking and publication helpers for the audio trial journal.

Extracted from the experimental filter journal without its lifecycle or grants.
"""
from contextlib import contextmanager
import ctypes
import os
from pathlib import Path
import stat
import sys
import time

def _acquire_lock(lock, locking, *, wait=time.sleep):
    """Bound contention; a stalled writer cannot hang the launch handshake."""
    for attempt in range(50):
        try:
            locking.flock(lock, locking.LOCK_EX | locking.LOCK_NB)
            return
        except BlockingIOError:
            if attempt == 49:
                raise TimeoutError("audio journal writer busy")
            wait(0.02)


def _publish_exclusive(directory, temporary, target):
    # One atomic no-replace rename avoids a crash window with two hard links
    # to the initial record, which strict recovery would correctly reject.
    library = ctypes.CDLL(None, use_errno=True)
    try:
        rename = library.renameat2
    except AttributeError as error:
        raise OSError("atomic exclusive publication unavailable") from error
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(directory, temporary.encode("ascii"), directory, target.encode("ascii"), 1) != 0:
        raise OSError(ctypes.get_errno(), "exclusive journal publication failed")


class AudioJournalFilesystem:
    def __init__(self, root, *, owner_uid=None, trusted_directory_fd=None):
        """Parents must exist. Fixtures require an explicit trusted directory FD.

        Production checks every ancestor's root ownership/write permissions.
        The caller retains the fixture FD for the journal's lifetime; every
        operation duplicates and validates it. owner_uid alone never relaxes
        production path checks.
        """
        self.root = Path(root)
        if not self.root.is_absolute() or any(part in (".", "..") for part in self.root.parts):
            raise ValueError("absolute journal directory required")
        if owner_uid is not None and (type(owner_uid) is not int or owner_uid < 0):
            raise ValueError("invalid fixture owner")
        if (owner_uid is None) != (trusted_directory_fd is None):
            raise ValueError("fixture requires explicit owner and trusted directory FD")
        if trusted_directory_fd is not None and (type(trusted_directory_fd) is not int or trusted_directory_fd < 0):
            raise ValueError("invalid trusted directory FD")
        self.owner_uid = 0 if owner_uid is None else owner_uid
        self.trusted_directory_fd = trusted_directory_fd

    def _secure(self, fd, *, directory=False):
        info = os.fstat(fd)
        valid_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        if (not valid_type or info.st_uid != self.owner_uid or info.st_mode & 0o022
                or (not directory and (info.st_nlink != 1 or info.st_mode & 0o077))):
            raise ValueError("unsafe journal filesystem object")

    def _directory(self):
        if sys.platform != "linux" or os.geteuid() != self.owner_uid:
            raise ValueError("journal requires its Linux owner")
        if self.trusted_directory_fd is not None:
            fd = os.dup(self.trusted_directory_fd)
            try:
                self._secure(fd, directory=True)
                return fd
            except BaseException:
                os.close(fd)
                raise
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            self._secure(fd, directory=True)
            parts = self.root.parts[1:]
            for part in parts:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
                self._secure(fd, directory=True)
            return fd
        except BaseException:
            os.close(fd)
            raise

    @contextmanager
    def _locked(self):
        import fcntl
        directory = self._directory()
        lock = None
        try:
            lock = os.open("journal.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                           0o600, dir_fd=directory)
            self._secure(lock)
            _acquire_lock(lock, fcntl)
            yield directory
        finally:
            if lock is not None:
                os.close(lock)
            os.close(directory)
