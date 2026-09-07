"""Linux/x86_64 LSM receive-link primitives for disposable fixtures.

No runtime activation or cgroup selection is provided. The caller must
supply a reviewed program restricted to its disposable cgroup. Pins and extra
link references retain attachment after an owner closes or exits. Release must
be observed after all owned references close; close alone is not proof. Callers authenticate and serialize the held
bpffs directory and pin ownership; no unlink or detach authority is provided.
UAPI: https://github.com/torvalds/linux/blob/v6.16/include/uapi/linux/bpf.h
Attach: https://github.com/libbpf/libbpf/blob/v1.5.1/src/libbpf.c
"""
import ctypes
from dataclasses import dataclass
import errno
import os
import platform

from .device_filter_kernel import LoadAttr, LinkAttr, InfoAttr, ObjectAttr, CgroupDeviceLink


@dataclass(frozen=True)
class ReceiveIdentity:
    link_id: int
    program_id: int
    hook_btf_id: int
    target_obj_id: int

    def __post_init__(self):
        if (any(type(value) is not int or not 0 < value < 2**32
                for value in (self.link_id, self.program_id, self.hook_btf_id, self.target_obj_id))):
            raise ValueError('invalid kernel receive identity')


class ProgramIdAttr(ctypes.Structure):
    _fields_ = [('prog_id', ctypes.c_uint32), ('next_id', ctypes.c_uint32),
                ('open_flags', ctypes.c_uint32), ('fd_by_id_token_fd', ctypes.c_int32)]


class ReceivePinAbsent(FileNotFoundError):
    """Only BPF_OBJ_GET reported ENOENT; no release or clearance conclusion."""


class ReceiveLoadAttr(ctypes.Structure):
    _fields_ = LoadAttr._fields_ + [
        ('prog_btf_fd', ctypes.c_uint32), ('func_info_rec_size', ctypes.c_uint32),
        ('func_info', ctypes.c_uint64), ('func_info_cnt', ctypes.c_uint32),
        ('line_info_rec_size', ctypes.c_uint32), ('line_info', ctypes.c_uint64),
        ('line_info_cnt', ctypes.c_uint32), ('attach_btf_id', ctypes.c_uint32),
        ('attach_btf_obj_fd', ctypes.c_uint32)]


class ReceiveLinkInfo(ctypes.Structure):
    _fields_ = [('type', ctypes.c_uint32), ('id', ctypes.c_uint32),
        ('prog_id', ctypes.c_uint32), ('padding', ctypes.c_uint32),
        ('attach_type', ctypes.c_uint32), ('target_obj_id', ctypes.c_uint32),
        ('target_btf_id', ctypes.c_uint32), ('reserved', ctypes.c_uint32)]


class FileReceiveLink:
    def __init__(self, *, syscall=None, close_fd=None):
        if platform.system() != 'Linux' or platform.machine() != 'x86_64':
            raise RuntimeError('receive fixture requires Linux x86_64')
        if syscall is None:
            library = ctypes.CDLL(None, use_errno=True)
            syscall = library.syscall
            syscall.restype = ctypes.c_long
        self._syscall = syscall
        self._close_fd = close_fd or os.close
        self.program_fd = self.link_fd = None
        self.verifier_log = ''

    def _call(self, command, attr):
        result = self._syscall(321, command, ctypes.byref(attr), ctypes.sizeof(attr))
        if result < 0:
            raise OSError(ctypes.get_errno(), 'receive fixture BPF operation failed')
        return int(result)

    def _load(self, program, *, hook_btf_id):
        if self.program_fd is not None or self.link_fd is not None:
            raise RuntimeError('receive fixture already owns descriptors')
        if (type(program) is not bytes or not 0 < len(program) <= 4096 or len(program) % 8
                or type(hook_btf_id) is not int or not 0 < hook_btf_id < 2**32):
            raise ValueError('invalid bounded receive program or hook identity')
        instructions = ctypes.create_string_buffer(program)
        license = ctypes.create_string_buffer(b'GPL')
        log = ctypes.create_string_buffer(65536)
        attr = ReceiveLoadAttr(prog_type=29, insn_cnt=len(program)//8,
            insns=ctypes.addressof(instructions), license=ctypes.addressof(license),
            log_level=1, log_size=len(log), log_buf=ctypes.addressof(log),
            prog_name=b'regear_recvtest', expected_attach_type=27, attach_btf_id=hook_btf_id,
            prog_btf_fd=0, attach_btf_obj_fd=0)
        try:
            self.program_fd = self._call(5, attr)
            return self.program_id()
        except BaseException:
            self.close()
            raise
        finally:
            self.verifier_log = log.value.decode('utf-8', errors='replace')

    def verify_load(self, program, *, hook_btf_id):
        """Verify load and identity, then close; never create a link or enforce.

        Returned program ID identifies only this completed load observation.
        The descriptor is closed before return; no persistence or authority.
        """
        program_id = self._load(program, hook_btf_id=hook_btf_id)
        try:
            return program_id
        finally:
            self.close()

    def load_attach(self, program, *, hook_btf_id):
        expected_program = self._load(program, hook_btf_id=hook_btf_id)
        try:
            self.link_fd = self._call(28, LinkAttr(prog_fd=self.program_fd, target_fd=0, attach_type=27))
            info = self.identity()
            if info.target_btf_id != hook_btf_id or info.prog_id != expected_program:
                raise ValueError('received link targets another hook')
            return info.id
        except BaseException:
            self.close()
            raise

    def program_id(self):
        if self.program_fd is None:
            raise ValueError('no receive program owned')
        return self._program_identity(self.program_fd)

    def _program_identity(self, fd):
        info = (ctypes.c_uint32 * 2)()
        attr = InfoAttr(bpf_fd=fd, info_len=ctypes.sizeof(info), info=ctypes.addressof(info))
        self._call(15, attr)
        if attr.info_len < 8 or info[0] != 29 or info[1] == 0:
            raise ValueError('unexpected receive program identity')
        return int(info[1])

    def identity(self):
        if self.link_fd is None:
            raise ValueError('no receive link owned')
        info = ReceiveLinkInfo()
        attr = InfoAttr(bpf_fd=self.link_fd, info_len=ctypes.sizeof(info), info=ctypes.addressof(info))
        self._call(15, attr)
        if (attr.info_len < 28 or info.type != 2 or info.attach_type != 27
                or not info.id or not info.prog_id or not info.target_btf_id or not info.target_obj_id):
            raise ValueError('unexpected receive link identity')
        return info

    def link_identity(self):
        # v6.16 trampoline keys contain btf_obj_id(vmlinux), not sentinel zero.
        # Self-load selects vmlinux through attach_btf_obj_fd=0; recovery instead
        # requires an independently authenticated exact previously saved identity.
        info = self.identity()
        return ReceiveIdentity(info.id, info.prog_id, info.target_btf_id, info.target_obj_id)

    def pin(self, directory_fd, token, expected):
        """Exclusive pin in caller-authenticated bpffs directory; no overwrite."""
        path = CgroupDeviceLink._object_path(directory_fd, token)
        if type(expected) is not ReceiveIdentity or self.link_identity() != expected:
            raise ValueError('receive pin identity mismatch')
        self._call(6, ObjectAttr(pathname=ctypes.addressof(path), bpf_fd=self.link_fd))

    def recover(self, directory_fd, token, expected):
        """Acquire exact pin; caller authenticates expected identity and boot.

        Matching supplied fields alone does not prove they came from our load.
        Close never removes the pin.
        """
        if self.link_fd is not None or self.program_fd is not None:
            raise RuntimeError('receive recovery requires empty ownership')
        if type(expected) is not ReceiveIdentity:
            raise ValueError('typed receive identity required')
        path = CgroupDeviceLink._object_path(directory_fd, token)
        try:
            self.link_fd = self._call(7, ObjectAttr(pathname=ctypes.addressof(path)))
        except OSError as error:
            if error.errno == errno.ENOENT:
                raise ReceivePinAbsent(errno.ENOENT, 'receive pin object absent') from error
            raise
        try:
            if self.link_identity() != expected:
                raise ValueError('receive recovered identity mismatch')
        except BaseException:
            self.close()
            raise
        return self.link_fd

    def probe_program_present(self, program_id):
        """Temporary identity observation only; absence is not clearance."""
        if type(program_id) is not int or not 0 < program_id < 2**32:
            raise ValueError('positive program identity required')
        try:
            fd = self._call(13, ProgramIdAttr(prog_id=program_id))
        except OSError as error:
            if error.errno == errno.ENOENT:
                return False
            raise
        try:
            if self._program_identity(fd) != program_id:
                raise ValueError('program lookup identity mismatch')
            return True
        finally:
            self._close_fd(fd)

    def close(self):
        try:
            if self.link_fd is not None:
                descriptor, self.link_fd = self.link_fd, None
                self._close_fd(descriptor)
        finally:
            if self.program_fd is not None:
                descriptor, self.program_fd = self.program_fd, None
                self._close_fd(descriptor)
