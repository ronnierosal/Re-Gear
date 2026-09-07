"""Internal experimental attachment controller; deliberately not wired to RPC.

Upstream must authenticate the waiting wrapper, idle state, exact device and
cgroup identities, and the held cgroup FD. Observations are trusted adapter
evidence, not frontend values. No attachment result authorizes launch/removal.
"""
from dataclasses import dataclass, replace
import hashlib
import math
import os
import stat
import time

from .device_filter_kernel import CgroupDeviceLink
from .device_filter_lifecycle import LaunchBinding, OwnedFilter, Phase
from .device_filter_pin_directory import FilterPinDirectory, pin_token
from .device_filter_program import compile_device_filter


@dataclass(frozen=True)
class AttachmentObservation:
    binding: LaunchBinding
    denied_devices: tuple[tuple[int, int], ...]
    no_game: bool
    waiting_wrapper_verified: bool


def validate_waiting_launch(evidence, binding, cgroup_fd, *, now, fstat, expected=None):
    """Shared trusted-observer validation; supplies no kernel or launch authority."""
    if (type(evidence) is not AttachmentObservation
            or type(evidence.binding) is not LaunchBinding or evidence.binding != binding
            or evidence.no_game is not True or evidence.waiting_wrapper_verified is not True
            or type(now) not in (int, float) or not math.isfinite(now)
            or not 0 <= now < binding.deadline
            or (expected is not None and evidence != expected)):
        raise ValueError("fresh authenticated waiting-launch evidence required")
    compile_device_filter(evidence.denied_devices)
    info = fstat(cgroup_fd)
    if (not stat.S_ISDIR(info.st_mode)
            or (info.st_dev, info.st_ino) != (binding.cgroup_dev, binding.cgroup_inode)):
        raise ValueError("held cgroup identity mismatch")
    return evidence


class FilterAttachmentController:
    def __init__(self, journal, observe, *, kernel_factory=CgroupDeviceLink,
                 pin_factory=FilterPinDirectory, fstat=os.fstat, clock=time.monotonic):
        self.journal, self.observe = journal, observe
        self.kernel_factory, self.pin_factory = kernel_factory, pin_factory
        self.fstat, self.clock = fstat, clock

    def _fresh(self, binding, cgroup_fd, expected=None):
        evidence, now = self.observe(), self.clock()
        validate_waiting_launch(evidence, binding, cgroup_fd, now=now,
                                fstat=self.fstat, expected=expected)
        return evidence, now

    def attach(self, operation, unit, cgroup_fd):
        if type(cgroup_fd) is not int or cgroup_fd < 0:
            raise ValueError("held cgroup descriptor required")
        with self.journal.transaction() as tx:
            current = tx.read(operation, unit)
            if current.lifecycle.phase is not Phase.REQUESTED:
                raise ValueError("attachment request cannot replay")
            binding = current.lifecycle.binding
            try:
                evidence, _ = self._fresh(binding, cgroup_fd)
                code = compile_device_filter(evidence.denied_devices)
                with self.pin_factory() as pins, self.kernel_factory() as kernel:
                    prior = set(kernel.query_program_ids(cgroup_fd))
                    kernel.load(code)
                    program_id = kernel.program_id()
                    if program_id in prior:
                        raise ValueError("new program identity already attached")
                    kernel.attach(cgroup_fd)
                    identity = kernel.link_identity()
                    if (identity.program_id != program_id
                            or set(kernel.query_program_ids(cgroup_fd)) != prior | {program_id}):
                        raise ValueError("exact attachment identity or program set mismatch")
                    evidence, now = self._fresh(binding, cgroup_fd, evidence)
                    owner = OwnedFilter(program_id, hashlib.sha256(code).hexdigest(),
                                        True, False, identity.link_id, identity.cgroup_id)
                    current = tx.change(operation, unit, current.revision, "prepare_pin",
                                        owned=owner, observed=binding, now=now)
                    if current.lifecycle.phase is not Phase.PIN_PENDING:
                        raise ValueError("pin preparation not durable")
                    self._fresh(binding, cgroup_fd, evidence)
                    token = pin_token(binding)
                    kernel.pin(pins.fd, token, identity)
                    with self.kernel_factory() as readback:
                        readback.recover(pins.fd, token, identity)
                        if readback.link_identity() != identity:
                            raise ValueError("pin identity readback mismatch")
                    _, now = self._fresh(binding, cgroup_fd, evidence)
                    if set(kernel.query_program_ids(cgroup_fd)) != prior | {program_id}:
                        raise ValueError("attachment set changed during pin")
                    current = tx.change(operation, unit, current.revision, "attach",
                                        owned=replace(owner, survives_owner_exit=True),
                                        observed=binding, now=now)
                    if current.lifecycle.phase is not Phase.ATTACHED:
                        raise ValueError("attachment confirmation not durable")
                    return current
            except BaseException as error:
                # A failed fsync may have published a newer revision. Re-read;
                # never guess the revision or unlink a possibly foreign pin.
                try:
                    latest = tx.read(operation, unit)
                    if latest.lifecycle.phase in (Phase.REQUESTED, Phase.PIN_PENDING, Phase.ATTACHED):
                        tx.change(operation, unit, latest.revision, "cancel")
                except BaseException as cancellation_error:
                    raise RuntimeError("attachment failed and durable cancellation is unconfirmed") from cancellation_error
                raise error
