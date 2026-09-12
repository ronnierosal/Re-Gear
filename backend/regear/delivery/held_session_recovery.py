"""User-only recovery executor over pinned unit and lease directory descriptors.

The launcher must independently pin and validate the directories against its
operation record. This module never discovers a device or permits unplugging.
"""
from ..application.held_session_release import (
    HeldSessionPreflight, HeldSessionRecovery, HeldSessionResult, HELD_UNITS)
from ..adapters.steamos.commands import HeldSessionCommandRunner
from .runtime_mask_lease import MaskLeaseJournal, RuntimeMaskLease


def recover(*, units_fd, lease_fd, uid, token, boot_identity, commands=None):
    journal = masks = None
    try:
        commands = commands or HeldSessionCommandRunner(uid)
        journal = MaskLeaseJournal(lease_fd, owner_uid=uid)
        masks = RuntimeMaskLease(units_fd, lease_fd, owner_uid=uid)
        with journal.locked():
            intent = journal.load_intent()
            if intent.token != token or intent.boot_identity != boot_identity:
                return HeldSessionResult('held_recovery.identity_changed')

        def revoke():
            with journal.locked():
                journal.begin_recovery(intent)
            return True

        def restore_masks():
            with journal.locked():
                records = journal.load_masks(intent)
                # Attempt every owned entry even if another entry conflicts.
                outcomes = []
                for record in records:
                    try:
                        outcomes.append(masks.restore(record) is True)
                    except Exception:
                        outcomes.append(False)
                return all(outcomes)

        def verify(prior, units):
            return all(commands.run('state', unit) ==
                       ('active' if unit in prior else 'inactive') for unit in units)

        def finish():
            with journal.locked():
                return journal.finish(intent, lambda: verify(intent.prior_active, HELD_UNITS))

        snapshot = HeldSessionPreflight(token, intent.prior_active, True, True, True, True)
        with journal.recovery_locked():
            with journal.locked():
                completed = journal.is_finished(intent)
            if completed:
                verified = verify(intent.prior_active, HELD_UNITS)
                return HeldSessionResult('held_recovery.already_restored' if verified
                                         else 'held_recovery.state_changed',
                                         restored=verified, journal_retained=not verified)
            return HeldSessionRecovery(revoke=revoke, load=lambda: snapshot,
                restore_masks=restore_masks, reload_manager=lambda: commands.run('reload'),
                start=lambda unit: commands.run('start', unit), verify=verify,
                finish=finish).run()
    except Exception:
        return HeldSessionResult('held_recovery.unavailable')
    finally:
        if masks is not None:
            masks.close()
        if journal is not None:
            journal.close()
