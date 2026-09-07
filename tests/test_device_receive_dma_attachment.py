from dataclasses import replace
import hashlib
import unittest
from unittest.mock import Mock
from tests import test_device_receive_attachment as char_tests
from tests import test_device_filter_preparation as preparation_tests
from tests.test_dma_receive_program import LAYOUT,FOPS,OPS
from backend.hdm.delivery.device_receive_attachment import DmaReceiveObservation,DmaReceiveAttachmentPolicy
from backend.hdm.delivery.dma_receive_program import compile_dma_receive
from backend.hdm.delivery.device_receive_kernel import ReceiveIdentity
from backend.hdm.delivery.device_receive_recovery import ReceiveRecovery
from backend.hdm.delivery.device_filter_recovery import FilterRecovery
from backend.hdm.delivery.device_filter_lifecycle import Phase,PairedStage
from backend.hdm.delivery.device_filter_journal import encode_record


def dma_policy(base):
    evidence=DmaReceiveObservation(base.binding,LAYOUT,FOPS,OPS,4,'d'*64,0.)
    code=compile_dma_receive((base.binding.cgroup_inode,),base.evidence.denied_devices,layout=LAYOUT,
        dma_buf_fops=FOPS,amdgpu_dmabuf_ops=OPS,allowed_internal_primary_minor=4)
    return DmaReceiveAttachmentPolicy(base.binding,evidence,hashlib.sha256(code).hexdigest())


class DmaAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.base=char_tests.ReceiveAttachmentTests();self.base.setUp();b=self.base
        b.policy=dma_policy(b)
        b.controller.observe_dma=Mock(return_value=b.policy.evidence)
        b.receive.link_identity.return_value=ReceiveIdentity(3,4,1,6)
        b.receive_readback.link_identity.return_value=ReceiveIdentity(3,4,1,6)

    def test_closed_dma_compiler_and_actual_recovery(self):
        b=self.base;result=b.attach()
        self.assertFalse(result.launch_authorized);self.assertFalse(result.disconnect_clearance)
        b.retained.release_entry.return_value=True;b.receive.probe_program_present.return_value=False
        recovery=ReceiveRecovery(map_factory=lambda:b.retained,receive_factory=lambda:b.receive,
            directory_factory=lambda:b.pins,unlink=Mock())
        recovered=FilterRecovery(b.journal,receive_recovery=recovery).recover('attach',b.binding.unit,current_boot_hash=b.binding.boot_hash)
        self.assertEqual(recovered.outcome,'cancelled_without_owned_identity')
        self.assertEqual(b.record.paired.stage,PairedStage.COMPLETE)

    def test_symbols_addresses_never_appear_in_repr_or_journal(self):
        b=self.base;b.attach()
        text=repr(b.policy)+repr(b.policy.evidence)+repr(b.record)+encode_record(b.record).decode()
        for value in (FOPS,OPS):
            self.assertNotIn(str(value),text);self.assertNotIn(hex(value),text)
        self.assertNotIn('dma_buf_fops',encode_record(b.record).decode())

    def test_mismatched_symbol_minor_layout_binding_and_stale_source_fail_before_mutation(self):
        for change in (dict(dma_buf_fops=FOPS+8),dict(internal_primary_minor=5),
            dict(layout=replace(LAYOUT,dma_btf_id=9)),dict(binding=replace(self.base.binding,topology_hash='e'*64)),
            dict(observed_at=2.)):
            with self.subTest(change=tuple(change)):
                self.setUp();b=self.base
                b.controller.observe_dma.return_value=replace(b.policy.evidence,**change)
                with self.assertRaises(ValueError):b.attach()
                b.maps.assert_not_called();b.receives.assert_not_called()
        self.setUp();self.base.controller.clock=lambda:3
        with self.assertRaises(ValueError):self.base.attach()
        self.base.maps.assert_not_called()

    def test_digest_or_missing_source_fail_before_mutation(self):
        b=self.base;b.policy=replace(b.policy,program_sha256='e'*64)
        with self.assertRaises(ValueError):b.attach()
        b.maps.assert_not_called()
        self.setUp();self.base.controller.observe_dma=None
        with self.assertRaises(ValueError):self.base.attach()
        self.base.maps.assert_not_called()

    def test_changed_dma_source_after_map_pin_prevents_receive_load(self):
        b=self.base
        def change(*args):b.controller.observe_dma.return_value=replace(b.policy.evidence,internal_primary_minor=5)
        b.map_readback.recover.side_effect=change
        with self.assertRaises(ValueError):b.attach()
        b.receive.load_attach.assert_not_called()
        self.assertEqual(b.record.lifecycle.phase,Phase.CANCELLED)

    def test_invalid_minor_and_boolean_time_are_rejected(self):
        evidence=self.base.policy.evidence
        for fields in (dict(internal_primary_minor=True),dict(observed_at=True),dict(dma_buf_fops=0)):
            with self.subTest(fields=tuple(fields)):
                with self.assertRaises(ValueError):replace(evidence,**fields)

    def test_preparation_accepts_dma_and_rechecks_through_direct_stage(self):
        p=preparation_tests.FilterPreparationTests();p.setUp();b=p.base
        b.policy=dma_policy(b)
        b.receive.link_identity.return_value=ReceiveIdentity(3,4,1,6)
        b.receive_readback.link_identity.return_value=ReceiveIdentity(3,4,1,6)
        source=Mock(return_value=b.policy.evidence);p.controller.observe_dma=source
        result=p.prepare()
        self.assertTrue(result.prepared);self.assertFalse(result.launch_authorized)
        self.assertGreater(source.call_count,5)

    def test_dma_changes_during_direct_stage_cancel_and_preserve_owners(self):
        for when in ('direct_start','after_direct'):
            with self.subTest(when=when):
                p=preparation_tests.FilterPreparationTests();p.setUp();b=p.base
                b.policy=dma_policy(b)
                b.receive.link_identity.return_value=ReceiveIdentity(3,4,1,6)
                b.receive_readback.link_identity.return_value=ReceiveIdentity(3,4,1,6)
                source=Mock(return_value=b.policy.evidence)
                p.controller.observe_dma=source
                original=p.direct_factory.side_effect
                def factory(*args,**kwargs):
                    controller=original(*args,**kwargs)
                    if when=='direct_start':
                        source.return_value=replace(b.policy.evidence,internal_primary_minor=5)
                    else:
                        attach=controller.attach
                        def changed_after_attach(*args,**kwargs):
                            result=attach(*args,**kwargs)
                            source.return_value=replace(b.policy.evidence,dma_buf_fops=FOPS+8)
                            return result
                        controller.attach=changed_after_attach
                    return controller
                p.direct_factory.side_effect=factory
                with self.assertRaises(ValueError):p.prepare()
                self.assertEqual(b.record.lifecycle.phase,Phase.CANCELLED)
                self.assertEqual(b.record.paired.stage,PairedStage.RECEIVE_CONFIRMED)
                self.assertEqual(b.record.paired.receive.program_id,4)
                if when=='direct_start':
                    self.assertIsNone(b.record.lifecycle.owned)
                    p.direct.load.assert_not_called()
                else:
                    self.assertEqual(b.record.lifecycle.owned.program_id,42)


if __name__=='__main__':unittest.main()
