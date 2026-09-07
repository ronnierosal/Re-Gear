from dataclasses import replace
from unittest.mock import Mock
import unittest
from tests import test_device_receive_attachment as attachment_tests
from backend.hdm.delivery.device_filter_preparation import FilterPreparation
from backend.hdm.delivery.device_receive_attachment import ReceiveAttachmentController
from backend.hdm.delivery.device_filter_attachment import FilterAttachmentController
from backend.hdm.delivery.device_filter_lifecycle import Phase,PairedStage
from backend.hdm.delivery.device_filter_kernel import LinkIdentity
from backend.hdm.delivery.device_filter_recovery import FilterRecovery
from backend.hdm.delivery.device_receive_recovery import ReceiveRecovery


class FilterPreparationTests(unittest.TestCase):
    def setUp(self):
        self.base=attachment_tests.ReceiveAttachmentTests();self.base.setUp();b=self.base
        previous=b.tx.change.side_effect
        def change(operation,unit,revision,action,**evidence):
            if action in ('prepare_pin','attach'):
                self.assertEqual(revision,b.record.revision)
                b.events.append(action)
                state=(b.record.lifecycle.prepare_pin(**evidence) if action=='prepare_pin'
                       else b.record.lifecycle.attach(**evidence))
                b.record=replace(b.record,revision=revision+1,lifecycle=state)
                return b.record
            return previous(operation,unit,revision,action,**evidence)
        b.tx.change.side_effect=change
        self.direct=Mock()
        self.direct.__enter__=Mock(return_value=self.direct);self.direct.__exit__=Mock(return_value=False)
        self.direct.program_id.return_value=42
        self.direct.link_identity.return_value=LinkIdentity(43,42,1234)
        self.attached=False
        self.direct.query_program_ids.side_effect=lambda fd:(42,) if self.attached else ()
        def attach(fd):self.attached=True
        self.direct.attach.side_effect=attach
        self.direct_pins=Mock(fd=9)
        self.direct_pins.__enter__=Mock(return_value=self.direct_pins);self.direct_pins.__exit__=Mock(return_value=False)
        self.pair_factory=Mock(side_effect=lambda journal,observe,**kwargs:ReceiveAttachmentController(journal,observe,
            map_factory=b.maps,receive_factory=b.receives,pin_factory=lambda:b.pins,**kwargs))
        self.direct_factory=Mock(side_effect=lambda journal,observe,**kwargs:FilterAttachmentController(journal,observe,
            kernel_factory=lambda:self.direct,pin_factory=lambda:self.direct_pins,**kwargs))
        self.controller=FilterPreparation(b.journal,b.observe,paired_factory=self.pair_factory,
            direct_factory=self.direct_factory,fstat=b.controller.fstat,clock=lambda:1)

    def prepare(self):return self.controller.prepare('attach',self.base.binding.unit,20,policy=self.base.policy)

    def test_both_existing_controllers_prepare_without_grant(self):
        result=self.prepare()
        self.assertTrue(result.prepared);self.assertFalse(result.launch_authorized);self.assertFalse(result.disconnect_clearance)
        self.assertEqual(result.paired.stage,PairedStage.RECEIVE_CONFIRMED)
        self.assertEqual(result.direct.program_id,42)
        self.assertEqual(self.base.record.lifecycle.phase,Phase.ATTACHED)
        self.assertEqual(self.base.events,['retention_intent','retention_confirmed','receive_intent',
            'receive_confirmed','prepare_pin','attach'])

    def test_paired_failure_never_constructs_direct_controller(self):
        self.base.receive.pin.side_effect=OSError()
        with self.assertRaises(OSError):self.prepare()
        self.direct_factory.assert_not_called()
        self.assertEqual(self.base.record.lifecycle.phase,Phase.CANCELLED)

    def test_cancellation_between_stages_blocks_direct(self):
        original=self.pair_factory.side_effect
        def pair(*args,**kwargs):
            controller=original(*args,**kwargs)
            attach=controller.attach
            def wrapped(*args,**kwargs):
                result=attach(*args,**kwargs)
                self.base.record=replace(self.base.record,revision=self.base.record.revision+1,
                    lifecycle=self.base.record.lifecycle.cancel())
                return result
            controller.attach=wrapped
            return controller
        self.pair_factory.side_effect=pair
        with self.assertRaises(ValueError):self.prepare()
        self.direct_factory.assert_not_called()

    def test_changed_devices_between_stages_are_rejected(self):
        original=self.pair_factory.side_effect
        def pair(*args,**kwargs):
            controller=original(*args,**kwargs);attach=controller.attach
            def wrapped(*args,**kwargs):
                result=attach(*args,**kwargs)
                self.base.evidence=replace(self.base.evidence,denied_devices=((226,129),))
                return result
            controller.attach=wrapped;return controller
        self.pair_factory.side_effect=pair
        with self.assertRaises(ValueError):self.prepare()
        self.direct_factory.assert_not_called()
        self.assertEqual(self.base.record.lifecycle.phase,Phase.CANCELLED)

    def test_direct_pin_failure_retains_pair_and_direct_owners(self):
        self.direct.pin.side_effect=OSError()
        with self.assertRaises(OSError):self.prepare()
        self.assertEqual(self.base.record.lifecycle.phase,Phase.CANCELLED)
        self.assertEqual(self.base.record.paired.stage,PairedStage.RECEIVE_CONFIRMED)
        self.assertEqual(self.base.record.lifecycle.owned.program_id,42)

    def test_actual_recovery_releases_pair_before_direct(self):
        self.prepare();b=self.base;events=[]
        b.retained.release_entry.side_effect=lambda *a:events.append('map_release') or True
        b.receive.probe_program_present.return_value=False
        paired=ReceiveRecovery(map_factory=lambda:b.retained,receive_factory=lambda:b.receive,
            directory_factory=lambda:b.pins,unlink=Mock())
        self.direct.recover.side_effect=lambda *a:events.append('direct_recover')
        recovery=FilterRecovery(b.journal,receive_recovery=paired,kernel_factory=lambda:self.direct,
            directory_factory=lambda:self.direct_pins,unlink=Mock())
        result=recovery.recover('attach',b.binding.unit,current_boot_hash=b.binding.boot_hash)
        self.assertEqual(result.outcome,'owned_pin_removed')
        self.assertEqual(events,['map_release','direct_recover'])
        self.assertEqual(b.record.paired.stage,PairedStage.COMPLETE)
        self.assertEqual(b.record.direct_cleanup.value,'complete')

    def test_replay_refused_without_new_controllers(self):
        self.prepare();count=self.pair_factory.call_count
        with self.assertRaises(ValueError):self.prepare()
        self.assertEqual(self.pair_factory.call_count,count)

    def test_final_observation_change_prevents_prepared_result(self):
        original=self.direct_factory.side_effect
        def direct(*args,**kwargs):
            controller=original(*args,**kwargs);attach=controller.attach
            def wrapped(*args,**kwargs):
                result=attach(*args,**kwargs)
                self.base.evidence=replace(self.base.evidence,waiting_wrapper_verified=False)
                return result
            controller.attach=wrapped;return controller
        self.direct_factory.side_effect=direct
        with self.assertRaises(ValueError):self.prepare()
        self.assertEqual(self.base.record.lifecycle.phase,Phase.CANCELLED)


if __name__=='__main__':unittest.main()

