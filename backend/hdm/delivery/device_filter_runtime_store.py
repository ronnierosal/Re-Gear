"""Exclusive immutable runtime publication; no activation or runtime retirement."""
import ctypes
from dataclasses import dataclass
import os
import stat
import sys
import uuid

from .device_filter_bootstrap import ROOT, manifest_from_bytes, runtime_identity, shim_bytes
from .device_filter_runtime_bundle import RuntimeBundle


@dataclass(frozen=True)
class RuntimePublication:
    digest: str
    path: str
    session_sha256: str


def _validate(bundle):
    if type(bundle) is not RuntimeBundle or runtime_identity(bundle.path) != bundle.digest:
        raise ValueError("invalid runtime bundle identity")
    manifest = manifest_from_bytes(bundle.archive, bundle.digest)
    if (bundle.gamescope_shim != shim_bytes(bundle.path)
            or bundle.steam_argv != ("/usr/bin/python3", "-I", bundle.path, "steam")
            or bundle.session_argv != ("/usr/bin/python3", "-I", bundle.path, "session")):
        raise ValueError("runtime launch arguments changed")
    return manifest


def _rename_exclusive(directory, source, target):
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(directory, source.encode("ascii"), directory, target.encode("ascii"), 1) != 0:
        raise OSError(ctypes.get_errno(), "exclusive runtime publication failed")


class RuntimeStore:
    def __init__(self, *, owner_uid=None, trusted_directory_fd=None):
        if (owner_uid is None) != (trusted_directory_fd is None):
            raise ValueError("fixture requires owner and trusted directory")
        self.owner = 0 if owner_uid is None else owner_uid
        if type(self.owner) is not int or self.owner < 0:
            raise ValueError("invalid owner")
        if trusted_directory_fd is not None and (type(trusted_directory_fd) is not int or trusted_directory_fd < 0):
            raise ValueError("invalid held directory")
        self.trusted = trusted_directory_fd

    def _directory_check(self, fd):
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != self.owner or info.st_mode & 0o022:
            raise ValueError("unsafe runtime directory")

    def _directory(self):
        if sys.platform != "linux" or os.geteuid() != self.owner:
            raise ValueError("Linux runtime owner required")
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.dup(self.trusted) if self.trusted is not None else os.open("/", flags)
        try:
            self._directory_check(fd)
            if self.trusted is None:
                for part in ROOT.split("/")[1:]:
                    child = os.open(part, flags, dir_fd=fd)
                    os.close(fd)
                    fd = child
                    self._directory_check(fd)
            return fd
        except BaseException:
            os.close(fd)
            raise

    def _write(self, directory, name, raw, mode):
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            position = 0
            while position < len(raw):
                count = os.write(fd, raw[position:])
                if count <= 0:
                    raise OSError("short runtime write")
                position += count
            os.fchmod(fd, mode)
            os.fsync(fd)
        finally:
            os.close(fd)

    def _read(self, directory, name, expected, mode):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != self.owner
                    or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != mode
                    or info.st_size != len(expected)):
                raise ValueError("runtime file identity or mode changed")
            raw = bytearray()
            while len(raw) <= len(expected):
                chunk = os.read(fd, min(65536, len(expected) + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
            if bytes(raw) != expected:
                raise ValueError("runtime readback changed")
        finally:
            os.close(fd)

    def _verify_at(self, parent, name, bundle):
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directory = os.open(name, flags, dir_fd=parent)
        try:
            self._directory_check(directory)
            self._read(directory, "runtime.pyz", bundle.archive, 0o444)
            bin_fd = os.open("bin", flags, dir_fd=directory)
            try:
                self._directory_check(bin_fd)
                self._read(bin_fd, "gamescope", bundle.gamescope_shim, 0o555)
            finally:
                os.close(bin_fd)
        finally:
            os.close(directory)

    def verify(self, bundle):
        manifest = _validate(bundle)
        parent = self._directory()
        try:
            self._verify_at(parent, bundle.digest, bundle)
            # Reconcile a prior rename whose parent fsync failed.
            os.fsync(parent)
        finally:
            os.close(parent)
        return RuntimePublication(bundle.digest, bundle.path, manifest["session_sha256"])

    def publish(self, bundle):
        manifest = _validate(bundle)
        parent = self._directory()
        temporary = ".pending-" + uuid.uuid4().hex
        stage = bin_fd = None
        created = False
        published = False
        try:
            os.mkdir(temporary, 0o700, dir_fd=parent)
            created = True
            stage = os.open(temporary, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.mkdir("bin", 0o700, dir_fd=stage)
            bin_fd = os.open("bin", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=stage)
            self._write(stage, "runtime.pyz", bundle.archive, 0o444)
            self._write(bin_fd, "gamescope", bundle.gamescope_shim, 0o555)
            os.fchmod(bin_fd, 0o755)
            os.fsync(bin_fd)
            os.fchmod(stage, 0o755)
            os.fsync(stage)
            self._verify_at(parent, temporary, bundle)
            _rename_exclusive(parent, temporary, bundle.digest)
            published = True
            os.fsync(parent)
            self._verify_at(parent, bundle.digest, bundle)
            return RuntimePublication(bundle.digest, bundle.path, manifest["session_sha256"])
        finally:
            try:
                if created and not published and stage is not None:
                    # Only exact fixed entries inside our held fresh directory.
                    for fd, name in ((bin_fd, "gamescope"), (stage, "runtime.pyz")):
                        if fd is not None:
                            try:
                                os.unlink(name, dir_fd=fd)
                            except FileNotFoundError:
                                pass
                    if bin_fd is not None:
                        os.rmdir("bin", dir_fd=stage)
                    info = os.stat(temporary, dir_fd=parent, follow_symlinks=False)
                    held = os.fstat(stage)
                    if (info.st_dev, info.st_ino) != (held.st_dev, held.st_ino):
                        raise ValueError("temporary directory identity changed")
                    os.rmdir(temporary, dir_fd=parent)
            finally:
                for fd in (bin_fd, stage, parent):
                    if fd is not None:
                        os.close(fd)
