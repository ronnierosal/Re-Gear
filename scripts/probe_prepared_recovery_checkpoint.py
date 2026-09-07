"""Explicit disposable direct-cleanup retry and private arm reconciliation.

No system arm path, player unit or launch authority is used. Private directories
remain as same-boot evidence, including unresolved arms after any failure.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys

if Path(__file__).name!='__main__.py':
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))

from hdm.delivery.device_filter_arm import FilterArm,FilterArmStore
from hdm.delivery.device_filter_arm_recovery import clear_recovered_arm
from hdm.delivery.device_filter_recovery import FilterRecovery
from hdm.delivery.device_filter_lifecycle import Phase,PairedStage,DirectCleanupStage
from scripts.probe_paired_journal_fixture import run_fixture,create_journal_directory
from scripts.probe_filter_preparation_fixture import publish_preparation,recover_preparation


class CheckpointInterrupted(RuntimeError):
    """Fixture injection before completion commit, not an arbitrary I/O error."""


class InterruptCompletion:
    def __init__(self,journal):self.journal=journal;self.fired=False

    @contextmanager
    def transaction(self):
        with self.journal.transaction() as tx:
            owner=self
            class Transaction:
                def read(self,*args):return tx.read(*args)
                def change(self,*args,**kwargs):
                    if args[-1]=='direct_cleanup_complete' and not owner.fired:
                        owner.fired=True
                        raise CheckpointInterrupted('disposable completion checkpoint')
                    return tx.change(*args,**kwargs)
            yield Transaction()


def retry_checkpoint(journal,binding,*,current_boot_hash,recovery_factory=FilterRecovery):
    proxy=InterruptCompletion(journal)
    try:
        recovery_factory(proxy).recover(binding.operation,binding.unit,current_boot_hash=current_boot_hash)
    except CheckpointInterrupted:pass
    else:raise ValueError('expected completion checkpoint not reached')
    if not proxy.fired:raise ValueError('unowned checkpoint interruption')
    with journal.transaction() as tx:pending=tx.read(binding.operation,binding.unit)
    if (pending.lifecycle.binding!=binding or pending.lifecycle.phase is not Phase.CANCELLED
            or pending.paired is None or pending.paired.stage is not PairedStage.COMPLETE
            or pending.direct_cleanup is not DirectCleanupStage.DETACHED_VERIFIED or pending.delivery_granted):
        raise ValueError('durable detached checkpoint unavailable')
    result=recovery_factory(journal).recover(binding.operation,binding.unit,current_boot_hash=current_boot_hash)
    with journal.transaction() as tx:complete=tx.read(binding.operation,binding.unit)
    if (result.outcome!='owned_pin_removed' or result.launch_authorized or result.disconnect_clearance
            or complete.lifecycle.binding!=binding or complete.lifecycle.phase is not Phase.CANCELLED
            or complete.direct_cleanup is not DirectCleanupStage.COMPLETE
            or complete.paired!=pending.paired or complete.lifecycle.owned!=pending.lifecycle.owned
            or complete.revision<=pending.revision or complete.delivery_granted):
        raise ValueError('fresh retry not durably complete')
    return result


def recover_checkpoint(journal_factory,binding,*,current_boot_hash,observe_denial,observe_restored):
    # create_journal_directory authenticates /run and creates a new private leaf.
    _,directory=create_journal_directory()
    try:
        store=FilterArmStore(owner_uid=0,trusted_directory_fd=directory)
        previous='0'*32 if binding.invocation!='0'*32 else '1'*32
        arm=FilterArm(1,binding.operation,binding.unit,binding.uid,binding.boot_hash,
            binding.topology_hash,'a'*64,previous,binding.deadline)
        store.arm(arm)
        class Recovery:
            def __init__(self,journal):self.journal=journal
            def recover(self,operation,unit,*,current_boot_hash):
                if (operation,unit)!=(binding.operation,binding.unit):raise ValueError('fixture identity changed')
                return retry_checkpoint(self.journal,binding,current_boot_hash=current_boot_hash)
        report=recover_preparation(journal_factory,binding,current_boot_hash=current_boot_hash,
            observe_denial=observe_denial,observe_restored=observe_restored,recovery_factory=Recovery)
        journal=journal_factory()
        # The synchronous fixture publisher has returned and closed its handles;
        # no background publisher exists. This is not inferred from a lock.
        first=clear_recovered_arm(journal,store,arm,current_boot_hash=current_boot_hash,publisher_quiesced=True)
        if first.outcome!='arm_removed' or store.read(binding.unit) is not None:
            raise ValueError('private arm removal not observed')
        second=clear_recovered_arm(journal,store,arm,current_boot_hash=current_boot_hash,publisher_quiesced=True)
        if second.outcome!='arm_already_absent' or not first.arm_absent or not second.arm_absent:
            raise ValueError('private arm retry not idempotent')
        report.update(direct_completion_checkpoint_verified=True,private_arm_cleared=True,
            private_arm_retry_verified=True,private_arm_directory_retained=True)
        return report
    finally:os.close(directory)


def main():
    if sys.argv[1:]!=['--disposable-recovery-checkpoint']:
        raise SystemExit('Explicit --disposable-recovery-checkpoint required')
    report=run_fixture(publisher=publish_preparation,recoverer=recover_checkpoint)
    print(json.dumps(report,sort_keys=True))
    return 0 if report['state']=='fixture_passed' else 1


if __name__=='__main__':raise SystemExit(main())
