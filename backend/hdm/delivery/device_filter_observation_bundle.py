"""One immutable fresh collection; never cached or renewed between checks."""
from __future__ import annotations
from dataclasses import dataclass,field
from typing import TYPE_CHECKING
from .device_filter_attachment import AttachmentObservation,validate_waiting_launch
if TYPE_CHECKING:
    from .device_receive_attachment import DmaReceiveObservation


@dataclass(frozen=True)
class PrepareObservationBundle:
    launch: AttachmentObservation
    dma: DmaReceiveObservation = field(repr=False)

    def __post_init__(self):
        from .device_receive_attachment import DmaReceiveObservation
        if type(self.launch) is not AttachmentObservation or type(self.dma) is not DmaReceiveObservation:
            raise ValueError('typed launch and DMA collection required')
        if self.launch.binding!=self.dma.binding:raise ValueError('bundle binding mismatch')


def validate_prepare_bundle(bundle,policy,binding,cgroup_fd,*,now,fstat,expected=None):
    from .device_receive_attachment import validate_dma_observation
    if type(bundle) is not PrepareObservationBundle:raise ValueError('typed fresh collection required')
    validate_waiting_launch(bundle.launch,binding,cgroup_fd,now=now,fstat=fstat,expected=expected)
    validate_dma_observation(policy,bundle.dma,now)
    return bundle
