"""Internal prepare-only composition; no grant, server, arm or RPC integration.

Both controllers share one pinned authenticated observation. Each keeps its
own journal transaction; the gaps are revalidated rather than implying atomic
publication. Prepared status records ownership only and cannot authorize a
launch. Failure preserves recorded pair/direct owners for ordered recovery.
"""
from dataclasses import dataclass
import os
import time

from .device_filter_attachment import FilterAttachmentController,validate_waiting_launch
from .device_filter_observation_bundle import validate_prepare_bundle
from .device_receive_attachment import ReceiveAttachmentController,ReceiveAttachmentPolicy,ReceiveAttachmentResult,DmaReceiveAttachmentPolicy
from .device_receive_attachment import validate_dma_observation
from .device_filter_journal import JournalRecord
from .device_filter_lifecycle import Phase,PairedStage,PairedOwnership,OwnedFilter,LaunchBinding


@dataclass(frozen=True)
class PreparationResult:
    revision: int
    binding: LaunchBinding
    paired: PairedOwnership
    direct: OwnedFilter
    prepared: bool = True
    launch_authorized: bool = False
    disconnect_clearance: bool = False


class FilterPreparation:
    def __init__(self,journal,observe,*,paired_factory=ReceiveAttachmentController,
                 direct_factory=FilterAttachmentController,fstat=os.fstat,clock=time.monotonic,observe_dma=None,observe_bundle=None):
        self.journal,self.observe=journal,observe
        self.paired_factory,self.direct_factory=paired_factory,direct_factory
        self.fstat,self.clock=fstat,clock
        self.observe_dma=observe_dma
        self.observe_bundle=observe_bundle

    def prepare(self,operation,unit,cgroup_fd,*,policy):
        if type(cgroup_fd) is not int or cgroup_fd<0 or type(policy) not in (ReceiveAttachmentPolicy,DmaReceiveAttachmentPolicy):
            raise ValueError('held cgroup and exact receive policy required')
        with self.journal.transaction() as tx:
            initial=tx.read(operation,unit)
            if (initial.lifecycle.phase is not Phase.REQUESTED or initial.lifecycle.owned is not None
                    or initial.paired is not None):raise ValueError('preparation cannot replay')
        binding=initial.lifecycle.binding
        try:
            if policy.binding!=binding:raise ValueError('policy binding changed')
            bundled=self.observe_bundle is not None
            if bundled:
                if type(policy) is not DmaReceiveAttachmentPolicy or not callable(self.observe_bundle):
                    raise ValueError('DMA bundle source required')
                first=validate_prepare_bundle(self.observe_bundle(),policy,binding,cgroup_fd,
                    now=self.clock(),fstat=self.fstat).launch
            else:
                first=self.observe()
                validate_waiting_launch(first,binding,cgroup_fd,now=self.clock(),fstat=self.fstat)
            def pinned_bundle():
                return validate_prepare_bundle(self.observe_bundle(),policy,binding,cgroup_fd,
                    now=self.clock(),fstat=self.fstat,expected=first)
            def pinned_observe():
                if bundled:return pinned_bundle().launch
                evidence=self.observe()
                validate_waiting_launch(evidence,binding,cgroup_fd,now=self.clock(),fstat=self.fstat,expected=first)
                if type(policy) is DmaReceiveAttachmentPolicy:
                    if not callable(self.observe_dma):raise ValueError('fresh DMA source required')
                    validate_dma_observation(policy,self.observe_dma(),self.clock())
                return evidence
            options=dict(fstat=self.fstat,clock=self.clock)
            if bundled:options['observe_bundle']=pinned_bundle
            elif type(policy) is DmaReceiveAttachmentPolicy:options['observe_dma']=self.observe_dma
            paired=self.paired_factory(self.journal,pinned_observe,**options)
            pair_result=paired.attach(operation,unit,cgroup_fd,policy=policy)
            if (type(pair_result) is not ReceiveAttachmentResult or pair_result.launch_authorized
                    or pair_result.disconnect_clearance or type(pair_result.ownership) is not PairedOwnership
                    or pair_result.ownership.stage is not PairedStage.RECEIVE_CONFIRMED
                    or pair_result.program_sha256!=policy.program_sha256):
                raise ValueError('paired ownership not confirmed')
            with self.journal.transaction() as tx:
                current=tx.read(operation,unit)
                if (current.revision!=pair_result.revision or current.lifecycle.binding!=binding
                        or current.lifecycle.phase is not Phase.REQUESTED or current.lifecycle.owned is not None
                        or current.paired!=pair_result.ownership or current.delivery_granted):
                    raise ValueError('paired publication changed before direct attachment')
                pinned_observe()
            direct=self.direct_factory(self.journal,pinned_observe,fstat=self.fstat,clock=self.clock)
            direct_result=direct.attach(operation,unit,cgroup_fd)
            if (type(direct_result) is not JournalRecord or direct_result.lifecycle.phase is not Phase.ATTACHED
                    or type(direct_result.lifecycle.owned) is not OwnedFilter or direct_result.delivery_granted):
                raise ValueError('direct ownership not confirmed')
            with self.journal.transaction() as tx:
                latest=tx.read(operation,unit)
                if (latest.revision!=direct_result.revision or latest.lifecycle.binding!=binding
                        or latest.lifecycle.phase is not Phase.ATTACHED or latest.paired!=pair_result.ownership
                        or latest.lifecycle.owned!=direct_result.lifecycle.owned or latest.delivery_granted):
                    raise ValueError('prepared ownership readback mismatch')
                pinned_observe()
            return PreparationResult(latest.revision,binding,latest.paired,latest.lifecycle.owned)
        except BaseException as error:
            try:
                with self.journal.transaction() as tx:
                    latest=tx.read(operation,unit)
                    if latest.lifecycle.binding!=binding:raise ValueError('preparation binding changed')
                    if latest.lifecycle.phase in (Phase.REQUESTED,Phase.PIN_PENDING,Phase.ATTACHED):
                        try:tx.change(operation,unit,latest.revision,'cancel')
                        except BaseException:
                            latest=tx.read(operation,unit)
                            if latest.lifecycle.binding!=binding or latest.lifecycle.phase is not Phase.CANCELLED:raise
                    latest=tx.read(operation,unit)
                    if latest.lifecycle.phase is not Phase.CANCELLED:raise ValueError('preparation cancellation unavailable')
            except BaseException as cancellation_error:
                raise RuntimeError('preparation failed and durable cancellation is unconfirmed') from cancellation_error
            raise error
