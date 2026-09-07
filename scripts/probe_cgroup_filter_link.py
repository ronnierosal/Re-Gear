"""Fixed Linux/x86_64 cgroup-device BPF-link fixture primitives.

No command-line execution or persistent attachment. The fixture driver must
independently authenticate the exact disposable cgroup before calling attach.
Closing the link removes only this attachment; it never changes existing ones.
UAPI: https://github.com/torvalds/linux/blob/v6.16/include/uapi/linux/bpf.h
"""

import ctypes
import os
import platform


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
