from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from scripts import probe_prepared_recovery_checkpoint as fixture


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.binding=SimpleNamespace(operation='fixture',unit='gamescope-session.service')
        self.record=SimpleNamespace(lifecycle=SimpleNamespace(binding=self.binding,
            phase=fixture.Phase.CANCELLED,owned=object()),paired=SimpleNamespace(stage=fixture.PairedStage.COMPLETE),
            direct_cleanup=fixture.DirectCleanupStage.DETACHED_VERIFIED,delivery_granted=False,revision=4)
        owner=self
        class Journal:
            @contextmanager
            def transaction(self):yield self
            def read(self,*args):return owner.record
            def change(self,*args,**kwargs):
                owner.record.direct_cleanup=fixture.DirectCleanupStage.COMPLETE
                owner.record.revision+=1
        self.journal=Journal()
        self.events=[]
        class Recovery:
            def __init__(self,journal):self.journal=journal
            def recover(self,operation,unit,**kwargs):
                owner.events.append(type(self.journal).__name__)
                with self.journal.transaction() as tx:
                    tx.change(operation,unit,4,'direct_cleanup_complete')
                return SimpleNamespace(outcome='owned_pin_removed',launch_authorized=False,disconnect_clearance=False)
        self.factory=Recovery

    def test_checkpoint_then_fresh_journal_retry(self):
        # Return snapshots, matching real immutable journal read semantics.
        original=self.journal.read
        self.journal.read=lambda *a:SimpleNamespace(**vars(original(*a)))
        result=fixture.retry_checkpoint(self.journal,self.binding,current_boot_hash='a'*64,recovery_factory=self.factory)
        self.assertEqual(result.outcome,'owned_pin_removed')
        self.assertEqual(self.events,['InterruptCompletion','Journal'])
        self.assertEqual(self.record.direct_cleanup,fixture.DirectCleanupStage.COMPLETE)

    def test_unrelated_error_does_not_trigger_retry(self):
        factory=Mock();factory.return_value.recover.side_effect=PermissionError()
        with self.assertRaises(PermissionError):fixture.retry_checkpoint(self.journal,self.binding,
            current_boot_hash='a'*64,recovery_factory=factory)
        self.assertEqual(factory.call_count,1)

    def test_missing_checkpoint_cannot_pass(self):
        factory=Mock()
        with self.assertRaises(ValueError):fixture.retry_checkpoint(self.journal,self.binding,
            current_boot_hash='a'*64,recovery_factory=factory)
        self.assertEqual(factory.call_count,1)

    def test_partial_pair_prevents_fresh_retry(self):
        self.record.paired=None
        with self.assertRaises(ValueError):fixture.retry_checkpoint(self.journal,self.binding,
            current_boot_hash='a'*64,recovery_factory=self.factory)
        self.assertEqual(self.events,['InterruptCompletion'])

    def test_injection_is_once_and_before_delegate(self):
        proxy=fixture.InterruptCompletion(self.journal)
        with proxy.transaction() as tx:
            with self.assertRaises(fixture.CheckpointInterrupted):tx.change('fixture','unit',4,'direct_cleanup_complete')
            self.assertEqual(self.record.revision,4)
            tx.change('fixture','unit',4,'direct_cleanup_complete')
        self.assertEqual(self.record.revision,5)


if __name__=='__main__':unittest.main()
