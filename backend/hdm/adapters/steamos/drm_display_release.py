"""Turn off an eGPU CRTC the kernel console reclaimed, and give it straight back.

`hdm.domain.display_release` decides whether this may run; this performs it, and
performs nothing else. The sequence is deliberately small:

1. Open the card. Nothing else holds it -- that is the precondition the domain
   checked -- so `drm_open` makes this the DRM master without a further call.
   `DRM_IOCTL_SET_MASTER` is issued anyway, because inheriting master by being
   first is a property of the moment rather than something to rely on, and a
   device that will not grant it must refuse rather than continue unprivileged.
2. For each permitted CRTC, one legacy `DRM_IOCTL_MODE_SETCRTC` with `fb_id=0`,
   `mode_valid=0` and no connectors. That is the documented way to say "drive
   nothing".
3. Read each CRTC back with `GET_CRTC`. A write that returned without error but
   left the mode committed is reported as still committed, for the same reason
   `SysfsDeviceRemoval` verifies a detach rather than assuming it.
4. Hold the descriptor. This is the part that matters, and it is why this is a
   handle rather than a function.

**Why the descriptor is held.** The console's mode came back because
`drm_client_dev_restore()` runs when the last descriptor on the device closes.
So this release lasts exactly as long as the handle does: while it is open the
CRTC stays off, and the moment it closes -- deliberately, on an exception, or
because the process died -- the kernel puts the console's mode back.

That makes the recovery structural. There is no restore step that can be
skipped, no journal entry that can be lost, and no state to reconcile after a
crash: a process that dies mid-disconnect leaves the display exactly as it
found it. It is the opposite of the `/sys/class/vtconsole/vtcon1/bind` lever,
which is system-wide and has no automatic restore at all.

Scoped to one card. `card0` and the internal panel are never opened, never
mastered and never modified. Nothing here removes a device, and nothing here is
a claim that any device is safe to unplug.
"""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from .drm_crtc import GET_CRTC, KernelCrtc, ioctl_call, iowr


#: Both are `DRM_IO`: no payload, no direction bits.
SET_MASTER = (0x64 << 8) | 0x1E
DROP_MASTER = (0x64 << 8) | 0x1F
SET_CRTC = iowr(0xA2, ctypes.sizeof(KernelCrtc))


class DisplayReleaseOutcome(StrEnum):
    RELEASED = "released"
    #: The card could not be opened, so nothing was attempted.
    UNAVAILABLE = "unavailable"
    #: Master was refused. Something else holds the device, or the kernel
    #: declined; either way this must not continue.
    NOT_MASTER = "not_master"
    #: The write failed, or returned without error and left a mode committed.
    STILL_COMMITTED = "still_committed"


@dataclass(frozen=True, slots=True)
class DisplayReleaseResult:
    outcome: DisplayReleaseOutcome
    code: str = ""
    released: tuple[int, ...] = ()

    @property
    def ok(self) -> bool:
        return self.outcome is DisplayReleaseOutcome.RELEASED


class HeldDisplayRelease:
    """A released display, held off for exactly as long as this is open.

    Closing restores the console's mode, because that is what the kernel does
    when the last descriptor goes. Nothing has to remember to undo anything.
    """

    def __init__(
        self,
        node: str,
        descriptor: int,
        released: tuple[int, ...],
        *,
        ioctl: Callable[[int, int, object], int],
        close_fd: Callable[[int], None],
    ) -> None:
        self.node = node
        self.released = released
        self._descriptor: int | None = descriptor
        self._ioctl = ioctl
        self._close_fd = close_fd

    @property
    def held(self) -> bool:
        return self._descriptor is not None

    def still_released(self) -> bool | None:
        """Re-read the CRTCs this turned off; None when that cannot be read.

        A caller about to act on the release should ask again rather than trust
        that it still holds, in the same way readiness is re-assessed before a
        removal instead of being carried from earlier.
        """
        if self._descriptor is None:
            return False
        try:
            for identifier in self.released:
                crtc = KernelCrtc()
                crtc.crtc_id = identifier
                self._ioctl(self._descriptor, GET_CRTC, crtc)
                if crtc.mode_valid or crtc.fb_id:
                    return False
        except OSError:
            return None
        return True

    def restore(self) -> None:
        """Drop master and close, which puts the console's mode back.

        Idempotent, and safe to call from a failure path. Dropping master is
        attempted first so the handover is explicit, but the close is what
        actually triggers the kernel's restore, and it happens either way.
        """
        descriptor, self._descriptor = self._descriptor, None
        if descriptor is None:
            return
        try:
            self._ioctl(descriptor, DROP_MASTER, 0)
        except OSError:
            # Closing still drops master and still restores. A drop that failed
            # is not a reason to leak the descriptor and keep the display off.
            pass
        finally:
            self._close_fd(descriptor)

    def __enter__(self) -> "HeldDisplayRelease":
        return self

    def __exit__(self, *_: object) -> None:
        self.restore()


class DrmDisplayRelease:
    """Take master on one card and turn the named CRTCs off."""

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

    def release(
        self, node: str, crtcs: tuple[int, ...]
    ) -> tuple[DisplayReleaseResult, HeldDisplayRelease | None]:
        """Turn `crtcs` off on `node`, returning the handle that holds them off.

        The handle is the release. Discarding it restores the display, so a
        caller that wants the CRTCs to stay off must keep it for as long as
        that matters.
        """
        if type(crtcs) is not tuple or not crtcs or any(
            type(identifier) is not int or identifier <= 0 for identifier in crtcs
        ):
            return (
                DisplayReleaseResult(
                    DisplayReleaseOutcome.UNAVAILABLE, "display_release.crtcs_invalid"
                ),
                None,
            )
        try:
            descriptor = self._open(node)
        except OSError:
            return (
                DisplayReleaseResult(
                    DisplayReleaseOutcome.UNAVAILABLE, "display_release.node_unavailable"
                ),
                None,
            )

        # One handle owns the descriptor from here on, so every failure path
        # below restores through the same code the success path eventually
        # uses, rather than closing the descriptor its own way.
        held = HeldDisplayRelease(
            node, descriptor, crtcs, ioctl=self._ioctl, close_fd=self._close_fd
        )
        try:
            self._ioctl(descriptor, SET_MASTER, 0)
        except OSError:
            held.restore()
            return (
                DisplayReleaseResult(
                    DisplayReleaseOutcome.NOT_MASTER, "display_release.master_refused"
                ),
                None,
            )

        try:
            for identifier in crtcs:
                self._disable(descriptor, identifier)
            outstanding = self._outstanding(descriptor, crtcs)
        except OSError as error:
            held.restore()
            return (
                DisplayReleaseResult(
                    DisplayReleaseOutcome.STILL_COMMITTED,
                    f"display_release.write_failed:{error.errno}",
                ),
                None,
            )
        if outstanding:
            # The write returned without error and the mode is still there.
            # Restoring puts the console back rather than leaving a display in
            # a state nobody asked for.
            held.restore()
            return (
                DisplayReleaseResult(
                    DisplayReleaseOutcome.STILL_COMMITTED,
                    "display_release.mode_still_committed",
                ),
                None,
            )

        return (
            DisplayReleaseResult(
                DisplayReleaseOutcome.RELEASED, "display_release.released", crtcs
            ),
            held,
        )

    def _disable(self, descriptor: int, identifier: int) -> None:
        """One legacy set-config that says: drive nothing."""
        crtc = KernelCrtc()
        crtc.crtc_id = identifier
        crtc.fb_id = 0
        crtc.x = 0
        crtc.y = 0
        crtc.mode_valid = 0
        crtc.count_connectors = 0
        crtc.set_connectors_ptr = 0
        self._ioctl(descriptor, SET_CRTC, crtc)

    def _outstanding(self, descriptor: int, crtcs: tuple[int, ...]) -> tuple[int, ...]:
        """Which of `crtcs` still report a committed mode, read back fresh."""
        remaining = []
        for identifier in crtcs:
            crtc = KernelCrtc()
            crtc.crtc_id = identifier
            self._ioctl(descriptor, GET_CRTC, crtc)
            if crtc.mode_valid or crtc.fb_id:
                remaining.append(identifier)
        return tuple(remaining)
