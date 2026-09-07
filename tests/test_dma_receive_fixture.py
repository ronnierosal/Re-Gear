from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts import probe_dma_receive_fixture as fixture


class DmaFixtureSequenceTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.identity = SimpleNamespace(internal='internal', external='external')
        self.owner = Mock()
        self.owner.load_attach.side_effect = lambda *a, **k: self.events.append('attach')
        self.owner.close.side_effect = lambda: self.events.append('detach')
        self.observe = Mock(return_value=self.identity)
        self.membership = Mock()
        self.result_override = {}

    def allocate(self, target):
        self.events.append('allocate_' + target)
        return SimpleNamespace(export_fd=10 if target == 'internal' else 20)

    def deliver(self, fd, sequence):
        self.events.append(sequence)
        if sequence in self.result_override:
            return self.result_override[sequence]
        return dict(sequence=sequence, received=0 if sequence == 3 else 1,
                    truncated=sequence == 3, identity=None if sequence == 3 else [1, fd])

    def run_case(self, **options):
        args = dict(observe=self.observe, allocate=self.allocate, owner=self.owner,
                    compile_program=lambda: (b'program', 12), membership=self.membership,
                    deliver=self.deliver, outside=self.deliver, identify=lambda fd: (1, fd),
                    clock=lambda: 10)
        args.update(options)
        return fixture.exercise(self.identity, **args)

    def test_complete_order_and_claim_limits(self):
        result = self.run_case()
        self.assertEqual(self.events, ['allocate_internal','allocate_external',1,2,'attach',3,4,16,'detach',5])
        self.assertEqual(result['state'], 'fixture_passed')
        for field in ('disconnect_clearance','resources_released','importer_isolation_verified',
                      'inherited_player_resources_verified','player_mutation'):
            self.assertFalse(result[field])

    def test_stale_identity_stops_before_allocation_or_attachment(self):
        for call in range(1, 5):
            self.setUp()
            self.observe.side_effect = [self.identity] * (call - 1) + [None]
            with self.assertRaises(ValueError): self.run_case()
            self.owner.load_attach.assert_not_called()
            if call == 1: self.assertEqual(self.events, [])

    def test_post_restore_identity_change_cannot_pass(self):
        self.observe.side_effect = [self.identity] * 4 + [None]
        with self.assertRaises(ValueError): self.run_case()
        self.owner.close.assert_called_once()

    def test_each_delivery_mismatch_blocks_success(self):
        for sequence in (1,2,3,4,5,16):
            self.setUp()
            self.result_override[sequence] = dict(sequence=sequence,received=0,truncated=False,identity=None)
            with self.assertRaises(ValueError): self.run_case()
            if sequence < 3: self.owner.load_attach.assert_not_called()

    def test_same_buffer_identities_and_membership_failure_block_attach(self):
        with self.assertRaises(ValueError): self.run_case(identify=lambda fd: (1, 1))
        self.owner.load_attach.assert_not_called()
        self.setUp()
        self.membership.side_effect = ValueError('changed')
        with self.assertRaises(ValueError): self.run_case()
        self.assertEqual(self.events, [])

    def test_deadline_expiry_stops_before_mutation(self):
        with self.assertRaises(ValueError): self.run_case(clock=Mock(side_effect=[1,32]))
        self.assertEqual(self.events, [])

    def test_compile_expiry_or_identity_change_blocks_attachment(self):
        now = [10.0]
        def compile_late():
            now[0] = 41.0
            return b'program', 12
        with self.assertRaises(ValueError):
            self.run_case(clock=lambda: now[0], compile_program=compile_late)
        self.owner.load_attach.assert_not_called()
        self.setUp()
        def compile_changed():
            self.observe.return_value = None
            return b'program', 12
        with self.assertRaises(ValueError): self.run_case(compile_program=compile_changed)
        self.owner.load_attach.assert_not_called()

    def test_invalid_or_reversing_clock_blocks_mutation(self):
        for values in ([float('nan'), 10], [10,float('inf')], [10,9]):
            with self.assertRaises(ValueError): self.run_case(clock=Mock(side_effect=values))
        self.assertEqual(self.events, [])

    def test_cleanup_attempts_every_buffer_after_link_failure(self):
        resources = fixture._OwnedResources()
        resources.link = Mock()
        resources.link.close.side_effect = OSError('private')
        one, two = Mock(), Mock()
        two.close.side_effect = OSError('private')
        resources.buffers = [one, two]
        with self.assertRaises(RuntimeError): resources.close()
        one.close.assert_called_once()
        two.close.assert_called_once()

    def test_explicit_cli_and_sanitized_failure(self):
        with patch.object(fixture.sys, 'argv', ['probe']), patch.object(fixture, 'run_fixture') as run:
            with self.assertRaises(SystemExit): fixture.main()
            run.assert_not_called()
        with patch.object(fixture.sys, 'argv', ['probe','--supervised-dma-fixture']), \
                patch.object(fixture.platform, 'system', return_value='Windows'), \
                patch.object(fixture, 'run_fixture', side_effect=RuntimeError('PRIVATE')), \
                patch('builtins.print') as output:
            self.assertEqual(fixture.main(), 1)
            self.assertNotIn('PRIVATE', output.call_args.args[0])


if __name__ == '__main__': unittest.main()
