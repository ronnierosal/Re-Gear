"""One bounded grant delivery under the journal lock; no RPC/socket activation.

The trusted observer and bounded authenticated sender are supplied by the
future runtime adapter. No callback may reconnect/retry or wait for child exec.
A returned delivery result proves a response was sent, never that exec happened.
"""
from dataclasses import dataclass
import hashlib
import os
import time

from .device_filter_attachment import AttachmentObservation, validate_waiting_launch
from .device_filter_kernel import CgroupDeviceLink, LinkIdentity
from .device_filter_lifecycle import Phase
from .device_filter_pin_directory import FilterPinDirectory, pin_token
from .device_filter_program import compile_device_filter


@dataclass(frozen=True)
class GrantObservation:
    launch: AttachmentObservation
    inherited_scan_complete: bool
    inherited_descriptors_free: bool
    broker_scan_complete: bool
    broker_descriptors_free: bool
    # An empty scan cannot rule out later SCM_RIGHTS/device-broker delivery.
    # Existing callers that supply snapshots alone must continue to fail closed.
    broker_forwarding_restricted: bool = False


@dataclass(frozen=True)
class GrantDelivery:
    revision: int
    response_sent: bool
    execution_verified: bool = False
    disconnect_clearance: bool = False


class FilterGrantController:
    def __init__(self, journal, observe, send_once, *, kernel_factory=CgroupDeviceLink,
                 pin_factory=FilterPinDirectory, fstat=os.fstat, clock=time.monotonic):
        self.journal, self.observe, self.send_once = journal, observe, send_once
        self.kernel_factory, self.pin_factory = kernel_factory, pin_factory
        self.fstat, self.clock = fstat, clock

    def _fresh(self, state, cgroup_fd, expected=None):
        evidence, now = self.observe(), self.clock()
        if (type(evidence) is not GrantObservation
                or any(item is not True for item in (evidence.inherited_scan_complete,
                    evidence.inherited_descriptors_free, evidence.broker_scan_complete,
                    evidence.broker_descriptors_free, evidence.broker_forwarding_restricted))
                or (expected is not None and evidence != expected)):
            raise ValueError("complete descriptor and broker evidence required")
        validate_waiting_launch(evidence.launch, state.binding, cgroup_fd, now=now, fstat=self.fstat)
        code = compile_device_filter(evidence.launch.denied_devices)
        if hashlib.sha256(code).hexdigest() != state.owned.program_hash:
            raise ValueError("filter policy changed")
        return evidence, now

    def deliver(self, operation, unit, cgroup_fd):
        if type(cgroup_fd) is not int or cgroup_fd < 0:
            raise ValueError("held cgroup descriptor required")
        with self.journal.transaction() as tx:
            record = tx.read(operation, unit)
            if record.paired is not None:
                raise ValueError("paired launch authority is unavailable")
            if record.lifecycle.phase is not Phase.ATTACHED:
                raise ValueError("grant cannot replay")
            state = record.lifecycle
            try:
                evidence, _ = self._fresh(state, cgroup_fd)
                owned = state.owned
                identity = LinkIdentity(owned.link_id, owned.program_id, owned.kernel_cgroup_id)
                with self.pin_factory() as pins, self.kernel_factory() as kernel:
                    kernel.recover(pins.fd, pin_token(state.binding), identity)
                    if owned.program_id not in kernel.query_program_ids(cgroup_fd):
                        raise ValueError("owned program absent from held cgroup")
                    _, now = self._fresh(state, cgroup_fd, evidence)
                    record = tx.change(operation, unit, record.revision, "grant",
                        observed=state.binding, now=now, no_game=True,
                        inherited_scan_complete=True, inherited_descriptors_free=True)
                    if record.delivery_granted is not True:
                        raise ValueError("durable launch grant unavailable")
                    # Revalidate after potentially slow fsync; cancellation from
                    # here is coordinated recovery, never silent detach/replay.
                    self._fresh(state, cgroup_fd, evidence)
                    if kernel.link_identity() != identity:
                        raise ValueError("pinned link changed before response")
                    if self.send_once(state.binding, record.revision) is not True:
                        raise OSError("grant response delivery uncertain")
                    return GrantDelivery(record.revision, True)
            except BaseException:
                try:
                    latest = tx.read(operation, unit)
                    if latest.lifecycle.phase in (Phase.ATTACHED, Phase.GRANTED):
                        tx.change(operation, unit, latest.revision, "recover")
                except BaseException as recovery_error:
                    raise RuntimeError("grant failed and recovery persistence is unconfirmed") from recovery_error
                raise
