"""Serialized startup recovery for owned filters; no launch delivery or RPC.

A missing pin is not release evidence. Post-grant ownership is retained for
coordinated session recovery. Callers supply the freshly observed boot hash;
this module never treats a journal boot value as a current observation.
Only an already durable exact detach proof permits missing-pin cleanup resume.
"""
from dataclasses import dataclass
import os
import re

from .device_filter_kernel import CgroupDeviceLink, LinkIdentity, DirectPinAbsent
from .device_filter_lifecycle import Phase, PairedStage, DirectCleanupStage
from .device_filter_pin_directory import FilterPinDirectory, pin_token


@dataclass(frozen=True)
class RecoveryResult:
    outcome: str
    revision: int
    launch_authorized: bool = False
    disconnect_clearance: bool = False


class FilterRecovery:
    def __init__(self, journal, *, kernel_factory=CgroupDeviceLink,
                 directory_factory=FilterPinDirectory, unlink=os.unlink, receive_recovery=None):
        self.journal = journal
        self.kernel_factory = kernel_factory
        self.directory_factory = directory_factory
        self.unlink = unlink
        self.receive_recovery = receive_recovery

    def recover(self, operation, unit, *, current_boot_hash, prior_owner_quiesced=False):
        if type(prior_owner_quiesced) is not bool:
            raise ValueError("explicit owner quiescence evidence required")
        if type(current_boot_hash) is not str or re.fullmatch(r"[0-9a-f]{64}", current_boot_hash) is None:
            raise ValueError("fresh boot identity required")
        with self.journal.transaction() as transaction:
            record = transaction.read(operation, unit)
            state = record.lifecycle
            if state.binding.boot_hash != current_boot_hash:
                # Kernel IDs can recycle across boots. Do not open any pin.
                return RecoveryResult("different_boot_unresolved", record.revision)
            if state.phase not in (Phase.CANCELLED, Phase.RECOVERY_REQUIRED):
                record = transaction.change(operation, unit, record.revision, "recover")
                state = record.lifecycle
            if state.phase is Phase.RECOVERY_REQUIRED:
                return RecoveryResult("session_recovery_required", record.revision)
            if record.paired is not None:
                recovery = self.receive_recovery
                if recovery is None:
                    from .device_receive_recovery import ReceiveRecovery
                    recovery = ReceiveRecovery()
                paired_result = recovery.recover(transaction, operation, unit,
                    current_boot_hash=current_boot_hash,
                    prior_owner_quiesced=prior_owner_quiesced)
                if paired_result.completed is not True:
                    return RecoveryResult(paired_result.outcome, paired_result.revision)
                latest = transaction.read(operation, unit)
                if (latest.lifecycle.binding != state.binding
                        or latest.lifecycle.phase is not Phase.CANCELLED
                        or latest.paired is None or latest.paired.stage is not PairedStage.COMPLETE):
                    raise ValueError("paired recovery completion not durable")
                record, state = latest, latest.lifecycle
            if not state.owned_detach_allowed:
                return RecoveryResult("cancelled_without_owned_identity", record.revision)
            if record.direct_cleanup is DirectCleanupStage.COMPLETE:
                return RecoveryResult("owned_pin_removed", record.revision)
            expected = LinkIdentity(state.owned.link_id, state.owned.program_id,
                                    state.owned.kernel_cgroup_id)
            token = pin_token(state.binding)
            missing = False
            with self.directory_factory() as directory:
                if record.direct_cleanup is None:
                    try:
                        with self.kernel_factory() as kernel:
                            try:
                                kernel.recover(directory.fd, token, expected)
                            except (ValueError, RuntimeError):
                                kernel.recover_detached(directory.fd, token, expected)
                            else:
                                kernel.detach(expected)
                            # Release principal ownership before independent readback.
                            kernel.close()
                    except DirectPinAbsent:
                        return RecoveryResult("pin_missing_unverified", record.revision)
                # Exact inert identity from an independently acquired descriptor.
                with self.kernel_factory() as readback:
                    try:
                        readback.recover_detached(directory.fd, token, expected)
                    except DirectPinAbsent:
                        if record.direct_cleanup is not DirectCleanupStage.DETACHED_VERIFIED:
                            return RecoveryResult("pin_missing_unverified", record.revision)
                        missing = True
                    if not missing:
                        if record.direct_cleanup is None:
                            record = transaction.change(operation, unit, record.revision, "direct_detached_verified")
                            if record.direct_cleanup is not DirectCleanupStage.DETACHED_VERIFIED:
                                raise ValueError("direct detach proof not durable")
                        self.unlink(token, dir_fd=directory.fd)
                # All acquired BPF descriptors and the directory close before
                # COMPLETE. A failed close never becomes missing-pin evidence.
            record = transaction.change(operation, unit, record.revision, "direct_cleanup_complete")
            if record.direct_cleanup is not DirectCleanupStage.COMPLETE:
                raise ValueError("direct cleanup completion not durable")
            return RecoveryResult("owned_pin_removed", record.revision)
