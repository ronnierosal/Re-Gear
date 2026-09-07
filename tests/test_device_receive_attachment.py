from contextlib import contextmanager
from dataclasses import replace
import hashlib
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from backend.hdm.delivery.device_receive_attachment import ReceiveAttachmentController,ReceiveAttachmentPolicy
from backend.hdm.delivery.device_filter_attachment import AttachmentObservation
from backend.hdm.delivery.device_filter_btf import FileReceiveLayout
from backend.hdm.delivery.device_filter_journal import JournalRecord
from backend.hdm.delivery.device_filter_lifecycle import LaunchBinding,FilterLifecycle,Phase,PairedStage,PairedOwnership,DirectCleanupStage
from backend.hdm.delivery.device_receive_program import compile_device_receive
from backend.hdm.delivery.device_receive_kernel import ReceiveIdentity
from backend.hdm.delivery.cgroup_retention_map import MapIdentity
from backend.hdm.delivery.device_filter_recovery import FilterRecovery
from backend.hdm.delivery.device_receive_recovery import ReceiveRecovery


class ReceiveAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.binding=LaunchBinding('a'*64,'attach','gamescope-session.service','b'*32,1000,50,100,29,1234,'c'*64,30)
        self.evidence=AttachmentObservation(self.binding,((226,128),),True,True)
        self.layout=FileReceiveLayout(5,6,7,64,64,8,16,24,8)
        code=compile_device_receive((1234,),self.evidence.denied_devices,file_inode_offset=8,inode_mode_offset=16,inode_rdev_offset=24)
        self.policy=ReceiveAttachmentPolicy(self.binding,self.layout,'d'*64,hashlib.sha256(code).hexdigest())
        self.record=JournalRecord(1,FilterLifecycle(self.binding))
        self.events=[];self.failure=None;self.cancel_failure=None;self.locked=False
        self.tx=Mock()
        self.tx.read.side_effect=lambda *a:self.record
        def change(operation,unit,revision,action,**evidence):
            self.assertTrue(self.locked);self.assertEqual(revision,self.record.revision)
            self.events.append(action)
            if self.failure==action+'_before' or (action=='cancel' and self.cancel_failure=='before'):
                raise OSError('write failed')
            if action in ('cancel','recover'):
                self.record=replace(self.record,revision=revision+1,lifecycle=self.record.lifecycle.cancel())
            elif action in ('direct_detached_verified','direct_cleanup_complete'):
                required=None if action=='direct_detached_verified' else DirectCleanupStage.DETACHED_VERIFIED
                self.assertIs(self.record.direct_cleanup,required)
                stage=DirectCleanupStage.DETACHED_VERIFIED if action=='direct_detached_verified' else DirectCleanupStage.COMPLETE
                self.record=replace(self.record,revision=revision+1,direct_cleanup=stage)
            else:
                paired=(PairedOwnership(evidence['map_id'],PairedStage.RETENTION_INTENT) if action=='retention_intent'
                        else self.record.paired.advance(action,**evidence))
                self.record=replace(self.record,revision=revision+1,paired=paired)
            if self.failure==action+'_after' or (action=='cancel' and self.cancel_failure=='after'):
                raise OSError('sync failed after publication')
            return self.record
        self.tx.change.side_effect=change
        @contextmanager
        def transaction():
            self.assertFalse(self.locked);self.locked=True
            try:yield self.tx
            finally:self.locked=False
        self.journal=Mock();self.journal.transaction=transaction
        self.retained=Mock();self.retained.create.return_value=MapIdentity(2);self.retained.identity.return_value=MapIdentity(2)
        self.map_readback=Mock();self.map_readback.identity.return_value=MapIdentity(2)
        self.receive=Mock();self.receive.link_identity.return_value=ReceiveIdentity(3,4,5,6)
        self.receive_readback=Mock();self.receive_readback.link_identity.return_value=ReceiveIdentity(3,4,5,6)
        self.maps=Mock(side_effect=[self.retained,self.map_readback]);self.receives=Mock(side_effect=[self.receive,self.receive_readback])
        self.pins=Mock(fd=8)
        self.observe=Mock(side_effect=lambda:self.evidence)
        self.controller=ReceiveAttachmentController(self.journal,self.observe,map_factory=self.maps,receive_factory=self.receives,
            pin_factory=lambda:self.pins,fstat=lambda fd:SimpleNamespace(st_mode=stat.S_IFDIR,st_dev=29,st_ino=1234),clock=lambda:1)

    def attach(self):return self.controller.attach('attach',self.binding.unit,20,policy=self.policy)

    def test_exact_independent_readbacks_and_no_grant(self):
        result=self.attach()
        self.assertEqual(result.ownership.stage,PairedStage.RECEIVE_CONFIRMED)
        self.assertFalse(result.launch_authorized);self.assertFalse(result.disconnect_clearance)
        self.map_readback.recover.assert_called_once();self.receive_readback.recover.assert_called_once()
        self.assertEqual(self.events,['retention_intent','retention_confirmed','receive_intent','receive_confirmed'])
        self.assertEqual(self.record.lifecycle.phase,Phase.REQUESTED)

    def test_published_writes_reread_latest_and_cancel_preserving_ids(self):
        for action in ('retention_intent','retention_confirmed','receive_intent','receive_confirmed'):
            with self.subTest(action=action):
                self.setUp();self.failure=action+'_after'
                with self.assertRaises(OSError):self.attach()
                self.assertEqual(self.record.lifecycle.phase,Phase.CANCELLED)
                self.assertEqual(self.record.paired.map_id,2)
                if action.startswith('receive'):self.assertEqual(self.record.paired.receive.program_id,4)
                self.assertEqual(self.events[-1],'cancel')

    def test_cancellation_write_uncertainty_reconciles_or_reports_unresolved(self):
        self.failure='receive_confirmed_before';self.cancel_failure='after'
        with self.assertRaises(OSError):self.attach()
        self.assertEqual(self.record.lifecycle.phase,Phase.CANCELLED)
        self.setUp();self.failure='receive_confirmed_before';self.cancel_failure='before'
        with self.assertRaisesRegex(RuntimeError,'cancellation is unconfirmed'):self.attach()
        self.assertEqual(self.record.paired.stage,PairedStage.RECEIVE_INTENT)
        self.receive.close.assert_called();self.retained.close.assert_called()

    def test_evidence_change_after_map_publication_blocks_receive_load(self):
        def readback(*args):self.evidence=replace(self.evidence,no_game=False)
        self.map_readback.recover.side_effect=readback
        with self.assertRaises(ValueError):self.attach()
        self.receive.load_attach.assert_not_called();self.receive.pin.assert_not_called()
        self.assertEqual(self.record.lifecycle.phase,Phase.CANCELLED)

    def test_receive_confirmation_failure_is_recoverable_by_actual_coordinator(self):
        self.failure='receive_confirmed_before'
        with self.assertRaises(OSError):self.attach()
        self.assertEqual(self.record.paired.stage,PairedStage.RECEIVE_INTENT)
        self.failure=None
        self.retained.release_entry.return_value=True
        self.receive.probe_program_present.return_value=False
        recovery=ReceiveRecovery(map_factory=lambda:self.retained,receive_factory=lambda:self.receive,
            directory_factory=lambda:self.pins,unlink=Mock())
        result=FilterRecovery(self.journal,receive_recovery=recovery).recover('attach',self.binding.unit,
            current_boot_hash=self.binding.boot_hash)
        self.assertEqual(result.outcome,'cancelled_without_owned_identity')
        self.assertEqual(self.record.paired.stage,PairedStage.COMPLETE)

    def test_replay_never_constructs_additional_kernel_owners(self):
        self.attach()
        count=self.maps.call_count
        with self.assertRaises(ValueError):self.attach()
        self.assertEqual(self.maps.call_count,count)

    def test_policy_hash_or_held_cgroup_mismatch_prevents_kernel_mutation(self):
        self.policy=replace(self.policy,program_sha256='e'*64)
        with self.assertRaises(ValueError):self.attach()
        self.maps.assert_not_called();self.receives.assert_not_called()
        self.setUp();self.controller.fstat=lambda fd:SimpleNamespace(st_mode=stat.S_IFDIR,st_dev=29,st_ino=99)
        with self.assertRaises(ValueError):self.attach()
        self.maps.assert_not_called()

    def test_reused_readback_handle_is_rejected(self):
        self.maps.side_effect=[self.retained,self.retained]
        with self.assertRaises(ValueError):self.attach()
        self.receive.load_attach.assert_not_called()
        self.assertEqual(self.record.lifecycle.phase,Phase.CANCELLED)

    def test_cleanup_failure_attempts_all_and_cancels(self):
        self.receive.close.side_effect=OSError()
        with self.assertRaises(OSError):self.attach()
        self.retained.close.assert_called();self.pins.close.assert_called()
        self.assertEqual(self.record.lifecycle.phase,Phase.CANCELLED)


if __name__=='__main__':unittest.main()
