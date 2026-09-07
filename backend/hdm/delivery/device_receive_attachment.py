"""Recovery-only paired attachment; deliberately absent from runtime and RPC.

Upstream supplies authenticated waiting-launch evidence and a running-kernel
BTF policy identity. Hashes identify the reviewed program; they do not certify
kernel provenance or authorize launch. The same observation contract as device
attachment validates the held cgroup. Failures preserve any recorded ownership
and leave incomplete metadata unresolved while attempting cancellation; no pin
is removed here. A crash after receive load but before its identity is recorded
remains unresolved. The closed policies cover character-device receipt or the
reviewed AMD DMA-exporter attribution variant; neither covers inherited buffers
or importer attachments. A caller-supplied BTF hash is not live kernel
verification. DMA addresses and compiled bytes remain ephemeral.
"""
from dataclasses import dataclass,field,replace
import hashlib
import math
import os
import re
import sys
import time

from .device_filter_attachment import validate_waiting_launch
from .device_filter_observation_bundle import validate_prepare_bundle
from .device_filter_btf import FileReceiveLayout,DmaBufReceiveLayout
from .dma_receive_program import compile_dma_receive
from .device_filter_lifecycle import LaunchBinding,Phase,PairedStage,PairedReceiveIdentity,PairedOwnership
from .device_filter_lifecycle import paired_token
from .device_filter_pin_directory import FilterPinDirectory
from .device_receive_program import compile_device_receive
from .device_receive_kernel import FileReceiveLink,ReceiveIdentity
from .cgroup_retention_map import CgroupRetentionMap,MapIdentity


@dataclass(frozen=True)
class ReceiveAttachmentPolicy:
    binding: LaunchBinding
    layout: FileReceiveLayout
    btf_sha256: str
    program_sha256: str

    def __post_init__(self):
        if type(self.binding) is not LaunchBinding or type(self.layout) is not FileReceiveLayout:
            raise ValueError('typed receive policy required')
        if any(type(value) is not str or re.fullmatch(r'[0-9a-f]{64}',value) is None
               for value in (self.btf_sha256,self.program_sha256)):
            raise ValueError('exact policy hashes required')
        layout=self.layout
        if (any(type(value) is not int or not 0<value<2**32 for value in
                (layout.hook_btf_id,layout.file_btf_id,layout.inode_btf_id,layout.file_size,layout.inode_size))
                or type(layout.pointer_size) is not int or layout.pointer_size!=8
                or type(layout.mode_size) is not int or layout.mode_size!=2
                or type(layout.rdev_size) is not int or layout.rdev_size!=4):
            raise ValueError('validated receive ABI layout required')
        for offset,width,size in ((layout.file_inode_offset,8,layout.file_size),
                (layout.inode_mode_offset,2,layout.inode_size),(layout.inode_rdev_offset,4,layout.inode_size)):
            if type(offset) is not int or offset<0 or offset+width>size:
                raise ValueError('receive layout field bounds invalid')


@dataclass(frozen=True)
class ReceiveAttachmentResult:
    revision: int
    ownership: PairedOwnership
    program_sha256: str
    launch_authorized: bool = False
    disconnect_clearance: bool = False


@dataclass(frozen=True)
class DmaReceiveObservation:
    """Trusted adapter evidence, not inferred topology or symbol authority."""
    binding: LaunchBinding
    layout: DmaBufReceiveLayout
    dma_buf_fops: int = field(repr=False)
    amdgpu_dmabuf_ops: int = field(repr=False)
    internal_primary_minor: int
    btf_sha256: str
    observed_at: float

    def __post_init__(self):
        if (type(self.binding) is not LaunchBinding or type(self.layout) is not DmaBufReceiveLayout
                or type(self.btf_sha256) is not str or re.fullmatch(r'[0-9a-f]{64}',self.btf_sha256) is None
                or type(self.observed_at) not in (int,float) or not math.isfinite(self.observed_at)
                or self.observed_at<0):raise ValueError('typed DMA evidence required')
        # Validate the closed compiler's ABI/symbol/minor contract; discard bytes.
        compile_dma_receive((self.binding.cgroup_inode,),((1,3),),layout=self.layout,
            dma_buf_fops=self.dma_buf_fops,amdgpu_dmabuf_ops=self.amdgpu_dmabuf_ops,
            allowed_internal_primary_minor=self.internal_primary_minor)


@dataclass(frozen=True)
class DmaReceiveAttachmentPolicy:
    binding: LaunchBinding
    evidence: DmaReceiveObservation = field(repr=False)
    program_sha256: str

    def __post_init__(self):
        if (type(self.binding) is not LaunchBinding or type(self.evidence) is not DmaReceiveObservation
                or self.evidence.binding!=self.binding or type(self.program_sha256) is not str
                or re.fullmatch(r'[0-9a-f]{64}',self.program_sha256) is None):
            raise ValueError('exact DMA policy identity required')


def validate_dma_observation(policy,value,now):
    if (type(policy) is not DmaReceiveAttachmentPolicy or type(value) is not DmaReceiveObservation
            or type(now) not in (int,float) or not math.isfinite(now)
            or not 0<=now-value.observed_at<=2 or now>=policy.binding.deadline
            or replace(value,observed_at=policy.evidence.observed_at)!=policy.evidence):
        raise ValueError('DMA evidence changed or stale')


def _close_all(*owners):
    pending=sys.exc_info()[0] is not None
    errors=[]
    for owner in owners:
        if owner is not None:
            try:owner.close()
            except Exception as error:errors.append(error)
    if errors and not pending:raise errors[0]


class ReceiveAttachmentController:
    def __init__(self,journal,observe,*,map_factory=CgroupRetentionMap,receive_factory=FileReceiveLink,
                 pin_factory=FilterPinDirectory,fstat=os.fstat,clock=time.monotonic,observe_dma=None,observe_bundle=None):
        self.journal,self.observe=journal,observe
        self.map_factory,self.receive_factory,self.pin_factory=map_factory,receive_factory,pin_factory
        self.fstat,self.clock=fstat,clock
        self.observe_dma=observe_dma
        self.observe_bundle=observe_bundle

    def _dma_fresh(self,policy):
        if not callable(self.observe_dma):raise ValueError('fresh DMA evidence source required')
        value=self.observe_dma()
        validate_dma_observation(policy,value,self.clock())

    def _fresh(self,binding,cgroup_fd,expected=None):
        evidence=self.observe()
        validate_waiting_launch(evidence,binding,cgroup_fd,now=self.clock(),fstat=self.fstat,expected=expected)
        return evidence

    def attach(self,operation,unit,cgroup_fd,*,policy):
        if type(cgroup_fd) is not int or cgroup_fd<0 or type(policy) not in (ReceiveAttachmentPolicy,DmaReceiveAttachmentPolicy):
            raise ValueError('held descriptor and explicit policy required')
        with self.journal.transaction() as tx:
            current=tx.read(operation,unit)
            if current.lifecycle.phase is not Phase.REQUESTED or current.paired is not None or current.lifecycle.owned is not None:
                raise ValueError('paired attachment request cannot replay')
            binding=current.lifecycle.binding
            retained=receive=pins=None
            try:
                if policy.binding!=binding:raise ValueError('receive policy binding mismatch')
                dma=type(policy) is DmaReceiveAttachmentPolicy
                def collect(expected=None):
                    if self.observe_bundle is not None:
                        if not dma or not callable(self.observe_bundle):raise ValueError('DMA bundle source required')
                        return validate_prepare_bundle(self.observe_bundle(),policy,binding,cgroup_fd,
                            now=self.clock(),fstat=self.fstat,expected=expected).launch
                    value=self._fresh(binding,cgroup_fd,expected)
                    if dma:self._dma_fresh(policy)
                    return value
                evidence=collect()
                def fresh():collect(evidence)
                if dma:
                    observed=policy.evidence
                    layout=observed.layout.receive
                    code=compile_dma_receive((binding.cgroup_inode,),evidence.denied_devices,layout=observed.layout,
                        dma_buf_fops=observed.dma_buf_fops,amdgpu_dmabuf_ops=observed.amdgpu_dmabuf_ops,
                        allowed_internal_primary_minor=observed.internal_primary_minor)
                else:
                    layout=policy.layout
                    code=compile_device_receive((binding.cgroup_inode,),evidence.denied_devices,
                        file_inode_offset=layout.file_inode_offset,inode_mode_offset=layout.inode_mode_offset,
                        inode_rdev_offset=layout.inode_rdev_offset)
                if hashlib.sha256(code).hexdigest()!=policy.program_sha256:
                    raise ValueError('compiled receive policy mismatch')
                def change(action,**fields):
                    nonlocal current
                    current=tx.change(operation,unit,current.revision,action,**fields)
                pins=self.pin_factory()
                fresh()
                retained=self.map_factory()
                map_identity=retained.create(cgroup_fd)
                if type(map_identity) is not MapIdentity or retained.identity()!=map_identity:
                    raise ValueError('retention identity unavailable')
                change('retention_intent',map_id=map_identity.map_id)
                fresh()
                retained.pin(pins.fd,paired_token(binding,'retention'),map_identity)
                readback=self.map_factory()
                if readback is retained:raise ValueError('independent retention readback required')
                try:
                    readback.recover(pins.fd,paired_token(binding,'retention'),map_identity)
                    if readback.identity()!=map_identity:raise ValueError('retention readback mismatch')
                finally:readback.close()
                fresh()
                change('retention_confirmed')
                fresh()
                receive=self.receive_factory()
                receive.load_attach(code,hook_btf_id=layout.hook_btf_id)
                receive_identity=receive.link_identity()
                if type(receive_identity) is not ReceiveIdentity or receive_identity.hook_btf_id!=layout.hook_btf_id:
                    raise ValueError('receive identity unavailable')
                change('receive_intent',receive=PairedReceiveIdentity(receive_identity.link_id,
                    receive_identity.program_id,receive_identity.hook_btf_id,receive_identity.target_obj_id))
                fresh()
                receive.pin(pins.fd,paired_token(binding,'receive'),receive_identity)
                readback=self.receive_factory()
                if readback is receive:raise ValueError('independent receive readback required')
                try:
                    readback.recover(pins.fd,paired_token(binding,'receive'),receive_identity)
                    if readback.link_identity()!=receive_identity:raise ValueError('receive readback mismatch')
                finally:readback.close()
                fresh()
                change('receive_confirmed')
                if current.paired.stage is not PairedStage.RECEIVE_CONFIRMED:
                    raise ValueError('receive confirmation not durable')
                _close_all(receive,retained,pins)
                receive=retained=pins=None
                return ReceiveAttachmentResult(current.revision,current.paired,policy.program_sha256)
            except BaseException as error:
                # A failing fsync may have published a revision. Re-read instead
                # of guessing the revision or deleting a possibly durable pin.
                try:
                    latest=tx.read(operation,unit)
                    if latest.lifecycle.binding!=binding:raise ValueError('journal binding changed')
                    if latest.lifecycle.phase is Phase.REQUESTED:
                        try:tx.change(operation,unit,latest.revision,'cancel')
                        except BaseException:
                            latest=tx.read(operation,unit)
                            if latest.lifecycle.binding!=binding or latest.lifecycle.phase is not Phase.CANCELLED:
                                raise
                    elif latest.lifecycle.phase is not Phase.CANCELLED:
                        raise ValueError('cancellation unavailable')
                    latest=tx.read(operation,unit)
                    if latest.lifecycle.phase is not Phase.CANCELLED:raise ValueError('cancellation not durable')
                except BaseException as cancellation_error:
                    raise RuntimeError('paired attachment failed and cancellation is unconfirmed') from cancellation_error
                raise error
            finally:
                _close_all(receive,retained,pins)
