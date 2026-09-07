"""Recovery-only paired receive ownership under an already-held journal lock.

No lock acquisition, launch grant, runtime integration, or device selection.
Explicit prior-owner quiescence is independent evidence, never inferred from
holding the lock. Any incomplete metadata or uncertain kernel result retains
retention ownership for a later coordinated recovery.
"""
from dataclasses import dataclass
import math
import os
import re
import sys
import time

from .cgroup_retention_map import CgroupRetentionMap, MapIdentity
from .device_receive_kernel import FileReceiveLink, ReceiveIdentity, ReceivePinAbsent
from .device_filter_lifecycle import Phase, PairedStage, PairedOwnership, PairedReceiveIdentity, paired_token
from .device_filter_pin_directory import FilterPinDirectory


@dataclass(frozen=True)
class ReceiveRecoveryResult:
    outcome: str
    revision: int
    completed: bool = False
    launch_authorized: bool = False
    disconnect_clearance: bool = False


def _close_all(*owners):
    pending=sys.exc_info()[0] is not None
    errors=[]
    for owner in owners:
        if owner is not None:
            try:owner.close()
            except Exception as error:errors.append(error)
    if errors and not pending:raise errors[0]


class ReceiveRecovery:
    def __init__(self, *, map_factory=CgroupRetentionMap, receive_factory=FileReceiveLink,
                 directory_factory=FilterPinDirectory, unlink=os.unlink,
                 clock=time.monotonic, sleep=time.sleep):
        self.map_factory=map_factory
        self.receive_factory=receive_factory
        self.directory_factory=directory_factory
        self.unlink=unlink
        self.clock=clock
        self.sleep=sleep

    def _absent(self,owner,program_id):
        previous=self.clock()
        if type(previous) not in (int,float) or not math.isfinite(previous):
            raise ValueError('clock unavailable')
        deadline=previous+2
        for _ in range(102):
            current=self.clock()
            if (type(current) not in (int,float) or not math.isfinite(current)
                    or current<previous or current>=deadline):
                raise ValueError('program absence deadline unresolved')
            previous=current
            present=owner.probe_program_present(program_id)
            if present is False:return
            if present is not True:raise ValueError('program presence unknown')
            self.sleep(.02)
        raise ValueError('program absence unresolved')

    def recover(self,transaction,operation,unit,*,current_boot_hash,prior_owner_quiesced=False):
        if (type(current_boot_hash) is not str or re.fullmatch(r'[0-9a-f]{64}',current_boot_hash) is None
                or type(prior_owner_quiesced) is not bool):
            raise ValueError('explicit fresh recovery evidence required')
        record=transaction.read(operation,unit)
        def result(outcome,completed=False):
            return ReceiveRecoveryResult(outcome,record.revision,completed)
        state=record.lifecycle
        if state.binding.boot_hash!=current_boot_hash:return result('different_boot_unresolved')
        if state.phase in (Phase.GRANTED,Phase.RECOVERY_REQUIRED):return result('session_recovery_required')
        if state.phase is not Phase.CANCELLED:return result('cancellation_required')
        paired=record.paired
        if paired is None:return result('paired_not_present',True)
        if type(paired) is not PairedOwnership:return result('paired_metadata_unresolved')
        if paired.stage is PairedStage.COMPLETE:return result('paired_complete',True)
        if type(paired.receive) is not PairedReceiveIdentity:return result('paired_metadata_unresolved')
        supported=(PairedStage.RECEIVE_INTENT,PairedStage.RECEIVE_CONFIRMED,
            PairedStage.RECEIVE_RELEASE_PENDING,PairedStage.RECEIVE_RELEASED,PairedStage.RETENTION_RELEASE_PENDING)
        if paired.stage not in supported:return result('paired_stage_unresolved')
        expected_map=MapIdentity(paired.map_id)
        owned=paired.receive
        expected=ReceiveIdentity(owned.link_id,owned.program_id,owned.hook_btf_id,owned.target_obj_id)
        map_token=paired_token(state.binding,'retention')
        receive_token=paired_token(state.binding,'receive')
        initial_stage=paired.stage
        retained=receive=directory=None
        def change(action):
            nonlocal record
            record=transaction.change(operation,unit,record.revision,action)
        try:
            directory=self.directory_factory()
            retained=self.map_factory()
            retained.recover(directory.fd,map_token,expected_map)
            if retained.identity()!=expected_map:raise ValueError('retention identity mismatch')
            receive=self.receive_factory()
            released=initial_stage in (PairedStage.RECEIVE_RELEASED,PairedStage.RETENTION_RELEASE_PENDING)
            if not released:
                missing=False
                try:receive.recover(directory.fd,receive_token,expected)
                except ReceivePinAbsent:
                    if (initial_stage not in (PairedStage.RECEIVE_INTENT,PairedStage.RECEIVE_RELEASE_PENDING)
                            or prior_owner_quiesced is not True):raise
                    missing=True
                if not missing:
                    if receive.link_identity()!=expected:raise ValueError('receive identity mismatch')
                    if initial_stage is not PairedStage.RECEIVE_RELEASE_PENDING:change('receive_release_pending')
                    check=self.receive_factory()
                    try:
                        check.recover(directory.fd,receive_token,expected)
                        if check.link_identity()!=expected:raise ValueError('receive pin identity mismatch')
                        self.unlink(receive_token,dir_fd=directory.fd)
                    finally:check.close()
                receive.close()
                self._absent(receive,expected.program_id)
                if record.paired.stage is not PairedStage.RECEIVE_RELEASE_PENDING:
                    change('receive_release_pending')
                change('receive_released')
            else:
                self._absent(receive,expected.program_id)
            if record.paired.stage is not PairedStage.RETENTION_RELEASE_PENDING:
                change('retention_release_pending')
            if retained.identity()!=expected_map:raise ValueError('retention identity changed')
            removed=retained.release_entry(expected_map)
            if removed is not True and not (removed is False and initial_stage is PairedStage.RETENTION_RELEASE_PENDING):
                raise ValueError('retention entry deletion unresolved')
            check_map=self.map_factory()
            try:
                check_map.recover(directory.fd,map_token,expected_map)
                if check_map.identity()!=expected_map:raise ValueError('retention pin identity mismatch')
                self.unlink(map_token,dir_fd=directory.fd)
            finally:check_map.close()
            _close_all(receive,retained,directory)
            receive=retained=directory=None
            change('paired_complete')
            return result('paired_complete',True)
        except (OSError,ValueError,RuntimeError):
            return result('paired_recovery_unresolved')
        finally:
            try:_close_all(receive,retained,directory)
            except (OSError,ValueError,RuntimeError):
                return result('paired_recovery_unresolved')
