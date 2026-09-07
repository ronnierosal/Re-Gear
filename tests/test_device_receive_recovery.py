from dataclasses import replace
import unittest
from unittest.mock import Mock
from backend.hdm.delivery.device_receive_recovery import ReceiveRecovery
from backend.hdm.delivery.device_receive_kernel import ReceiveIdentity, ReceivePinAbsent
from backend.hdm.delivery.cgroup_retention_map import MapIdentity
from backend.hdm.delivery.device_filter_journal import JournalRecord
from backend.hdm.delivery.device_filter_lifecycle import (FilterLifecycle, Phase, OwnedFilter,
    PairedOwnership, PairedStage, PairedReceiveIdentity, paired_token)
from tests.test_device_filter_journal import binding


class ReceiveRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.binding=binding()
        self.identity=PairedReceiveIdentity(4,5,6,7)
        self.record=JournalRecord(3,FilterLifecycle(self.binding,Phase.CANCELLED),
            paired=PairedOwnership(2,PairedStage.RECEIVE_CONFIRMED,self.identity))
        self.events=[]
        self.tx=Mock()
        self.tx.read.side_effect=lambda *a:self.record
        def change(operation,unit,revision,action):
            self.assertEqual(revision,self.record.revision)
            self.assertEqual(self.record.lifecycle.phase,Phase.CANCELLED)
            self.events.append(action)
            self.record=replace(self.record,revision=revision+1,paired=self.record.paired.advance(action))
            return self.record
        self.tx.change.side_effect=change
        self.map=Mock()
        self.map.identity.return_value=MapIdentity(2)
        self.map.recover.side_effect=lambda *a:self.events.append('map_recover')
        self.map.release_entry.side_effect=lambda *a:self.events.append('delete_entry') or True
        self.receive=Mock()
        self.receive.link_identity.return_value=ReceiveIdentity(4,5,6,7)
        self.receive.probe_program_present.side_effect=lambda *a:self.events.append('absence') or False
        self.directory=Mock(fd=8)
        self.factory=Mock(return_value=self.receive)
        self.unlink=Mock(side_effect=lambda token,**k:self.events.append('unpin_receive' if token==paired_token(self.binding,'receive') else 'unpin_map'))
        self.controller=ReceiveRecovery(map_factory=Mock(return_value=self.map),receive_factory=self.factory,
            directory_factory=Mock(return_value=self.directory),unlink=self.unlink)

    def run_recovery(self,**kwargs):
        return self.controller.recover(self.tx,self.binding.operation,self.binding.unit,
            current_boot_hash=kwargs.pop('current_boot_hash',self.binding.boot_hash),**kwargs)

    def stage(self,value):self.record=replace(self.record,paired=replace(self.record.paired,stage=value))

    def test_progress_order_and_no_authorization(self):
        result=self.run_recovery()
        self.assertTrue(result.completed)
        self.assertFalse(result.launch_authorized);self.assertFalse(result.disconnect_clearance)
        self.assertEqual(self.events,['map_recover','receive_release_pending','unpin_receive','absence',
            'receive_released','retention_release_pending','delete_entry','map_recover','unpin_map','paired_complete'])
        self.map.recover.assert_called_with(8,paired_token(self.binding,'retention'),MapIdentity(2))

    def test_no_kernel_before_cancellation_or_across_boot_or_postgrant(self):
        for phase in (Phase.REQUESTED,Phase.GRANTED,Phase.RECOVERY_REQUIRED):
            owned=None if phase is Phase.REQUESTED else OwnedFilter(42,'d'*64,True,True,43,1234)
            self.record=replace(self.record,lifecycle=FilterLifecycle(self.binding,phase,owned),paired=None)
            self.assertFalse(self.run_recovery().completed)
        self.record=replace(self.record,lifecycle=FilterLifecycle(self.binding,Phase.CANCELLED))
        self.assertFalse(self.run_recovery(current_boot_hash='b'*64).completed)
        self.controller.directory_factory.assert_not_called();self.factory.assert_not_called()

    def test_partial_metadata_never_claims_no_filter(self):
        self.record=replace(self.record,paired=PairedOwnership(2,PairedStage.RETENTION_CONFIRMED))
        self.assertFalse(self.run_recovery().completed)
        self.factory.assert_not_called();self.map.recover.assert_not_called()

    def test_missing_pending_pin_requires_explicit_quiescence(self):
        self.stage(PairedStage.RECEIVE_INTENT)
        self.receive.recover.side_effect=ReceivePinAbsent(2,'missing')
        self.assertFalse(self.run_recovery().completed)
        self.map.release_entry.assert_not_called()
        self.assertTrue(self.run_recovery(prior_owner_quiesced=True).completed)
        self.assertNotIn('unpin_receive',self.events)

    def test_confirmed_missing_pin_and_generic_enoent_are_unresolved(self):
        self.receive.recover.side_effect=ReceivePinAbsent(2,'missing')
        self.assertFalse(self.run_recovery(prior_owner_quiesced=True).completed)
        self.stage(PairedStage.RECEIVE_INTENT)
        self.receive.recover.side_effect=FileNotFoundError(2,'metadata error')
        self.assertFalse(self.run_recovery(prior_owner_quiesced=True).completed)
        self.map.release_entry.assert_not_called()

    def test_receive_release_resume_still_requires_absence(self):
        self.stage(PairedStage.RECEIVE_RELEASED)
        self.receive.probe_program_present.return_value=True
        self.receive.probe_program_present.side_effect=None
        self.controller.clock=Mock(side_effect=[0,3])
        self.assertFalse(self.run_recovery().completed)
        self.map.release_entry.assert_not_called();self.receive.recover.assert_not_called()

    def test_empty_entry_only_allowed_on_preexisting_release_pending(self):
        self.map.release_entry.side_effect=None;self.map.release_entry.return_value=False
        self.assertFalse(self.run_recovery().completed)
        self.assertEqual(self.record.paired.stage,PairedStage.RETENTION_RELEASE_PENDING)
        self.assertTrue(self.run_recovery().completed)

    def test_cas_failure_before_delete_preserves_map_entry(self):
        original=self.tx.change.side_effect
        def change(*args):
            if args[-1]=='retention_release_pending':raise ValueError('CAS conflict')
            return original(*args)
        self.tx.change.side_effect=change
        self.assertFalse(self.run_recovery().completed)
        self.map.release_entry.assert_not_called()

    def test_map_unpin_failure_cannot_commit_complete(self):
        self.unlink.side_effect=PermissionError()
        self.assertFalse(self.run_recovery().completed)
        self.assertNotIn('paired_complete',self.events)
        self.map.close.assert_called();self.directory.close.assert_called()

    def test_role_tokens_distinct_and_nonboolean_quiescence_rejected(self):
        self.assertNotEqual(paired_token(self.binding,'receive'),paired_token(self.binding,'retention'))
        with self.assertRaises(ValueError):self.run_recovery(prior_owner_quiesced=1)
        self.factory.assert_not_called()

    def test_release_pending_missing_pin_resume_requires_quiescence(self):
        self.stage(PairedStage.RECEIVE_RELEASE_PENDING)
        self.receive.recover.side_effect=ReceivePinAbsent(2,'missing')
        self.assertFalse(self.run_recovery().completed)
        self.map.release_entry.assert_not_called()
        self.assertTrue(self.run_recovery(prior_owner_quiesced=True).completed)

    def test_close_failure_attempts_all_and_never_commits_complete(self):
        self.receive.close.side_effect=OSError()
        self.assertFalse(self.run_recovery().completed)
        self.map.close.assert_called();self.directory.close.assert_called()
        self.assertNotIn('paired_complete',self.events)

    def test_complete_cas_failure_preserves_pending_metadata(self):
        original=self.tx.change.side_effect
        def change(*args):
            if args[-1]=='paired_complete':raise ValueError('CAS conflict')
            return original(*args)
        self.tx.change.side_effect=change
        self.assertFalse(self.run_recovery().completed)
        self.assertEqual(self.record.paired.stage,PairedStage.RETENTION_RELEASE_PENDING)
        self.assertIn('unpin_map',self.events)

    def test_absence_error_or_decreasing_clock_preserves_retention(self):
        self.stage(PairedStage.RECEIVE_RELEASED)
        self.receive.probe_program_present.side_effect=PermissionError()
        self.assertFalse(self.run_recovery().completed)
        self.map.release_entry.assert_not_called()
        self.controller.clock=Mock(side_effect=[2,1])
        self.assertFalse(self.run_recovery().completed)
        self.map.release_entry.assert_not_called()

    def test_distinct_receive_readback_closes_before_principal_and_absence(self):
        principal,readback=Mock(),Mock()
        expected=ReceiveIdentity(4,5,6,7)
        principal.link_identity.return_value=readback.link_identity.return_value=expected
        principal.close.side_effect=lambda:self.events.append('principal_close')
        readback.close.side_effect=lambda:self.events.append('readback_close')
        def absent(*args):
            self.assertIn('readback_close',self.events)
            self.assertIn('principal_close',self.events)
            self.assertLess(self.events.index('readback_close'),self.events.index('principal_close'))
            self.events.append('absence')
            return False
        principal.probe_program_present.side_effect=absent
        self.factory.side_effect=[principal,readback]
        self.assertTrue(self.run_recovery().completed)
        principal.recover.assert_called_once_with(8,paired_token(self.binding,'receive'),expected)
        readback.recover.assert_called_once_with(8,paired_token(self.binding,'receive'),expected)
        readback.close.assert_called_once()
        self.assertLess(self.events.index('principal_close'),self.events.index('absence'))

    def test_retry_after_map_unlink_and_failed_complete_stays_unresolved(self):
        original=self.tx.change.side_effect
        def change(*args):
            if args[-1]=='paired_complete':raise ValueError('CAS conflict')
            return original(*args)
        self.tx.change.side_effect=change
        self.assertFalse(self.run_recovery().completed)
        self.assertIn('unpin_map',self.events)
        saved=self.record
        self.assertEqual(saved.paired.stage,PairedStage.RETENTION_RELEASE_PENDING)
        self.events.clear();self.unlink.reset_mock();self.map.release_entry.reset_mock()
        self.map.recover.side_effect=FileNotFoundError(2,'map pin absent after unlink')
        self.tx.change.side_effect=original
        self.tx.change.reset_mock()
        self.assertFalse(self.run_recovery(prior_owner_quiesced=True).completed)
        self.assertEqual(self.record,saved)
        self.tx.change.assert_not_called()
        self.map.release_entry.assert_not_called()
        self.unlink.assert_not_called()


if __name__=='__main__':unittest.main()

