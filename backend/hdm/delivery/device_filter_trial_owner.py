"""Durably ordered setup for a fresh supervised prepared-session trial.

No restart is performed here. Persisted scheduling intent is consumed before
returning: a restarted owner must recover, never repeat setup or scheduling.
The external owner retains responsibility for recovery on every exception.
"""
from .device_filter_trial_owner_store import TrialOwnerRecord
from ..ports.presentation_activation import UserServiceOperation


def configure_prepared_trial(store, record, *, legacy, dropins, arms, commands):
    if type(record) is not TrialOwnerRecord or record.phase != 'prepared':
        raise ValueError('fresh prepared trial required')
    if record.arm.unit != 'gamescope-session.service':
        raise ValueError('only the supervised session trial is composed')
    # Exclusive creation must complete before any installed setting changes.
    # Existing records, including interrupted prepared records, are not replayed.
    store.create(record)

    def advance(phase):
        nonlocal record
        record = store.transition(record.arm.operation, record.arm.unit,
            record.phase, phase, expected_record=record)

    advance('legacy_suspending')
    legacy.suspend(record.user, record.arm.unit, record.arm.operation,
                   expected_original=record.legacy_original)
    advance('dropin_applying')
    dropins.apply(record.arm.unit, record.candidate)
    advance('arming')
    arms.arm(record.arm)
    reloaded = commands.run(UserServiceOperation.DAEMON_RELOAD,
        uid=record.user.uid, username=record.user.username)
    if reloaded.ok is not True:
        raise ValueError('trial configuration reload failed; recovery required')
    advance('scheduling')
    return record
