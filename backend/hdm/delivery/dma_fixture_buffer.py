"""One-page AMD GTT allocation/export for a separately supervised fixture.

Caller authenticates current AMD topology and exact render path/device number.
No mmap, import, GPU submission, display operation or implicit device discovery.
UAPI: Linux v6.16 include/uapi/drm/amdgpu_drm.h and include/uapi/drm/drm.h.
"""
import ctypes
import os
import platform
import re
import stat


class GemCreateIn(ctypes.Structure):
    _fields_ = [("bo_size", ctypes.c_uint64), ("alignment", ctypes.c_uint64),
                ("domains", ctypes.c_uint64), ("domain_flags", ctypes.c_uint64)]


class GemCreateOut(ctypes.Structure):
    _fields_ = [("handle", ctypes.c_uint32), ("pad", ctypes.c_uint32)]


class GemCreate(ctypes.Union):
    _fields_ = [("request", GemCreateIn), ("result", GemCreateOut)]


class PrimeHandle(ctypes.Structure):
    _fields_ = [("handle", ctypes.c_uint32), ("flags", ctypes.c_uint32), ("fd", ctypes.c_int32)]


class GemClose(ctypes.Structure):
    _fields_ = [("handle", ctypes.c_uint32), ("pad", ctypes.c_uint32)]


# Linux x86_64 _IOC encodings; sizes are independently asserted in tests.
GEM_CREATE = 0xc0206440
PRIME_HANDLE_TO_FD = 0xc00c642d
GEM_CLOSE = 0x40086409


def _ioctl(fd, request, value):
    library = ctypes.CDLL(None, use_errno=True)
    function = library.ioctl
    function.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_void_p]
    function.restype = ctypes.c_int
    if function(fd, request, ctypes.byref(value)) != 0:
        raise OSError(ctypes.get_errno(), "fixture buffer ioctl failed")


class DmaFixtureBuffer:
    """Owns an exported FD, GEM handle and render FD until explicit close."""
    def __init__(self, *, open_fd=os.open, fstat=os.fstat, close_fd=os.close,
                 ioctl=_ioctl, effective_uid=None, get_inheritable=os.get_inheritable):
        if platform.system() != "Linux" or platform.machine() != "x86_64":
            raise ValueError("fixture buffer requires Linux x86_64")
        uid = os.geteuid() if effective_uid is None else effective_uid()
        if type(uid) is not int or uid != 0:
            raise ValueError("fixture buffer requires root")
        self._open, self._fstat, self._close, self._ioctl = open_fd, fstat, close_fd, ioctl
        self._inheritable = get_inheritable
        self.render_fd = self.export_fd = self.handle = None

    def allocate(self, render_path, device_number):
        if any(value is not None for value in (self.render_fd, self.export_fd, self.handle)):
            raise ValueError("fixture buffer already allocated")
        if (type(render_path) is not str or re.fullmatch(r"/dev/dri/renderD[0-9]{1,10}", render_path) is None
                or type(device_number) is not int or not 0 <= device_number < 2**64):
            raise ValueError("exact authenticated render identity required")
        try:
            # O_NOFOLLOW and O_CLOEXEC are Linux constants for portable mocks.
            self.render_fd = self._open(render_path, os.O_RDWR | 0x20000 | 0x80000)
            info = self._fstat(self.render_fd)
            if not stat.S_ISCHR(info.st_mode) or info.st_rdev != device_number:
                raise ValueError("opened render device identity changed")
            create = GemCreate(request=GemCreateIn(4096, 4096, 2, 0))
            self._ioctl(self.render_fd, GEM_CREATE, create)
            if create.result.handle == 0:
                raise ValueError("GEM handle unavailable")
            self.handle = int(create.result.handle)
            prime = PrimeHandle(self.handle, 0x80000 | 2, -1)  # CLOEXEC | RDWR
            self._ioctl(self.render_fd, PRIME_HANDLE_TO_FD, prime)
            if prime.fd < 0 or prime.fd == self.render_fd:
                raise ValueError("export descriptor unavailable")
            self.export_fd = int(prime.fd)
            if self._inheritable(self.export_fd) is not False:
                raise ValueError("export descriptor is not close-on-exec")
            return self.export_fd
        except BaseException:
            self.close()
            raise

    def close(self):
        errors = []
        def attempt(action):
            try:
                action()
            except Exception as error:
                errors.append(error)
        exported, self.export_fd = self.export_fd, None
        if exported is not None:
            attempt(lambda: self._close(exported))
        handle, self.handle = self.handle, None
        if handle is not None and self.render_fd is not None:
            attempt(lambda: self._ioctl(self.render_fd, GEM_CLOSE, GemClose(handle, 0)))
        render, self.render_fd = self.render_fd, None
        if render is not None:
            attempt(lambda: self._close(render))
        if errors:
            raise RuntimeError("fixture buffer cleanup unconfirmed") from errors[0]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
