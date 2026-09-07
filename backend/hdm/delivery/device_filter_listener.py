"""Exclusive protected listener lifecycle, without request or grant authority.

Production parent must already exist. Existing entries are never removed to
make binding succeed. Caller supplies the independently trusted session group.
"""
import math
import os
import socket
import stat
import sys
import time


class FilterListener:
    def __init__(self, session_gid, *, owner_uid=None, trusted_directory_fd=None):
        if sys.platform != "linux":
            raise ValueError("Linux listener required")
        if type(session_gid) is not int or session_gid < 0:
            raise ValueError("trusted session group required")
        if (owner_uid is None) != (trusted_directory_fd is None):
            raise ValueError("fixture requires owner and held directory together")
        self.owner = 0 if owner_uid is None else owner_uid
        if type(self.owner) is not int or self.owner < 0 or os.geteuid() != self.owner:
            raise ValueError("listener owner required")
        self.directory = None
        self.connection = None
        self.identity = None
        try:
            if trusted_directory_fd is not None:
                if type(trusted_directory_fd) is not int or trusted_directory_fd < 0:
                    raise ValueError("invalid fixture directory")
                self.directory = os.dup(trusted_directory_fd)
                self._secure_directory(self.directory)
            else:
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                self.directory = os.open("/", flags)
                self._secure_directory(self.directory)
                for part in ("run", "regear", "device-filter"):
                    child = os.open(part, flags, dir_fd=self.directory)
                    os.close(self.directory)
                    self.directory = child
                    self._secure_directory(child)
            self.connection = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            # Kernel bind is exclusive. Do not unlink anything before binding.
            self.connection.bind(f"/proc/self/fd/{self.directory}/launch.sock")
            info = os.stat("launch.sock", dir_fd=self.directory, follow_symlinks=False)
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != self.owner:
                raise ValueError("bound socket identity unavailable")
            self.identity = (info.st_dev, info.st_ino)
            os.chown("launch.sock", self.owner, session_gid, dir_fd=self.directory, follow_symlinks=False)
            os.chmod("launch.sock", 0o660, dir_fd=self.directory, follow_symlinks=False)
            info = self._owned_socket()
            if info.st_gid != session_gid or stat.S_IMODE(info.st_mode) != 0o660:
                raise ValueError("listener permissions unverified")
            self.connection.listen(1)
        except BaseException:
            self.close()
            raise

    def _secure_directory(self, fd):
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != self.owner or info.st_mode & 0o022:
            raise ValueError("untrusted listener directory")

    def _owned_socket(self):
        self._secure_directory(self.directory)
        info = os.stat("launch.sock", dir_fd=self.directory, follow_symlinks=False)
        if (self.identity is None or not stat.S_ISSOCK(info.st_mode)
                or info.st_uid != self.owner or (info.st_dev, info.st_ino) != self.identity):
            raise ValueError("listener socket replaced or ownership changed")
        return info

    def accept(self, *, deadline, clock=time.monotonic):
        return self._accept(deadline=deadline, clock=clock, maximum_wait=5)

    def accept_waiting(self, *, deadline, clock=time.monotonic):
        """Wait for a restarted session; this does not extend handshake time."""
        return self._accept(deadline=deadline, clock=clock, maximum_wait=90)

    def _accept(self, *, deadline, clock, maximum_wait):
        now = clock()
        if (type(deadline) not in (int, float) or type(now) not in (int, float)
                or not math.isfinite(deadline) or not math.isfinite(now)
                or now < 0 or not 0 < deadline - now <= maximum_wait):
            raise TimeoutError("listener deadline invalid or expired")
        self._owned_socket()
        self.connection.settimeout(deadline - now)
        accepted, _ = self.connection.accept()
        try:
            after = clock()
            if (type(after) not in (int, float) or not math.isfinite(after)
                    or after < now or after >= deadline):
                raise TimeoutError("listener deadline expired")
            return accepted
        except BaseException:
            accepted.close()
            raise

    def close(self):
        try:
            if self.connection is not None:
                connection, self.connection = self.connection, None
                connection.close()
        finally:
            if self.directory is not None:
                try:
                    if self.identity is not None:
                        self._owned_socket()
                        os.unlink("launch.sock", dir_fd=self.directory)
                        self.identity = None
                finally:
                    directory, self.directory = self.directory, None
                    os.close(directory)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
