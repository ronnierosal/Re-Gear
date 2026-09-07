from dataclasses import replace
import unittest
from unittest.mock import Mock
from tests import test_device_filter_preparation as preparation_tests
from tests import test_device_receive_dma_attachment as dma_tests
from backend.hdm.delivery.device_filter_observation_bundle import PrepareObservationBundle
from backend.hdm.delivery.device_receive_kernel import ReceiveIdentity
from backend.hdm.delivery.device_filter_lifecycle import Phase,PairedStage


class ObservationBundleTests(unittest.TestCase):
    def setUp(self):
        self.p=preparation_tests.FilterPreparationTests();self.p.setUp();b=self.p.base
        b.policy=dma_tests.dma_policy(b)
        b.receive.link_identity.return_value=ReceiveIdentity(3,4,1,6)
        b.receive_readback.link_identity.return_value=ReceiveIdentity(3,4,1,6)
        self.collected=[]
        def collect():
            value=PrepareObservationBundle(b.evidence,b.policy.evidence)
            self.collected.append(value)
            return value
        self.source=Mock(side_effect=collect)
        self.p.controller.observe_bundle=self.source
        self.p.controller.observe=Mock(side_effect=AssertionError('split launch must not run'))
        self.p.controller.observe_dma=Mock(side_effect=AssertionError('split DMA must not run'))

    def test_one_collection_per_step_without_split_recursion(self):
        result=self.p.prepare()
        self.assertTrue(result.prepared)
        # Initial preparation + 7 receive checks + pre-direct + 4 direct + final.
        self.assertEqual(self.source.call_count,14)
        self.assertEqual(len({id(value) for value in self.collected}),14)
        self.assertTrue(all(value.dma.observed_at==0 for value in self.collected))
        self.p.controller.observe.assert_not_called();self.p.controller.observe_dma.assert_not_called()

    def test_changed_fresh_collection_after_pair_cancels_before_direct(self):
        original=self.p.pair_factory.side_effect
        def factory(*args,**kwargs):
            controller=original(*args,**kwargs);attach=controller.attach
            def changed(*args,**kwargs):
                result=attach(*args,**kwargs)
                b=self.p.base
                self.source.side_effect=lambda:PrepareObservationBundle(b.evidence,replace(b.policy.evidence,internal_primary_minor=5))
                return result
            controller.attach=changed;return controller
        self.p.pair_factory.side_effect=factory
        with self.assertRaises(ValueError):self.p.prepare()
        self.p.direct_factory.assert_not_called()
        self.assertEqual(self.p.base.record.lifecycle.phase,Phase.CANCELLED)
        self.assertEqual(self.p.base.record.paired.stage,PairedStage.RECEIVE_CONFIRMED)

    def test_stale_bundle_does_not_retimestamp_or_mutate(self):
        self.p.controller.clock=lambda:3
        with self.assertRaises(ValueError):self.p.prepare()
        self.p.base.maps.assert_not_called()
        self.assertEqual(self.collected[0].dma.observed_at,0)

    def test_bundle_requires_exact_shared_binding(self):
        b=self.p.base
        with self.assertRaises(ValueError):PrepareObservationBundle(b.evidence,
            replace(b.policy.evidence,binding=replace(b.binding,topology_hash='e'*64)))
        with self.assertRaises(ValueError):PrepareObservationBundle(b.evidence,object())


if __name__=='__main__':unittest.main()
