"""Inactive exact-arm cleanup after durable recovery; never restarts a session.

Caller must independently establish publisher quiescence. The journal lock is
not that evidence. Missing journals and unresolved cleanup retain the arm.
Lock order is journal transaction, then arm writer directory.
"""
from dataclasses import dataclass
import os

from .device_filter_arm import FilterArm, FilterArmStore, MAX_BYTES, decode_arm
from .device_filter_journal import JournalRecord
from .device_filter_lifecycle import Phase, PairedStage, DirectCleanupStage


@dataclass(frozen=True)
class ArmRecoveryResult:
    outcome: str
    arm_absent: bool = True
    launch_authorized: bool = False
    disconnect_clearance: bool = False


def clear_recovered_arm(journal, store, expected_arm, *, current_boot_hash,
                        publisher_quiesced=False):
    if (type(store) is not FilterArmStore or type(expected_arm) is not FilterArm
            or publisher_quiesced is not True or current_boot_hash != expected_arm.boot_hash
            or os.geteuid() != store.owner_uid):
        raise ValueError('exact owner, boot and independent publisher quiescence required')
    with journal.transaction() as tx:
        record = tx.read(expected_arm.operation, expected_arm.unit)
        if type(record) is not JournalRecord:
            raise ValueError('durable recovery record required')
        state = record.lifecycle
        binding = state.binding
        if ((binding.operation, binding.unit, binding.uid, binding.boot_hash, binding.topology_hash)
                != (expected_arm.operation, expected_arm.unit, expected_arm.uid,
                    current_boot_hash, expected_arm.topology_hash)
                or binding.invocation == expected_arm.previous_invocation
                or state.phase is not Phase.CANCELLED or record.delivery_granted
                or (record.paired is not None and record.paired.stage is not PairedStage.COMPLETE)
                or (state.owned is not None and record.direct_cleanup is not DirectCleanupStage.COMPLETE)):
            raise ValueError('durable complete recovery required before arm cleanup')
        with store._writer_directory() as directory:
            name = store._name(expected_arm.unit)
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            except FileNotFoundError:
                # Retry after unlink/fsync uncertainty; absence is not a grant.
                os.fsync(directory)
                return ArmRecoveryResult('arm_already_absent')
            try:
                store._secure(fd, directory=False)
                held = os.fstat(fd)
                raw = bytearray()
                while len(raw) <= MAX_BYTES:
                    chunk = os.read(fd, MAX_BYTES + 1 - len(raw))
                    if not chunk:
                        break
                    raw.extend(chunk)
                if decode_arm(bytes(raw)) != expected_arm:
                    raise ValueError('replacement arm must remain untouched')
                current = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != (held.st_dev, held.st_ino):
                    raise ValueError('arm identity changed before cleanup')
                os.unlink(name, dir_fd=directory)
                os.fsync(directory)
            finally:
                os.close(fd)
            return ArmRecoveryResult('arm_removed')
