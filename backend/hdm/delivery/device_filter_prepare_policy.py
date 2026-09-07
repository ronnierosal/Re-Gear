"""Derive a preparation-only policy after independent waiting-peer authentication.

The caller owns held-peer authentication and runtime verification. This builder
compares their identities; it creates no journal, attachment, or launch grant.
"""
import hashlib
import math
import re
import time

from .device_filter_arm import FilterArm
from .device_filter_peer import WaitingPeerIdentity
from .device_filter_lifecycle import LaunchBinding
from .device_filter_prepared_source import PreparedLaunchCollection
from .device_filter_session_prepare import SessionEntryPreparedCollection
from .device_filter_prepare_server import IsolationCoverage
from .device_filter_program import compile_device_filter
from .device_receive_attachment import DmaReceiveAttachmentPolicy, validate_dma_observation
from .dma_receive_program import compile_dma_receive


def build_prepare_policy(held, collection, *, expected_arm, runtime, deadline,
                         expected_denied_devices, clock=time.monotonic):
    arm = expected_arm
    if type(arm) is not FilterArm:
        raise ValueError("independent arm required")
    required = (SessionEntryPreparedCollection if arm.unit == "gamescope-session.service"
                else PreparedLaunchCollection)
    if type(collection) is not required:
        raise ValueError("exact prepared collection role required")
    if type(runtime.digest) is not str or re.fullmatch(r"[0-9a-f]{64}", runtime.digest) is None:
        raise ValueError("independent runtime identity required")
    compile_device_filter(expected_denied_devices)
    first = clock()
    if (type(first) not in (int, float) or not math.isfinite(first) or first < 0
            or type(deadline) not in (int, float) or not math.isfinite(deadline)
            or not first < deadline <= arm.deadline or deadline-first > 5):
        raise ValueError("bounded current preparation deadline required")
    identity = held.revalidate()
    if type(identity) is not WaitingPeerIdentity:
        raise ValueError("authenticated held identity required")
    evidence, dma = collection.evidence, collection.dma
    arm.require_current(unit=identity.unit, uid=identity.uid,
        boot_hash=evidence.boot_hash, topology_hash=evidence.topology_hash,
        config_hash=evidence.config_hash, invocation=identity.invocation, now=first)
    if (evidence.runtime_digest != runtime.digest or evidence.denied_devices != expected_denied_devices
            or any(value is not True for value in (evidence.no_game, evidence.effective_launch_verified,
                evidence.inherited_scan_complete, evidence.inherited_descriptors_free))
            or type(evidence.broker_coverage) is not IsolationCoverage
            or type(evidence.importer_coverage) is not IsolationCoverage):
        raise ValueError("prepared evidence differs from independent expectations")
    binding = LaunchBinding(arm.boot_hash, arm.operation, arm.unit, identity.invocation,
        identity.uid, identity.pid, identity.starttime, identity.cgroup_dev,
        identity.cgroup_inode, arm.topology_hash, deadline)
    if dma.binding != binding:
        raise ValueError("DMA evidence differs from held service identity")
    code = compile_dma_receive((binding.cgroup_inode,), expected_denied_devices,
        layout=dma.layout, dma_buf_fops=dma.dma_buf_fops,
        amdgpu_dmabuf_ops=dma.amdgpu_dmabuf_ops,
        allowed_internal_primary_minor=dma.internal_primary_minor)
    policy = DmaReceiveAttachmentPolicy(binding, dma, hashlib.sha256(code).hexdigest())
    if held.revalidate() != identity:
        raise ValueError("held peer changed during policy derivation")
    final = clock()
    if type(final) not in (int, float) or not math.isfinite(final) or final < first:
        raise ValueError("preparation clock regressed")
    validate_dma_observation(policy, dma, final)
    return policy
