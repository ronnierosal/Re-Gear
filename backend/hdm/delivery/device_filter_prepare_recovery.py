"""Recover cancelled preparation before clearing its exact launch arm.

The caller must own and stop the preparation process first. This coordinator
does not stop services, restore configuration, or authorize a new launch.
"""
from dataclasses import dataclass

from .device_filter_arm import FilterArm
from .device_filter_arm_recovery import ArmRecoveryResult, clear_recovered_arm
from .device_filter_recovery import FilterRecovery, RecoveryResult
from .device_filter_journal import JournalRecord
from ..ports.presentation_activation import GamescopeUserContext, UserServiceOperation


@dataclass(frozen=True)
class PreparedRecoveryResult:
    filter_outcome: str
    arm_outcome: str
    configuration_restore_required: bool = True
    launch_authorized: bool = False
    disconnect_clearance: bool = False


def recover_prepared_operation(journal, arms, expected_arm, *, observe_boot,
                               publisher_stopped, recovery_factory=FilterRecovery,
                               clear_arm=clear_recovered_arm):
    """Fresh independent observations bracket kernel recovery and arm cleanup.

    Missing journals and post-grant states remain unresolved. In particular,
    this cannot silently turn a failure before preparation into arm absence.
    """
    if (type(expected_arm) is not FilterArm or not callable(observe_boot)
            or not callable(publisher_stopped)):
        raise ValueError('exact arm and independent recovery observations required')

    def verify():
        if publisher_stopped() is not True:
            raise ValueError('preparation publisher is not stopped')
        boot = observe_boot()
        if boot != expected_arm.boot_hash:
            raise ValueError('recovery boot changed')
        current = arms.read(expected_arm.unit)
        if current is not None and current != expected_arm:
            raise ValueError('replacement arm must remain untouched')
        return boot

    boot = verify()
    with journal.transaction() as transaction:
        record = transaction.read(expected_arm.operation, expected_arm.unit)
        if type(record) is not JournalRecord:
            raise ValueError('durable preparation identity required')
        binding = record.lifecycle.binding
        if ((binding.operation, binding.unit, binding.uid, binding.boot_hash,
             binding.topology_hash) != (expected_arm.operation, expected_arm.unit,
             expected_arm.uid, boot, expected_arm.topology_hash)
                or binding.invocation == expected_arm.previous_invocation
                or record.delivery_granted):
            raise ValueError('journal differs from cancelled preparation')
    result = recovery_factory(journal).recover(expected_arm.operation,
        expected_arm.unit, current_boot_hash=boot, prior_owner_quiesced=True)
    if (type(result) is not RecoveryResult or result.launch_authorized
            or result.disconnect_clearance or result.outcome not in
            ('owned_pin_removed', 'cancelled_without_owned_identity')):
        raise ValueError('filter recovery remains unresolved')
    verify()
    cleared = clear_arm(journal, arms, expected_arm, current_boot_hash=boot,
                        publisher_quiesced=True)
    if (type(cleared) is not ArmRecoveryResult or cleared.arm_absent is not True
            or cleared.launch_authorized or cleared.disconnect_clearance):
        raise ValueError('arm recovery remains unresolved')
    verify()
    if arms.read(expected_arm.unit) is not None:
        raise ValueError('arm reappeared after recovery')
    return PreparedRecoveryResult(result.outcome, cleared.outcome)


def restore_prepared_session(journal, arms, expected_arm, *, user, dropins,
                             commands, expected_candidate, legacy, expected_legacy_original,
                             observe_boot, publisher_stopped,
                             observe_idle, recover=recover_prepared_operation):
    """Restore the Gamescope trial only after exact filter/arm recovery.

    This is an explicit controller operation, not an automatic RPC. Command
    acceptance is not proof of a working session. Caller retains the durable
    trial and must verify the restarted display before completing recovery.
    """
    if (type(expected_arm) is not FilterArm
            or expected_arm.unit != 'gamescope-session.service'
            or type(user) is not GamescopeUserContext or user.uid != expected_arm.uid
            or type(expected_candidate) is not bytes or not expected_candidate
            or not callable(observe_idle)):
        raise ValueError('exact Gamescope trial recovery context required')
    result = recover(journal, arms, expected_arm, observe_boot=observe_boot,
                     publisher_stopped=publisher_stopped)
    if (type(result) is not PreparedRecoveryResult or result.launch_authorized
            or result.disconnect_clearance):
        raise ValueError('prepared recovery did not complete')
    # Stop at any failed step: failed restoration must never restart into a
    # still-armed or foreign configuration. Store.restore is retryable.
    dropins.restore(expected_arm.unit, expected_candidate=expected_candidate)
    legacy.restore(user, expected_arm.unit, expected_arm.operation,
                   expected_original=expected_legacy_original)
    if publisher_stopped() is not True or observe_boot() != expected_arm.boot_hash:
        raise ValueError('recovery owner or boot changed before reload')
    if arms.read(expected_arm.unit) is not None:
        raise ValueError('session arm reappeared before reload')
    reloaded = commands.run(UserServiceOperation.DAEMON_RELOAD,
                            uid=user.uid, username=user.username)
    if reloaded.ok is not True:
        raise ValueError('restored configuration reload failed')
    if (publisher_stopped() is not True or observe_boot() != expected_arm.boot_hash
            or arms.read(expected_arm.unit) is not None or observe_idle() is not True):
        raise ValueError('fresh idle unarmed session required for recovery restart')
    restarted = commands.run(UserServiceOperation.RESTART_GAMESCOPE_SESSION,
                             uid=user.uid, username=user.username)
    if restarted.ok is not True:
        raise ValueError('normal session restart failed; recovery incomplete')
    return 'normal_session_restart_requested_unverified'
