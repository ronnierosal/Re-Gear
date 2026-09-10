"""Fixed Linux/x86_64 cgroup-device BPF-link fixture primitives.

Caller must authenticate cgroup authority and the held trusted bpffs directory
FD, including ownership/mount/path and durable expected identity. This module
does not establish those facts. Pinning persists a link after close; close never
unpins. Explicit detach affects only the held, revalidated link object.
UAPI: https://github.com/torvalds/linux/blob/v6.16/include/uapi/linux/bpf.h
"""

import ctypes
import errno
import os
import platform
import re
from dataclasses import dataclass


class DirectPinAbsent(FileNotFoundError):
    """BPF_OBJ_GET ENOENT only, never an identity or cleanup error."""


class LoadAttr(ctypes.Structure):
    _fields_ = [("prog_type", ctypes.c_uint32), ("insn_cnt", ctypes.c_uint32),
                ("insns", ctypes.c_uint64), ("license", ctypes.c_uint64),
                ("log_level", ctypes.c_uint32), ("log_size", ctypes.c_uint32),
                ("log_buf", ctypes.c_uint64), ("kern_version", ctypes.c_uint32),
                ("prog_flags", ctypes.c_uint32), ("prog_name", ctypes.c_char * 16),
                ("prog_ifindex", ctypes.c_uint32),
                ("expected_attach_type", ctypes.c_uint32)]


class LinkAttr(ctypes.Structure):
    _fields_ = [("prog_fd", ctypes.c_uint32), ("target_fd", ctypes.c_uint32),
                ("attach_type", ctypes.c_uint32), ("flags", ctypes.c_uint32)]


class QueryAttr(ctypes.Structure):
    _fields_ = [("target_fd", ctypes.c_uint32), ("attach_type", ctypes.c_uint32),
                ("query_flags", ctypes.c_uint32), ("attach_flags", ctypes.c_uint32),
                ("prog_ids", ctypes.c_uint64), ("prog_cnt", ctypes.c_uint32),
                ("padding", ctypes.c_uint32), ("prog_attach_flags", ctypes.c_uint64)]


class InfoAttr(ctypes.Structure):
    _fields_ = [("bpf_fd", ctypes.c_uint32), ("info_len", ctypes.c_uint32),
                ("info", ctypes.c_uint64)]


class ObjectAttr(ctypes.Structure):
    _fields_ = [("pathname", ctypes.c_uint64), ("bpf_fd", ctypes.c_uint32),
                ("file_flags", ctypes.c_uint32)]


class DetachAttr(ctypes.Structure):
    _fields_ = [("link_fd", ctypes.c_uint32), ("reserved", ctypes.c_uint32)]


class LinkInfo(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("id", ctypes.c_uint32),
                ("prog_id", ctypes.c_uint32), ("padding", ctypes.c_uint32),
                ("cgroup_id", ctypes.c_uint64), ("attach_type", ctypes.c_uint32)]


@dataclass(frozen=True)
class LinkIdentity:
    link_id: int
    program_id: int
    cgroup_id: int

    def __post_init__(self):
        for value, bits in ((self.link_id, 32), (self.program_id, 32), (self.cgroup_id, 64)):
            if type(value) is not int or not 0 < value < 1 << bits:
                raise ValueError("invalid link identity")


class CgroupDeviceLink:
    """Owns program and link descriptors, never the caller's cgroup descriptor."""

    def __init__(self, *, syscall=None, close_fd=None):
        if platform.system() != "Linux" or platform.machine() != "x86_64":
            raise RuntimeError("fixture requires Linux x86_64")
        if syscall is None:
            library = ctypes.CDLL(None, use_errno=True)
            syscall = library.syscall
            syscall.restype = ctypes.c_long
        self._syscall = syscall
        self._close_fd = close_fd or os.close
        self.program_fd = None
        self.link_fd = None

    def _call(self, command, attr):
        result = self._syscall(321, command, ctypes.byref(attr), ctypes.sizeof(attr))
        if result < 0:
            raise OSError(ctypes.get_errno(), "bounded BPF fixture operation failed")
        return int(result)

    @staticmethod
    def _fd(value):
        if type(value) is not int or not 0 <= value < (1 << 31):
            raise ValueError("invalid descriptor")
        return value

    def load(self, program):
        if self.program_fd is not None or self.link_fd is not None:
            raise RuntimeError("program already loaded")
        if type(program) is not bytes or not program or len(program) % 8 or len(program) > 568:
            raise ValueError("invalid bounded bytecode")
        instructions = ctypes.create_string_buffer(program)
        license_text = ctypes.create_string_buffer(b"GPL\0")
        attr = LoadAttr(prog_type=15, insn_cnt=len(program) // 8,
                        insns=ctypes.addressof(instructions),
                        license=ctypes.addressof(license_text), expected_attach_type=6)
        self.program_fd = self._call(5, attr)
        return self.program_fd

    def program_id(self):
        if self.program_fd is None:
            raise RuntimeError("no loaded program")
        info = (ctypes.c_uint32 * 2)()
        attr = InfoAttr(bpf_fd=self.program_fd, info_len=ctypes.sizeof(info),
                        info=ctypes.addressof(info))
        self._call(15, attr)
        if attr.info_len < 8 or info[0] != 15 or info[1] == 0:
            raise RuntimeError("unexpected program identity")
        return int(info[1])

    def attach(self, cgroup_fd):
        self._fd(cgroup_fd)
        if self.program_fd is None or self.link_fd is not None:
            raise RuntimeError("invalid link lifecycle")
        attr = LinkAttr(prog_fd=self.program_fd, target_fd=cgroup_fd,
                        attach_type=6, flags=0)
        self.link_fd = self._call(28, attr)
        return self.link_fd

    def query_program_ids(self, cgroup_fd):
        self._fd(cgroup_fd)
        ids = (ctypes.c_uint32 * 64)()
        attr = QueryAttr(target_fd=cgroup_fd, attach_type=6,
                         prog_ids=ctypes.addressof(ids), prog_cnt=64)
        self._call(16, attr)
        if attr.prog_cnt > 64:
            raise RuntimeError("unbounded cgroup program set")
        result = tuple(int(ids[i]) for i in range(attr.prog_cnt))
        if any(value == 0 for value in result) or len(set(result)) != len(result):
            raise RuntimeError("invalid cgroup program identity set")
        return result

    @classmethod
    def _object_path(cls, directory_fd, token):
        cls._fd(directory_fd)
        if type(token) is not str or re.fullmatch(r"[0-9a-f]{64}", token) is None:
            raise ValueError("invalid pin token")
        return ctypes.create_string_buffer(f"/proc/self/fd/{directory_fd}/{token}".encode("ascii"))

    def _link_info(self):
        if self.link_fd is None:
            raise RuntimeError("no held link")
        info = LinkInfo()
        attr = InfoAttr(bpf_fd=self.link_fd, info_len=ctypes.sizeof(info),
                        info=ctypes.addressof(info))
        self._call(15, attr)
        if attr.info_len < 28 or info.type != 3 or info.attach_type != 6:
            raise RuntimeError("unexpected cgroup-device link type")
        return info

    def link_identity(self):
        info = self._link_info()
        return LinkIdentity(info.id, info.prog_id, info.cgroup_id)

    def _verify_link(self, expected):
        if type(expected) is not LinkIdentity or self.link_identity() != expected:
            raise RuntimeError("link identity mismatch")

    def pin(self, directory_fd, token, expected):
        """Exclusive kernel pin; existing names fail, with no retry or overwrite."""
        path = self._object_path(directory_fd, token)
        self._verify_link(expected)
        attr = ObjectAttr(pathname=ctypes.addressof(path), bpf_fd=self.link_fd)
        self._call(6, attr)

    def recover(self, directory_fd, token, expected):
        """Get an exact pinned object; mismatch closes FD and never detaches."""
        if self.link_fd is not None or self.program_fd is not None:
            raise RuntimeError("recovery requires empty ownership")
        if type(expected) is not LinkIdentity:
            raise ValueError("expected link identity required")
        path = self._object_path(directory_fd, token)
        attr = ObjectAttr(pathname=ctypes.addressof(path))
        self.link_fd = self._get_pin(attr)
        try:
            self._verify_link(expected)
        except BaseException:
            self.close_link()
            raise
        return self.link_fd

    def detach(self, expected):
        """Detach only held link after a fresh exact identity check; no unlink."""
        self._verify_link(expected)
        self._call(34, DetachAttr(link_fd=self.link_fd))

    def recover_detached(self, directory_fd, token, expected):
        """Hold an inert pinned link solely for journal-authorized pin cleanup.

        Linux v6.16 kernel/bpf/cgroup.c reports cgroup_id zero after detach.
        Original positive identity remains required: only its exact link and
        program IDs with zero cgroup ID are admitted. This grants no attach or
        detach authority. Caller must separately authorize any pin removal.
        """
        if self.link_fd is not None or self.program_fd is not None:
            raise RuntimeError("recovery requires empty ownership")
        if type(expected) is not LinkIdentity:
            raise ValueError("expected link identity required")
        path = self._object_path(directory_fd, token)
        attr = ObjectAttr(pathname=ctypes.addressof(path))
        self.link_fd = self._get_pin(attr)
        try:
            info = self._link_info()
            if (info.id != expected.link_id or info.prog_id != expected.program_id
                    or info.cgroup_id != 0):
                raise RuntimeError("detached link identity mismatch")
        except BaseException:
            self.close_link()
            raise
        return self.link_fd

    def _get_pin(self, attr):
        try:return self._call(7,attr)
        except OSError as error:
            if error.errno==errno.ENOENT:
                raise DirectPinAbsent(errno.ENOENT,'direct pin object absent') from error
            raise

    def close_link(self):
        descriptor, self.link_fd = self.link_fd, None
        if descriptor is not None:
            self._close_fd(descriptor)

    def close(self):
        try:
            self.close_link()
        finally:
            descriptor, self.program_fd = self.program_fd, None
            if descriptor is not None:
                self._close_fd(descriptor)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
