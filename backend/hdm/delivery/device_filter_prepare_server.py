"""Inactive authenticated prepare-and-withhold endpoint; never sends a grant.

Closing this connection makes the waiting wrapper fail closed. It is not a
parked or successful launch. Paired/direct pins remain for explicit recovery;
all created requests are durably cancelled before ordinary connection closure.
Unknown broker/importer coverage remains an explicit limitation, not a claim
of restriction. No listener, arm mutation, restart or runtime wiring exists.
"""
from dataclasses import dataclass
from enum import Enum
import math
import re
import time

from ..adapters.steamos.filter_unit_observer import FilterUnitObserver
from .device_filter_arm import FilterArm,FilterArmStore
from .device_filter_attachment import AttachmentObservation
from .device_filter_lifecycle import LaunchBinding,Phase,PairedOwnership,OwnedFilter
from .device_filter_peer import hold_waiting_peer,WaitingPeerIdentity
from .device_filter_program import compile_device_filter
from .device_filter_runtime_peer import observe_runtime_peer,RuntimePeerObservation
from .device_filter_transport import receive_request
from .device_filter_journal import JournalInitialPublicationUncertain
from .device_filter_preparation import FilterPreparation,PreparationResult
from .device_filter_observation_bundle import PrepareObservationBundle
from .device_receive_attachment import DmaReceiveAttachmentPolicy,validate_dma_observation


class IsolationCoverage(Enum):
    UNKNOWN='unknown'
    UNRESTRICTED='unrestricted'
    RESTRICTED='restricted'


@dataclass(frozen=True)
class FilterPrepareEvidence:
    boot_hash: str
    topology_hash: str
    config_hash: str
    runtime_digest: str
    denied_devices: tuple[tuple[int,int],...]
    no_game: bool
    effective_launch_verified: bool
    inherited_scan_complete: bool
    inherited_descriptors_free: bool
    broker_coverage: IsolationCoverage
    importer_coverage: IsolationCoverage


@dataclass(frozen=True)
class PrepareWithholdResult:
    binding: LaunchBinding
    revision: int
    paired: PairedOwnership
    direct: OwnedFilter
    broker_coverage: IsolationCoverage
    importer_coverage: IsolationCoverage
    outcome: str='prepared_withheld_recovery_required'
    recovery_required: bool=True
    launch_authorized: bool=False
    disconnect_clearance: bool=False
    native_execution_authorized: bool=False


class FilterPrepareServer:
    def _runtime_valid(self,value):return type(value) is RuntimePeerObservation

    def _combined_valid(self,value):
        from .device_filter_prepared_source import PreparedLaunchCollection
        return type(value) is PreparedLaunchCollection

    def _arm_valid(self,arm):return True

    def __init__(self,journal,user,observe_evidence,observe_dma,*,arms=None,clock=time.monotonic,
                 observer_factory=FilterUnitObserver,hold_peer=hold_waiting_peer,
                 observe_runtime=observe_runtime_peer,preparation_factory=FilterPreparation,observe_combined=None):
        self.journal,self.user,self.observe_evidence,self.observe_dma=journal,user,observe_evidence,observe_dma
        self.arms=FilterArmStore() if arms is None else arms
        self.clock,self.observer_factory=clock,observer_factory
        self.hold_peer,self.observe_runtime,self.preparation_factory=hold_peer,observe_runtime,preparation_factory
        self.observe_combined=observe_combined

    def _cancel(self,binding):
        with self.journal.transaction() as tx:
            latest=tx.read(binding.operation,binding.unit)
            if latest.lifecycle.binding!=binding:raise ValueError('cancellation binding mismatch')
            if latest.lifecycle.phase in (Phase.REQUESTED,Phase.PIN_PENDING,Phase.ATTACHED):
                try:tx.change(binding.operation,binding.unit,latest.revision,'cancel')
                except BaseException:
                    latest=tx.read(binding.operation,binding.unit)
                    if latest.lifecycle.binding!=binding or latest.lifecycle.phase is not Phase.CANCELLED:raise
            latest=tx.read(binding.operation,binding.unit)
            if latest.lifecycle.binding!=binding or latest.lifecycle.phase is not Phase.CANCELLED:
                raise ValueError('durable cancellation unavailable')
            return latest

    def handle(self,connection,*,expected_arm,runtime,deadline,expected_policy=None,policy_builder=None):
        with connection:
            if (type(expected_arm) is not FilterArm or not self._arm_valid(expected_arm) or self.user.uid!=expected_arm.uid
                    or (type(expected_policy) is not DmaReceiveAttachmentPolicy and not
                        (expected_policy is None and callable(policy_builder) and self.observe_combined is not None))
                    or (expected_policy is not None and policy_builder is not None)
                    or type(deadline) not in (int,float) or not math.isfinite(deadline)
                    or type(runtime.digest) is not str or re.fullmatch(r'[0-9a-f]{64}',runtime.digest) is None):
                raise ValueError('independent arm runtime deadline and DMA policy required')
            deadline=min(deadline,expected_arm.deadline)
            now=self.clock()
            if type(now) not in (int,float) or not math.isfinite(now) or not 0<=now<deadline:
                raise ValueError('fresh request deadline required')
            peer,request=receive_request(connection,expected_uid=self.user.uid,deadline=deadline,clock=self.clock)
            if (request.operation,request.unit)!=(expected_arm.operation,expected_arm.unit):
                raise ValueError('request differs from approved operation')
            inspector=self.observer_factory(self.user,deadline=deadline,clock=self.clock)
            with self.hold_peer(peer,request,expected_uid=self.user.uid,inspect_unit=inspector) as held:
                binding=initial=None
                def observe():
                    nonlocal expected_policy
                    if self.arms.read(request.unit)!=expected_arm:raise ValueError('arm changed')
                    source=self.observe_runtime(held,runtime)
                    combined=None
                    if self.observe_combined is not None:
                        combined=self.observe_combined(held)
                        if not self._combined_valid(combined):raise ValueError('typed combined prepare source required')
                        current=combined.evidence
                    else:current=self.observe_evidence(held)
                    if (type(current) is not FilterPrepareEvidence or not self._runtime_valid(source)
                            or current.runtime_digest!=runtime.digest or source.runtime_digest!=runtime.digest
                            or type(current.broker_coverage) is not IsolationCoverage
                            or type(current.importer_coverage) is not IsolationCoverage
                            or any(value is not True for value in (current.no_game,current.effective_launch_verified,
                                current.inherited_scan_complete,current.inherited_descriptors_free))):
                        raise ValueError('complete authenticated prepare evidence required')
                    compile_device_filter(current.denied_devices)
                    identity=held.revalidate()
                    if type(identity) is not WaitingPeerIdentity or identity!=source.identity:
                        raise ValueError('runtime peer lifetime changed')
                    now=self.clock()
                    expected_arm.require_current(unit=request.unit,uid=identity.uid,boot_hash=current.boot_hash,
                        topology_hash=current.topology_hash,config_hash=current.config_hash,
                        invocation=identity.invocation,now=now)
                    if now>=deadline or self.arms.read(request.unit)!=expected_arm:raise ValueError('deadline or arm changed')
                    observed=LaunchBinding(current.boot_hash,request.operation,request.unit,identity.invocation,
                        identity.uid,identity.pid,identity.starttime,identity.cgroup_dev,identity.cgroup_inode,
                        current.topology_hash,deadline)
                    if binding is not None and (observed!=binding or current!=initial):
                        raise ValueError('prepare evidence changed')
                    dma=combined.dma if combined is not None else self.observe_dma(held)
                    if expected_policy is None:
                        # Construct only after authenticating the held service and
                        # typed observations. Never refresh the policy on retry.
                        expected_policy=policy_builder(held,combined,expected_arm=expected_arm,
                            runtime=runtime,deadline=deadline,clock=self.clock)
                        if type(expected_policy) is not DmaReceiveAttachmentPolicy:
                            raise ValueError('typed authenticated DMA policy required')
                    if observed!=expected_policy.binding:raise ValueError('DMA policy binding changed')
                    validate_dma_observation(expected_policy,dma,self.clock())
                    final_runtime=self.observe_runtime(held,runtime)
                    if (final_runtime!=source or held.revalidate()!=identity or self.arms.read(request.unit)!=expected_arm
                            ):
                        raise ValueError('peer or arm changed during DMA observation')
                    now=self.clock()
                    if type(now) not in (int,float) or not math.isfinite(now) or not 0<=now<deadline:
                        raise ValueError('prepare deadline expired during final revalidation')
                    return AttachmentObservation(observed,current.denied_devices,True,True),current,dma
                launch,initial,_=observe();binding=launch.binding
                created=False
                try:
                    # EEXIST never cancels or reuses a previously burned identity.
                    try:
                        self.journal.create(binding)
                        created=True
                    except JournalInitialPublicationUncertain as error:
                        if error.binding!=binding:raise
                        created=True  # Exact exclusive publication is known.
                        raise
                    def observe_bundle():
                        launch,_,dma=observe()
                        return PrepareObservationBundle(launch,dma)
                    preparation=self.preparation_factory(self.journal,lambda:observe()[0],clock=self.clock,
                        observe_bundle=observe_bundle)
                    result=preparation.prepare(request.operation,request.unit,held.cgroup_fd,policy=expected_policy)
                    if (type(result) is not PreparationResult or result.prepared is not True
                            or result.launch_authorized or result.disconnect_clearance or result.binding!=binding):
                        raise ValueError('non-authorizing preparation result required')
                    observe()
                    latest=self._cancel(binding)
                    if latest.paired!=result.paired or latest.lifecycle.owned!=result.direct:
                        raise ValueError('prepared ownership changed during cancellation')
                    return PrepareWithholdResult(binding,latest.revision,latest.paired,latest.lifecycle.owned,
                                                 initial.broker_coverage,initial.importer_coverage)
                except BaseException as error:
                    if created:
                        try:self._cancel(binding)
                        except BaseException as cancellation_error:
                            raise RuntimeError('withheld preparation requires recovery; cancellation unconfirmed') from cancellation_error
                    raise error
