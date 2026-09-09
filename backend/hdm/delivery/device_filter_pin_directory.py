"""Fixed root-only bpffs directory for experimental filter ownership.

Opening a directory does not attach, pin, detach, or authorize a filter. Caller
must serialize pin mutations with the durable journal's operation lock. No
path is accepted from the frontend; the kernel helper receives this held FD.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import stat
import sys

from .device_filter_lifecycle import LaunchBinding


BPF_FS_MAGIC = 0xCAFE4A11


def pin_token(binding: LaunchBinding) -> str:
    if type(binding) is not LaunchBinding:
        raise ValueError("exact launch binding required")
    # Include boot and invocation: an older launch must never name the new pin.
    payload = "\0".join((binding.boot_hash, binding.operation, binding.unit, binding.invocation))
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _root_directory(fd, *, private=False):
    observed = os.fstat(fd)
    if (not stat.S_ISDIR(observed.st_mode) or observed.st_uid != 0
            or observed.st_mode & (0o077 if private else 0o022)):
        raise ValueError("untrusted pin directory")


def _bpffs(fd):
    library = ctypes.CDLL(None, use_errno=True)
    library.fstatfs.argtypes = [ctypes.c_int, ctypes.c_void_p]
    library.fstatfs.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(256)
    if library.fstatfs(fd, ctypes.byref(buffer)) != 0:
        raise OSError(ctypes.get_errno(), "pin filesystem unavailable")
    if ctypes.c_long.from_buffer(buffer).value != BPF_FS_MAGIC:
        raise ValueError("pin directory requires existing bpffs")


class FilterPinDirectory:
    """An authenticated directory descriptor, never a pathname-based authority."""

    def __init__(self, *, create=False):
        self.fd = None
        if sys.platform != "linux" or os.geteuid() != 0:
            raise ValueError("root Linux pin owner required")
        if type(create) is not bool:
            raise ValueError("explicit creation flag required")
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open("/", flags)
        try:
            _root_directory(fd)
            for part in ("sys", "fs", "bpf"):
                child = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = child
                _root_directory(fd)
            _bpffs(fd)
            if create:
                try:
                    os.mkdir("regear-device-filter", 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open("regear-device-filter", flags, dir_fd=fd)
            os.close(fd)
            fd = child
            _root_directory(fd, private=True)
            _bpffs(fd)
            self.fd = fd
        except BaseException:
            os.close(fd)
            raise

    def close(self):
        descriptor, self.fd = self.fd, None
        if descriptor is not None:
            os.close(descriptor)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
