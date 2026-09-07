"""Single-slot cgroup reference retention; no filtering or runtime authority.

Linux v6.16 kernel/bpf/arraymap.c cgroup_fd_array_get_ptr acquires through
cgroup_get_from_fd; put_ptr calls cgroup_put, and map_free clears its entries.
Thus this reference is independent of a device link's offline lifecycle.
Caller authenticates held cgroup FD, bpffs directory, boot and saved map identity
and serializes pin ownership. Recovered map metadata cannot prove slot contents.
No lookup, replacement, unpin, cgroup deletion or launch authorization is exposed.
Source: https://github.com/torvalds/linux/blob/v6.16/kernel/bpf/arraymap.c
UAPI: https://github.com/torvalds/linux/blob/v6.16/include/uapi/linux/bpf.h
"""
import ctypes
import errno
from dataclasses import dataclass
import os
import platform

from .device_filter_kernel import CgroupDeviceLink, InfoAttr, ObjectAttr


@dataclass(frozen=True)
class MapIdentity:
    map_id: int

    def __post_init__(self):
        if type(self.map_id) is not int or not 0 < self.map_id < 2**32:
            raise ValueError('positive map identity required')


class CreateAttr(ctypes.Structure):
    _fields_ = [('map_type', ctypes.c_uint32), ('key_size', ctypes.c_uint32),
                ('value_size', ctypes.c_uint32), ('max_entries', ctypes.c_uint32),
                ('map_flags', ctypes.c_uint32)]


class UpdateAttr(ctypes.Structure):
    _fields_ = [('map_fd', ctypes.c_uint32), ('padding', ctypes.c_uint32),
                ('key', ctypes.c_uint64), ('value', ctypes.c_uint64),
                ('flags', ctypes.c_uint64)]


class MapInfo(ctypes.Structure):
    _fields_ = [('type', ctypes.c_uint32), ('id', ctypes.c_uint32),
                ('key_size', ctypes.c_uint32), ('value_size', ctypes.c_uint32),
                ('max_entries', ctypes.c_uint32), ('map_flags', ctypes.c_uint32)]


class CgroupRetentionMap:
    def __init__(self, *, syscall=None, close_fd=os.close):
        if platform.system() != 'Linux' or platform.machine() != 'x86_64':
            raise RuntimeError('cgroup retention requires Linux x86_64')
        if syscall is None:
            library = ctypes.CDLL(None, use_errno=True)
            syscall = library.syscall
            syscall.restype = ctypes.c_long
        self._syscall, self._close_fd = syscall, close_fd
        self.map_fd = None

    def _call(self, command, attr):
        result = self._syscall(321, command, ctypes.byref(attr), ctypes.sizeof(attr))
        if result < 0:
            raise OSError(ctypes.get_errno(), 'bounded cgroup retention operation failed')
        return int(result)

    def create(self, cgroup_fd):
        if self.map_fd is not None:
            raise RuntimeError('map already owned')
        CgroupDeviceLink._fd(cgroup_fd)
        self.map_fd = self._call(0, CreateAttr(map_type=8, key_size=4, value_size=4, max_entries=1))
        try:
            before = self.identity()
            key, value = ctypes.c_uint32(0), ctypes.c_uint32(cgroup_fd)
            self._call(2, UpdateAttr(map_fd=self.map_fd, key=ctypes.addressof(key),
                                    value=ctypes.addressof(value), flags=0))
            if self.identity() != before:
                raise ValueError('created map identity changed')
            return before
        except BaseException:
            self.close()
            raise

    def identity(self):
        if self.map_fd is None:
            raise ValueError('no retention map owned')
        info = MapInfo()
        attr = InfoAttr(bpf_fd=self.map_fd, info_len=ctypes.sizeof(info), info=ctypes.addressof(info))
        self._call(15, attr)
        if (attr.info_len < ctypes.sizeof(info)
                or (info.type,info.key_size,info.value_size,info.max_entries,info.map_flags)!=(8,4,4,1,0)):
            raise ValueError('unexpected retention map metadata')
        return MapIdentity(info.id)

    def pin(self, directory_fd, token, expected):
        path = CgroupDeviceLink._object_path(directory_fd, token)
        if type(expected) is not MapIdentity or self.identity() != expected:
            raise ValueError('retention pin identity mismatch')
        self._call(6, ObjectAttr(pathname=ctypes.addressof(path), bpf_fd=self.map_fd))

    def recover(self, directory_fd, token, expected):
        if self.map_fd is not None:
            raise RuntimeError('recovery requires empty map ownership')
        if type(expected) is not MapIdentity:
            raise ValueError('typed expected map identity required')
        path = CgroupDeviceLink._object_path(directory_fd, token)
        self.map_fd = self._call(7, ObjectAttr(pathname=ctypes.addressof(path)))
        try:
            if self.identity() != expected:
                raise ValueError('recovered retention identity mismatch')
        except BaseException:
            self.close()
            raise
        return self.map_fd

    def close(self):
        descriptor, self.map_fd = self.map_fd, None
        if descriptor is not None:
            self._close_fd(descriptor)

    def release_entry(self, expected):
        """Explicit slot release; caller first proves no receive filter remains.

        False means ENOENT only. Neither result is disconnect clearance.
        Close never invokes this mutation implicitly.
        """
        if type(expected) is not MapIdentity or self.identity() != expected:
            raise ValueError('retention release identity mismatch')
        key = ctypes.c_uint32(0)
        try:
            self._call(3, UpdateAttr(map_fd=self.map_fd, key=ctypes.addressof(key)))
        except OSError as error:
            if error.errno == errno.ENOENT:
                return False
            raise
        return True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
