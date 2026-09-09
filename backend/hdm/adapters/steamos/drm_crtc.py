"""Read whether a DRM device has a mode committed, from the CRTC itself.

`DrmConnectorRecord.mode_committed` derives that fact from sysfs `enabled`.
Upstream `drm_sysfs.c` shows `enabled_show` reports whether `connector->encoder`
is set, which is not the same question: an encoder can remain attached to a
connector that is not scanning out, and `modes_show` lists the modes a
connector *advertises* rather than one it is driving. Issue #143 recorded that
correction and left the product still reading the proxy, because the real
evidence was believed to need a privileged read of
`/sys/kernel/debug/dri/<n>/state`.

It does not. `DRM_IOCTL_MODE_GETRESOURCES` and `DRM_IOCTL_MODE_GETCRTC` are
read-only, require neither root nor DRM master, and return `mode_valid` and
`fb_id` directly. Verified unprivileged on the tested Ally X: the eGPU's card
reported `crtc=98 fb_id=133 mode_valid=1 3840x2160`, matching the framebuffer a
privileged debugfs read had attributed to the kernel console.

Three deliberate limits.

**Only GET calls.** No master is taken and no mode is set. This module observes.

**No `GETCONNECTOR`.** Its zero-count form makes the kernel probe the
connector, which is a real detect on the wire rather than a read of state.
Connector identity already comes from sysfs; what was missing was the CRTC, and
that needs no probe.

**Unreadable is unknown, never false.** A node that cannot be opened, an ioctl
that fails, or a kernel that answers unexpectedly all produce an incomplete
observation. A caller must not read "we could not look" as "nothing is
committed": that is the shape of fail-open this evidence exists to remove.
"""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from typing import Callable

try:  # pragma: no cover - exercised by platform, not by a test
    import fcntl
except ImportError:
    # Not a POSIX host. The module still imports so the rest of the package
    # loads anywhere, and an observation here fails closed to unknown rather
    # than pretending nothing is committed.
    fcntl = None


#: DRM's ioctl type, and the read-write direction bits, composed here rather
#: than imported so this module depends on no ioctl helper library.
_DRM_IOCTL_BASE = 0x64
_IOC_WRITE = 1
_IOC_READ = 2

#: A card with more CRTCs than this is not the shape this reads; refusing is
#: better than allocating whatever the kernel reports.
MAX_CRTCS = 64


def iowr(number: int, size: int) -> int:
    return ((_IOC_READ | _IOC_WRITE) << 30) | (size << 16) | (_DRM_IOCTL_BASE << 8) | number


class KernelModeInfo(ctypes.Structure):
    _fields_ = [
        ("clock", ctypes.c_uint32),
        ("hdisplay", ctypes.c_uint16),
        ("hsync_start", ctypes.c_uint16),
        ("hsync_end", ctypes.c_uint16),
        ("htotal", ctypes.c_uint16),
        ("hskew", ctypes.c_uint16),
        ("vdisplay", ctypes.c_uint16),
        ("vsync_start", ctypes.c_uint16),
        ("vsync_end", ctypes.c_uint16),
        ("vtotal", ctypes.c_uint16),
        ("vscan", ctypes.c_uint16),
        ("vrefresh", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("name", ctypes.c_char * 32),
    ]


class KernelCardResources(ctypes.Structure):
    _fields_ = [
        ("fb_id_ptr", ctypes.c_uint64),
        ("crtc_id_ptr", ctypes.c_uint64),
        ("connector_id_ptr", ctypes.c_uint64),
        ("encoder_id_ptr", ctypes.c_uint64),
        ("count_fbs", ctypes.c_uint32),
        ("count_crtcs", ctypes.c_uint32),
        ("count_connectors", ctypes.c_uint32),
        ("count_encoders", ctypes.c_uint32),
        ("min_width", ctypes.c_uint32),
        ("max_width", ctypes.c_uint32),
        ("min_height", ctypes.c_uint32),
        ("max_height", ctypes.c_uint32),
    ]


class KernelCrtc(ctypes.Structure):
    _fields_ = [
        ("set_connectors_ptr", ctypes.c_uint64),
        ("count_connectors", ctypes.c_uint32),
        ("crtc_id", ctypes.c_uint32),
        ("fb_id", ctypes.c_uint32),
        ("x", ctypes.c_uint32),
        ("y", ctypes.c_uint32),
        ("gamma_size", ctypes.c_uint32),
        ("mode_valid", ctypes.c_uint32),
        ("mode", KernelModeInfo),
    ]


GET_RESOURCES = iowr(0xA0, ctypes.sizeof(KernelCardResources))
GET_CRTC = iowr(0xA1, ctypes.sizeof(KernelCrtc))


def ioctl_call(descriptor: int, request: int, structure: object) -> int:
    """Issue one ioctl, or refuse on a host that has none.

    A missing `fcntl` raises here rather than at import, so the failure lands
    in the same place as any other unreadable device and produces an unknown
    observation instead of a false one.
    """
    if fcntl is None:
        raise OSError("ioctl is unavailable on this platform")
    return fcntl.ioctl(descriptor, request, structure)


@dataclass(frozen=True, slots=True)
class CrtcRecord:
    """One CRTC of a card, and whether it is presenting anything."""

    crtc_id: int
    fb_id: int
    mode_valid: bool
    width: int
    height: int

    @property
    def committed(self) -> bool:
        """Whether this CRTC has a mode *and* something to scan out.

        Both are required. A valid mode with no framebuffer is not a display
        being driven, and a framebuffer with no mode is not being presented.
        """
        return self.mode_valid and self.fb_id > 0


@dataclass(frozen=True, slots=True)
class CardCrtcState:
    """What one card's CRTCs report, or why they could not be read."""

    node: str
    code: str
    crtcs: tuple[CrtcRecord, ...] = ()
    complete: bool = False

    @property
    def committed(self) -> tuple[CrtcRecord, ...]:
        return tuple(record for record in self.crtcs if record.committed)

    @property
    def mode_committed(self) -> bool | None:
        """Whether this card is driving a display, or None if unknown.

        None is the answer whenever the observation did not finish. Callers
        grade an unknown as unverified rather than as a quiet false.
        """
        if not self.complete:
            return None
        return bool(self.committed)


class DrmCrtcProbe:
    """Observe a DRM card's CRTC state through read-only ioctls."""

    def __init__(
        self,
        *,
        open_node: Callable[[str], int] | None = None,
        ioctl: Callable[[int, int, object], int] | None = None,
        close_fd: Callable[[int], None] = os.close,
    ) -> None:
        self._open = open_node or self._open_node
        self._ioctl = ioctl or ioctl_call
        self._close_fd = close_fd

    @staticmethod
    def _open_node(node: str) -> int:
        return os.open(node, os.O_RDWR | getattr(os, "O_CLOEXEC", 0))

    def observe(self, node: str) -> CardCrtcState:
        """Read every CRTC on `node`, or report why the read did not finish."""
        try:
            descriptor = self._open(node)
        except OSError:
            return CardCrtcState(node, "drm_crtc.node_unavailable")
        try:
            return self._read(node, descriptor)
        except (OSError, ValueError):
            return CardCrtcState(node, "drm_crtc.read_failed")
        finally:
            self._close_fd(descriptor)

    def _read(self, node: str, descriptor: int) -> CardCrtcState:
        resources = KernelCardResources()
        self._ioctl(descriptor, GET_RESOURCES, resources)
        count = resources.count_crtcs
        if count == 0:
            # A card with no CRTCs drives nothing, and that is a complete answer.
            return CardCrtcState(node, "drm_crtc.no_crtcs", (), True)
        if count > MAX_CRTCS:
            return CardCrtcState(node, "drm_crtc.crtc_count_implausible")

        identifiers = (ctypes.c_uint32 * count)()
        # Ask only for the CRTC array. Leaving the other pointers null with
        # zero counts keeps the kernel from writing anywhere this did not
        # allocate, and none of the other lists is needed here.
        resources.crtc_id_ptr = ctypes.addressof(identifiers)
        resources.fb_id_ptr = 0
        resources.connector_id_ptr = 0
        resources.encoder_id_ptr = 0
        resources.count_fbs = 0
        resources.count_connectors = 0
        resources.count_encoders = 0
        self._ioctl(descriptor, GET_RESOURCES, resources)
        if resources.count_crtcs != count:
            # The set changed between the two calls, so the array this
            # allocated no longer describes the card.
            return CardCrtcState(node, "drm_crtc.crtc_set_changed")

        records = []
        for identifier in identifiers:
            crtc = KernelCrtc()
            crtc.crtc_id = identifier
            self._ioctl(descriptor, GET_CRTC, crtc)
            records.append(
                CrtcRecord(
                    int(crtc.crtc_id),
                    int(crtc.fb_id),
                    bool(crtc.mode_valid),
                    int(crtc.mode.hdisplay),
                    int(crtc.mode.vdisplay),
                )
            )
        return CardCrtcState(node, "drm_crtc.observed", tuple(records), True)
