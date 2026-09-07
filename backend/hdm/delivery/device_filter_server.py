"""One authenticated launch request, composed through existing controllers.

Not activated by an RPC or daemon. The caller supplies independently approved
arm/runtime and live evidence. Unknown descriptor forwarding routes withhold
even initial attachment. No observation or result grants physical removal.
"""
from dataclasses import dataclass
import time

from ..adapters.steamos.filter_unit_observer import FilterUnitObserver
from .device_filter_arm import FilterArm, FilterArmStore
from .device_filter_attachment import AttachmentObservation, FilterAttachmentController
from .device_filter_grant import GrantObservation, FilterGrantController
from .device_filter_lifecycle import LaunchBinding
from .device_filter_peer import hold_waiting_peer
from .device_filter_program import compile_device_filter
from .device_filter_runtime_peer import observe_runtime_peer
from .device_filter_transport import receive_request, send_grant


@dataclass(frozen=True)
class FilterLaunchEvidence:
    boot_hash: str
    topology_hash: str
    config_hash: str
    runtime_digest: str
    denied_devices: tuple[tuple[int, int], ...]
    no_game: bool
    effective_launch_verified: bool
    inherited_scan_complete: bool
    inherited_descriptors_free: bool
    broker_scan_complete: bool
    broker_descriptors_free: bool
    broker_forwarding_restricted: bool


class FilterLaunchServer:
    def __init__(self, journal, user, observe_evidence, *, arms=None,
                 clock=time.monotonic, observer_factory=FilterUnitObserver,
                 hold_peer=hold_waiting_peer, observe_runtime=observe_runtime_peer,
                 attachment_factory=FilterAttachmentController,
                 grant_factory=FilterGrantController):
        self.journal, self.user, self.observe_evidence = journal, user, observe_evidence
        self.arms = FilterArmStore() if arms is None else arms
        self.clock, self.observer_factory = clock, observer_factory
        self.hold_peer, self.observe_runtime = hold_peer, observe_runtime
        self.attachment_factory, self.grant_factory = attachment_factory, grant_factory

    def handle(self, connection, *, expected_arm, runtime, deadline):
        """Own/close one accepted connection. No retries, restart, or arm removal.

        The expected arm and runtime come from protected operation preparation,
        never from the socket or frontend. Existing journal records are never
        reused, even when a prior request failed before response delivery.
        """
        with connection:
            if type(expected_arm) is not FilterArm or self.user.uid != expected_arm.uid:
                raise ValueError("independently approved launch arm required")
            deadline = min(deadline, expected_arm.deadline)
            peer, request = receive_request(connection, expected_uid=self.user.uid,
                                            deadline=deadline, clock=self.clock)
            if (request.operation, request.unit) != (expected_arm.operation, expected_arm.unit):
                raise ValueError("request differs from prepared operation")
            inspector = self.observer_factory(self.user, deadline=deadline, clock=self.clock)
            with self.hold_peer(peer, request, expected_uid=self.user.uid, inspect_unit=inspector) as held:
                binding = None
                policy = None

                def observe():
                    if self.arms.read(request.unit) != expected_arm:
                        raise ValueError("prepared arm changed")
                    source = self.observe_runtime(held, runtime)
                    current = self.observe_evidence(held)
                    if (type(current) is not FilterLaunchEvidence
                            or current.runtime_digest != runtime.digest
                            or source.runtime_digest != runtime.digest
                            or any(value is not True for value in (
                                current.no_game, current.effective_launch_verified,
                                current.inherited_scan_complete, current.inherited_descriptors_free,
                                current.broker_scan_complete, current.broker_descriptors_free,
                                current.broker_forwarding_restricted))):
                        raise ValueError("complete authenticated launch isolation evidence required")
                    compile_device_filter(current.denied_devices)
                    identity = held.revalidate()
                    if identity != source.identity:
                        raise ValueError("runtime lifetime changed during evidence collection")
                    now = self.clock()
                    expected_arm.require_current(unit=request.unit, uid=identity.uid,
                        boot_hash=current.boot_hash, topology_hash=current.topology_hash,
                        config_hash=current.config_hash, invocation=identity.invocation,
                        now=now)
                    if now >= deadline or self.arms.read(request.unit) != expected_arm:
                        raise ValueError("launch deadline or arm changed during observation")
                    observed = LaunchBinding(current.boot_hash, request.operation, request.unit,
                        identity.invocation, identity.uid, identity.pid, identity.starttime,
                        identity.cgroup_dev, identity.cgroup_inode, current.topology_hash, deadline)
                    if binding is not None and (observed != binding or current.denied_devices != policy):
                        raise ValueError("launch binding changed")
                    launch = AttachmentObservation(observed, current.denied_devices, True, True)
                    return GrantObservation(launch, True, True, True, True, True)

                initial = observe()
                binding = initial.launch.binding
                policy = initial.launch.denied_devices
                # Exclusive journal create burns the operation/unit identity.
                # A crash at any subsequent boundary requires journal recovery.
                self.journal.create(binding)
                attachment = self.attachment_factory(self.journal, lambda: observe().launch, clock=self.clock)
                attachment.attach(request.operation, request.unit, held.cgroup_fd)
                def send_once(selected, revision):
                    return send_grant(connection, request, selected, revision,
                                      deadline=deadline, clock=self.clock)
                grant = self.grant_factory(self.journal, observe, send_once, clock=self.clock)
                return grant.deliver(request.operation, request.unit, held.cgroup_fd)
