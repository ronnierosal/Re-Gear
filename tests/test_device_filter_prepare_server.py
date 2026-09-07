from contextlib import contextmanager
from dataclasses import replace
import hashlib
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,MagicMock,patch
from backend.hdm.delivery import device_filter_prepare_server as server
from backend.hdm.delivery.device_filter_arm import FilterArm
from backend.hdm.delivery.device_filter_protocol import FilterRequest
from backend.hdm.delivery.device_filter_peer import WaitingPeerIdentity
from backend.hdm.delivery.device_filter_transport import PeerCredentials
from backend.hdm.delivery.device_filter_runtime_peer import RuntimePeerObservation
from backend.hdm.delivery.device_filter_lifecycle import LaunchBinding,FilterLifecycle,Phase,PairedOwnership,PairedStage,PairedReceiveIdentity,OwnedFilter
from backend.hdm.delivery.device_filter_journal import JournalRecord
from backend.hdm.delivery.device_filter_preparation import PreparationResult
from backend.hdm.delivery.device_receive_attachment import DmaReceiveObservation,DmaReceiveAttachmentPolicy
from tests.test_dma_receive_program import LAYOUT,FOPS,OPS


class PrepareServerTests(unittest.TestCase):
    def setUp(self):
        self.arm=FilterArm(1,'op','gamescope-session.service',1000,'a'*64,'b'*64,'c'*64,'d'*32,15)
        self.request=FilterRequest(1,'op',self.arm.unit,'e'*32,'f'*64)
        self.identity=WaitingPeerIdentity(50,1000,60,'e'*32,self.arm.unit,'/fixture',70,80)
        self.binding=LaunchBinding('a'*64,'op',self.arm.unit,'e'*32,1000,50,60,70,80,'b'*64,14)
        self.runtime=SimpleNamespace(digest='1'*64)
        self.source=RuntimePeerObservation(self.identity,self.runtime.digest,2,3)
        self.dma=DmaReceiveObservation(self.binding,LAYOUT,FOPS,OPS,4,'2'*64,10)
        self.policy=DmaReceiveAttachmentPolicy(self.binding,self.dma,'3'*64)
        self.evidence=server.FilterPrepareEvidence('a'*64,'b'*64,'c'*64,self.runtime.digest,((226,128),),
            True,True,True,True,server.IsolationCoverage.UNKNOWN,server.IsolationCoverage.UNRESTRICTED)
        self.held=MagicMock();self.held.__enter__.return_value=self.held;self.held.cgroup_fd=9
        self.held.revalidate.side_effect=lambda:self.identity
        self.arms=Mock();self.arms.read.return_value=self.arm
        self.connection=MagicMock();self.events=[];self.record=None;self.cancel_error=None
        self.tx=Mock();self.tx.read.side_effect=lambda *a:self.record
        def change(operation,unit,revision,action):
            self.assertEqual(revision,self.record.revision);self.assertEqual(action,'cancel')
            self.events.append('cancel')
            if self.cancel_error=='before':raise OSError()
            self.record=replace(self.record,revision=revision+1,lifecycle=self.record.lifecycle.cancel())
            if self.cancel_error=='after':raise OSError()
            return self.record
        self.tx.change.side_effect=change
        @contextmanager
        def transaction():yield self.tx
        self.journal=Mock();self.journal.transaction=transaction
        def create(binding):
            if self.record is not None:raise FileExistsError()
            self.events.append('create');self.record=JournalRecord(1,FilterLifecycle(binding))
        self.journal.create.side_effect=create
        self.prepare_hook=lambda:None
        def preparation(journal,observe,**kwargs):
            def prepare(operation,unit,fd,policy):
                self.events.append('prepare');self.prepare_hook();kwargs['observe_bundle']()
                paired=PairedOwnership(2,PairedStage.RECEIVE_CONFIRMED,PairedReceiveIdentity(3,4,5,6))
                direct=OwnedFilter(7,'4'*64,True,True,8,80)
                self.record=JournalRecord(5,FilterLifecycle(self.binding,Phase.ATTACHED,direct),paired=paired)
                return PreparationResult(5,self.binding,paired,direct)
            return SimpleNamespace(prepare=prepare)
        self.factory=Mock(side_effect=preparation)
        self.observe_dma=Mock(side_effect=lambda held:self.dma)
        self.runtime_observer=Mock(side_effect=lambda held,runtime:self.source)
        self.handler=server.FilterPrepareServer(self.journal,SimpleNamespace(uid=1000),lambda held:self.evidence,self.observe_dma,
            arms=self.arms,clock=lambda:10,observer_factory=Mock(),hold_peer=Mock(return_value=self.held),
            observe_runtime=self.runtime_observer,preparation_factory=self.factory)
        self.receive=patch.object(server,'receive_request',return_value=(PeerCredentials(50,1000,1000),self.request))
        self.receive.start();self.addCleanup(self.receive.stop)

    def handle(self):return self.handler.handle(self.connection,expected_arm=self.arm,runtime=self.runtime,deadline=14,expected_policy=self.policy)

    def test_prepare_is_cancelled_then_closed_without_sender(self):
        result=self.handle()
        self.assertEqual(self.events,['create','prepare','cancel'])
        self.assertTrue(result.recovery_required);self.assertFalse(result.launch_authorized)
        self.assertEqual(result.broker_coverage,server.IsolationCoverage.UNKNOWN)
        self.assertEqual(result.importer_coverage,server.IsolationCoverage.UNRESTRICTED)
        self.assertEqual(self.record.lifecycle.phase,Phase.CANCELLED)
        self.connection.send.assert_not_called();self.connection.sendmsg.assert_not_called()
        self.connection.__exit__.assert_called_once();self.held.__exit__.assert_called_once()
        # Initial auth, one preparation step, and final auth each collect once.
        self.assertEqual(self.observe_dma.call_count,3)
        self.assertEqual(self.runtime_observer.call_count,6)
        self.assertIn('observe_bundle',self.factory.call_args.kwargs)
        self.assertNotIn('observe_dma',self.factory.call_args.kwargs)

    def test_changed_arm_runtime_peer_or_dma_cancels_after_create(self):
        for change in ('arm','runtime','peer','dma'):
            with self.subTest(change=change):
                self.setUp()
                def hook():
                    if change=='arm':self.arms.read.return_value=None
                    elif change=='runtime':self.source=replace(self.source,runtime_digest='5'*64)
                    elif change=='peer':self.identity=replace(self.identity,starttime=61)
                    else:self.dma=replace(self.dma,internal_primary_minor=5)
                self.prepare_hook=hook
                with self.assertRaises(ValueError):self.handle()
                self.assertEqual(self.record.lifecycle.phase,Phase.CANCELLED)
                self.connection.__exit__.assert_called_once()

    def test_duplicate_does_not_cancel_existing_request(self):
        self.handle();revision=self.record.revision
        self.events.clear()
        with self.assertRaises(FileExistsError):self.handle()
        self.assertEqual(self.record.revision,revision);self.assertEqual(self.events,[])

    def test_cancellation_uncertainty_is_reconciled_or_explicit(self):
        self.cancel_error='after';self.handle()
        self.assertEqual(self.record.lifecycle.phase,Phase.CANCELLED)
        self.setUp();self.cancel_error='before'
        with self.assertRaisesRegex(RuntimeError,'cancellation unconfirmed'):self.handle()
        self.assertIsNotNone(self.record.paired);self.assertIsNotNone(self.record.lifecycle.owned)
        self.connection.__exit__.assert_called_once()

    def test_partial_preparation_failure_cancels_and_preserves_identity(self):
        def hook():
            self.record=replace(self.record,paired=PairedOwnership(2,PairedStage.RETENTION_INTENT))
            raise OSError()
        self.prepare_hook=hook
        with self.assertRaises(OSError):self.handle()
        self.assertEqual(self.record.lifecycle.phase,Phase.CANCELLED)
        self.assertEqual(self.record.paired.map_id,2)

    def test_unknown_inherited_or_missing_limitation_type_blocks_create(self):
        for fields in (dict(inherited_scan_complete=False),dict(broker_coverage=True),dict(importer_coverage=None)):
            self.evidence=replace(self.evidence,**fields)
            with self.assertRaises(ValueError):self.handle()
            self.journal.create.assert_not_called()

    def test_deadline_expiry_during_dma_collection_blocks_preparation(self):
        def dma(held):self.handler.clock=lambda:14;return self.dma
        self.observe_dma.side_effect=dma
        with self.assertRaises(ValueError):self.handle()
        self.factory.assert_not_called();self.connection.__exit__.assert_called_once()

    def test_uncertain_create_is_reread_and_cancelled_without_preparation(self):
        original=self.journal.create.side_effect
        def create(binding):
            original(binding)
            raise server.JournalInitialPublicationUncertain(binding)
        self.journal.create.side_effect=create
        with self.assertRaises(OSError):self.handle()
        self.assertEqual(self.record.lifecycle.phase,Phase.CANCELLED)
        self.factory.assert_not_called()
        self.connection.__exit__.assert_called_once()

    def test_lock_timeout_never_cancels_existing_same_binding(self):
        self.handle()
        existing=self.record
        self.events.clear()
        self.journal.create.side_effect=TimeoutError('lock busy before publication')
        with self.assertRaises(TimeoutError):self.handle()
        self.assertIs(self.record,existing)
        self.assertEqual(self.events,[])

    def test_expiry_during_final_peer_check_blocks_create(self):
        calls=0
        def identity():
            nonlocal calls
            calls+=1
            if calls==2:self.handler.clock=lambda:14
            return self.identity
        self.held.revalidate.side_effect=identity
        with self.assertRaises(ValueError):self.handle()
        self.journal.create.assert_not_called()
        self.factory.assert_not_called()

    def test_explicit_combined_source_collects_once_and_keeps_outer_checks(self):
        from backend.hdm.delivery.device_filter_prepared_source import PreparedLaunchCollection
        combined=Mock(side_effect=lambda held:PreparedLaunchCollection(self.evidence,self.dma))
        self.handler.observe_combined=combined
        self.handler.observe_evidence=Mock(side_effect=AssertionError('split evidence called'))
        self.handler.observe_dma=Mock(side_effect=AssertionError('split DMA called'))
        result=self.handle()
        self.assertTrue(result.recovery_required)
        self.assertEqual(combined.call_count,3)
        self.assertEqual(self.runtime_observer.call_count,6)
        self.handler.observe_evidence.assert_not_called();self.handler.observe_dma.assert_not_called()


if __name__=='__main__':unittest.main()
