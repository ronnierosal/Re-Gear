"""Arm and disarm the cgroup device filter behind `regear.ports.device_filter`.

`regear.delivery.device_filter_kernel` already supplies the syscall primitives and
`regear.egpu_release` drives them by hand. Nothing implemented the port, so the
one service that sequences a live disconnect had no way to reach the kernel.
This is that implementation and it adds no new capability: it loads, attaches,
queries and detaches exactly what the operator tool already does.

Two things it does that driving the primitives by hand does not.

**It opens the cgroup once and keeps the descriptor.** A `CgroupIdentity` is an
observation, and systemd recreates a unit's cgroup on restart under the same
path. Re-opening by path before each check would let a replaced cgroup inherit
the attachment, so the descriptor opened at arm time is the one every later
query uses, and the inode it was opened on is compared against the identity
that authorised the arm before anything is loaded.

**It detaches by identity.** `disarm` verifies the held link is still the one
this adapter attached before detaching it, so a link that was replaced
underneath is reported rather than torn down.

The link is not pinned. It exists for as long as this adapter holds it and
disappears with the process, which `regear.application.filter_arm` is explicit
about: that is not durable recovery, and nothing here claims otherwise.
"""

from __future__ import annotations

import os
from typing import Callable

from ...delivery.device_filter_kernel import CgroupDeviceLink
from ...domain.filter_authorization import CgroupIdentity
from ...ports.device_filter import (
    ArmedFilter,
    ArmOutcome,
    ArmResult,
    DisarmOutcome,
    DisarmResult,
)


class CgroupDeviceFilter:
    """One armed attachment at a time, on a cgroup identified by inode."""

    def __init__(
        self,
        *,
        link_factory: Callable[[], CgroupDeviceLink] = CgroupDeviceLink,
        open_cgroup: Callable[[str], int] | None = None,
        stat_fd: Callable[[int], os.stat_result] = os.fstat,
        close_fd: Callable[[int], None] = os.close,
    ) -> None:
        self._link_factory = link_factory
        self._open = open_cgroup or self._open_directory
        self._stat_fd = stat_fd
        self._close_fd = close_fd
        self._link: CgroupDeviceLink | None = None
        self._cgroup_fd: int | None = None
        self._identity = None
        self._program_id = 0

    @staticmethod
    def _open_directory(path: str) -> int:
        return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)

    def arm(self, program: bytes, cgroup: CgroupIdentity) -> ArmResult:
        """Load `program` and attach it to the cgroup `cgroup` identifies."""
        if self._link is not None:
            return ArmResult(ArmOutcome.REFUSED, code="device_filter.already_armed")
        if type(cgroup) is not CgroupIdentity:
            return ArmResult(ArmOutcome.REFUSED, code="device_filter.cgroup_invalid")

        try:
            cgroup_fd = self._open(cgroup.path)
        except OSError:
            return ArmResult(
                ArmOutcome.REFUSED, code="device_filter.cgroup_unavailable"
            )
        try:
            status = self._stat_fd(cgroup_fd)
        except OSError:
            self._close_fd(cgroup_fd)
            return ArmResult(
                ArmOutcome.REFUSED, code="device_filter.cgroup_unavailable"
            )
        if (status.st_dev, status.st_ino) != (cgroup.device, cgroup.inode):
            # The path resolves to a different cgroup than the one authorised.
            # A restart between the observation and here looks exactly like
            # this, and the authorisation does not carry over to it.
            self._close_fd(cgroup_fd)
            return ArmResult(ArmOutcome.REFUSED, code="device_filter.cgroup_replaced")

        try:
            link = self._link_factory()
        except (RuntimeError, OSError):
            self._close_fd(cgroup_fd)
            return ArmResult(
                ArmOutcome.LOAD_FAILED, code="device_filter.kernel_unavailable"
            )

        # Which half failed is worth keeping apart: a program the kernel will
        # not load is a different problem from one it loads and will not attach.
        attaching = False
        try:
            link.load(program)
            program_id = link.program_id()
            attaching = True
            link.attach(cgroup_fd)
            identity = link.link_identity()
        except (OSError, RuntimeError, ValueError):
            link.close()
            self._close_fd(cgroup_fd)
            return ArmResult(
                ArmOutcome.ATTACH_FAILED if attaching else ArmOutcome.LOAD_FAILED,
                code="device_filter.attach_failed"
                if attaching
                else "device_filter.load_failed",
            )

        self._link = link
        self._cgroup_fd = cgroup_fd
        self._identity = identity
        self._program_id = program_id
        return ArmResult(
            ArmOutcome.ARMED,
            ArmedFilter(program_id, identity.link_id, identity.cgroup_id),
        )

    def enforced(self, cgroup: CgroupIdentity, program_id: int) -> bool:
        """Report whether `program_id` decides opens on that cgroup right now.

        Asked through the descriptor opened at arm time rather than by path, so
        a cgroup recreated under the same name reads as not enforced instead of
        answering for the one this adapter never attached to.
        """
        if self._link is None or self._cgroup_fd is None:
            return False
        if program_id != self._program_id:
            # Asking about somebody else's program. This adapter can only speak
            # for the one it loaded.
            return False
        try:
            return program_id in self._link.query_program_ids(self._cgroup_fd)
        except (OSError, RuntimeError):
            return False

    def disarm(self) -> DisarmResult:
        """Detach the held link, verifying it is still the one this attached."""
        if self._link is None:
            return DisarmResult(DisarmOutcome.NOT_ARMED)
        link, self._link = self._link, None
        cgroup_fd, self._cgroup_fd = self._cgroup_fd, None
        identity, self._identity = self._identity, None
        self._program_id = 0
        outcome = DisarmOutcome.DISARMED
        code = ""
        try:
            link.detach(identity)
        except (OSError, RuntimeError, ValueError):
            # Closing the descriptors below still drops an unpinned link. The
            # failure is reported rather than swallowed because a link whose
            # identity no longer matches is not one this adapter may claim to
            # have taken down.
            outcome = DisarmOutcome.FAILED
            code = "device_filter.detach_failed"
        finally:
            link.close()
            if cgroup_fd is not None:
                self._close_fd(cgroup_fd)
        return DisarmResult(outcome, code)
