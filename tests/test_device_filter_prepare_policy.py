from dataclasses import replace
import hashlib
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from backend.hdm.delivery.device_filter_prepare_policy import build_prepare_policy
from backend.hdm.delivery.device_filter_arm import FilterArm
from backend.hdm.delivery.device_filter_peer import WaitingPeerIdentity
from backend.hdm.delivery.device_filter_lifecycle import LaunchBinding
from backend.hdm.delivery.device_filter_prepare_server import FilterPrepareEvidence, IsolationCoverage
from backend.hdm.delivery.device_filter_prepared_source import PreparedLaunchCollection
from backend.hdm.delivery.device_filter_session_prepare import SessionEntryPreparedCollection
from backend.hdm.delivery.device_receive_attachment import DmaReceiveObservation
from backend.hdm.delivery.dma_receive_program import compile_dma_receive
from tests.test_dma_receive_program import LAYOUT, FOPS, OPS


class PreparePolicyTests(unittest.TestCase):
    def setUp(self):
        self.arm = FilterArm(1, 'op', 'gamescope-session.service', 1000,
                             'a'*64, 'b'*64, 'c'*64, 'd'*32, 15)
        self.identity = WaitingPeerIdentity(50, 1000, 60, 'e'*32, self.arm.unit, '/fixture', 70, 80)
        self.binding = LaunchBinding('a'*64, 'op', self.arm.unit, 'e'*32, 1000, 50, 60, 70, 80, 'b'*64, 14)
        self.dma = DmaReceiveObservation(self.binding, LAYOUT, FOPS, OPS, 4, '2'*64, 10)
        self.nodes = ((226, 128),)
        self.runtime = SimpleNamespace(digest='1'*64)
        self.evidence = FilterPrepareEvidence('a'*64, 'b'*64, 'c'*64, '1'*64, self.nodes,
            True, True, True, True, IsolationCoverage.UNKNOWN, IsolationCoverage.UNKNOWN)
        self.collection = SessionEntryPreparedCollection(self.evidence, self.dma)
        self.held = Mock()
        self.held.revalidate.return_value = self.identity

    def build(self, **kwargs):
        values = dict(expected_arm=self.arm, runtime=self.runtime, deadline=14,
                      expected_denied_devices=self.nodes, clock=lambda: 10)
        values.update(kwargs)
        return build_prepare_policy(self.held, self.collection, **values)

    def test_exact_compiler_policy_and_unchanged_dma_timestamp(self):
        policy = self.build()
        code = compile_dma_receive((80,), self.nodes, layout=LAYOUT, dma_buf_fops=FOPS,
            amdgpu_dmabuf_ops=OPS, allowed_internal_primary_minor=4)
        self.assertEqual(policy.program_sha256, hashlib.sha256(code).hexdigest())
        self.assertIs(policy.evidence, self.dma)
        self.assertEqual(policy.binding, self.binding)
        self.assertEqual(self.held.revalidate.call_count, 2)

    def test_changed_held_peer_rejected(self):
        self.held.revalidate.side_effect = [self.identity, replace(self.identity, starttime=61)]
        with self.assertRaises(ValueError): self.build()

    def test_dma_identity_mismatch_rejected(self):
        self.collection = replace(self.collection, dma=replace(self.dma,
            binding=replace(self.binding, pid=51)))
        with self.assertRaises(ValueError): self.build()

    def test_independent_identity_and_node_mismatch_rejected(self):
        for field, value in (('boot_hash', 'f'*64), ('topology_hash', 'f'*64),
                             ('config_hash', 'f'*64), ('runtime_digest', 'f'*64),
                             ('denied_devices', ((226,129),)), ('no_game', False),
                             ('inherited_descriptors_free', False)):
            self.collection = SessionEntryPreparedCollection(replace(self.evidence, **{field:value}), self.dma)
            with self.subTest(field=field), self.assertRaises(ValueError): self.build()

    def test_stale_dma_and_clock_regression_rejected(self):
        for ticks in ((13, 13), (10, 9), (10, 14)):
            values = iter(ticks)
            with self.subTest(ticks=ticks), self.assertRaises(ValueError):
                self.build(clock=lambda: next(values))

    def test_wrong_collection_role_rejected(self):
        self.collection = PreparedLaunchCollection(self.evidence, self.dma)
        with self.assertRaises(ValueError): self.build()

    def test_steam_collection_supported_with_matching_role(self):
        self.arm = replace(self.arm, unit='steam-launcher.service')
        self.identity = replace(self.identity, unit=self.arm.unit)
        self.held.revalidate.return_value = self.identity
        self.binding = replace(self.binding, unit=self.arm.unit)
        self.dma = replace(self.dma, binding=self.binding)
        self.collection = PreparedLaunchCollection(self.evidence, self.dma)
        self.assertEqual(self.build().binding, self.binding)

    def test_deadline_must_match_collection_and_arm(self):
        for deadline in (10, 13, 16, float('nan')):
            with self.subTest(deadline=deadline), self.assertRaises(ValueError):
                self.build(deadline=deadline)
