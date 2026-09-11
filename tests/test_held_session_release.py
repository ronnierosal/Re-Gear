import unittest
import sys
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from regear.application.filter_arm import HolderObservation
from regear.application.held_session_release import (
    HeldSessionPreflight, HeldSessionRelease, HELD_UNITS, STOP_UNITS)


class HeldSessionTests(unittest.TestCase):
    def fixture(self, **overrides):
        events = []
        snapshot = HeldSessionPreflight('exact', HELD_UNITS, True, True, True, True)
        def callback(name, result=True):
            def call(*args):
                events.append((name, args))
                return result
            return Mock(side_effect=call)
        ports = {name: callback(name) for name in ('ownership_held', 'persist_intent',
            'prepare_restore', 'mask', 'masks_verified', 'stop', 'stopped_verified',
            'wait', 'restore', 'retire')}
        ports['preflight'] = callback('preflight', snapshot)
        ports['observe'] = callback('observe', HolderObservation((), True))
        ports.update(overrides)
        return HeldSessionRelease(**ports), ports, events

    def test_order_fixed_units_and_verified_restore(self):
        run, ports, events = self.fixture()
        result = run.run()
        self.assertTrue(result.ok)
        self.assertFalse(result.safe_to_unplug)
        names = [name for name, _ in events]
        self.assertLess(names.index('persist_intent'), names.index('prepare_restore'))
        self.assertLess(names.index('prepare_restore'), names.index('mask'))
        self.assertLess(names.index('masks_verified'), names.index('stop'))
        self.assertLess(names.index('observe'), names.index('restore'))
        self.assertLess(names.index('restore'), names.index('retire'))
        self.assertEqual([c.args[0] for c in ports['mask'].call_args_list], list(HELD_UNITS))
        self.assertEqual([c.args[0] for c in ports['stop'].call_args_list], list(STOP_UNITS))

    def test_unknown_preflight_and_arbitrary_unit_refused(self):
        for snapshot in (None, HeldSessionPreflight('exact', ('arbitrary.service',), True, True, True, True),
                         HeldSessionPreflight('exact', (), None, True, True, True)):
            run, ports, _ = self.fixture(preflight=lambda: snapshot)
            self.assertFalse(run.run().ok)
            ports['persist_intent'].assert_not_called()
            ports['mask'].assert_not_called()

    def test_watchdog_refusal_never_masks_and_restores_intent(self):
        run, ports, _ = self.fixture(prepare_restore=lambda *_: False)
        result = run.run()
        ports['mask'].assert_not_called()
        ports['restore'].assert_called_once()
        self.assertTrue(result.journal_retained)

    def test_partial_mask_exception_restores_and_retains_record(self):
        run, ports, _ = self.fixture(mask=Mock(side_effect=[True, OSError('partial')]))
        result = run.run()
        ports['stop'].assert_not_called()
        ports['restore'].assert_called_once()
        self.assertTrue(result.restored)
        self.assertTrue(result.journal_retained)

    def test_mask_verification_failure_never_stops(self):
        run, ports, _ = self.fixture(masks_verified=lambda *_: False)
        self.assertFalse(run.run().ok)
        ports['stop'].assert_not_called()
        ports['restore'].assert_called_once()

    def test_incomplete_empty_scan_is_bounded_and_not_clear(self):
        run, ports, _ = self.fixture(observe=Mock(return_value=HolderObservation((), False)))
        result = run.run()
        self.assertFalse(result.clear_observed)
        self.assertTrue(result.restored)
        self.assertEqual(ports['observe'].call_count, 6)
        self.assertEqual(ports['wait'].call_count, 5)

    def test_clear_observation_does_not_hide_restore_failure(self):
        run, ports, _ = self.fixture(restore=lambda *_: False)
        result = run.run()
        self.assertTrue(result.clear_observed)
        self.assertFalse(result.restored)
        self.assertTrue(result.journal_retained)
        ports['retire'].assert_not_called()

    def test_observe_exception_restores(self):
        run, ports, _ = self.fixture(observe=Mock(side_effect=OSError('scan failed')))
        result = run.run()
        ports['restore'].assert_called_once()
        self.assertTrue(result.journal_retained)

    def test_lost_ownership_before_mask_refuses_and_restores(self):
        run, ports, _ = self.fixture(ownership_held=Mock(side_effect=[True, True, False]))
        result = run.run()
        ports['mask'].assert_not_called()
        ports['restore'].assert_called_once()
        self.assertTrue(result.journal_retained)

    def test_single_use(self):
        run, ports, _ = self.fixture()
        run.run()
        self.assertEqual(run.run().code, 'held_release.already_attempted')
        ports['restore'].assert_called_once()

    def test_retirement_failure_preserves_verified_restore_fact(self):
        run, _, _ = self.fixture(retire=Mock(side_effect=OSError('journal')))
        result = run.run()
        self.assertTrue(result.clear_observed)
        self.assertTrue(result.restored)
        self.assertTrue(result.journal_retained)
        self.assertFalse(result.ok)

    def test_every_operating_stage_exception_restores_and_retains(self):
        for stage in ('persist_intent', 'prepare_restore', 'mask', 'masks_verified',
                      'stop', 'stopped_verified', 'observe', 'wait'):
            with self.subTest(stage=stage):
                overrides = {stage: Mock(side_effect=OSError('failed'))}
                if stage == 'wait':
                    overrides['observe'] = Mock(return_value=HolderObservation(('holder',), True))
                run, ports, _ = self.fixture(**overrides)
                result = run.run()
                ports['restore'].assert_called_once()
                ports['retire'].assert_not_called()
                self.assertTrue(result.restored)
                self.assertTrue(result.journal_retained)
                self.assertFalse(result.ok)

    def test_intent_false_still_restores_possible_partial_record(self):
        run, ports, _ = self.fixture(persist_intent=Mock(return_value=False))
        result = run.run()
        ports['prepare_restore'].assert_not_called()
        ports['mask'].assert_not_called()
        ports['restore'].assert_called_once()
        self.assertTrue(result.journal_retained)

    def test_failure_before_intent_never_restores_or_retires(self):
        for stage in ('preflight', 'ownership_held'):
            with self.subTest(stage=stage):
                run, ports, _ = self.fixture(**{stage: Mock(side_effect=OSError('failed'))})
                self.assertFalse(run.run().ok)
                ports['persist_intent'].assert_not_called()
                ports['restore'].assert_not_called()
                ports['retire'].assert_not_called()

    def test_restore_exception_retains_record_and_clear_observation(self):
        run, ports, _ = self.fixture(restore=Mock(side_effect=OSError('restore')))
        result = run.run()
        self.assertTrue(result.clear_observed)
        self.assertFalse(result.restored)
        self.assertTrue(result.journal_retained)
        ports['retire'].assert_not_called()

    def test_incomplete_then_complete_scan_requires_fresh_held_verification(self):
        run, ports, _ = self.fixture(observe=Mock(side_effect=[
            HolderObservation((), False), HolderObservation((), True)]))
        self.assertTrue(run.run().ok)
        self.assertEqual(ports['observe'].call_count, 2)
        self.assertEqual(ports['wait'].call_count, 1)
        self.assertEqual(ports['stopped_verified'].call_count, 3)

    def test_mask_lost_during_clear_scan_is_not_accepted(self):
        run, ports, _ = self.fixture(masks_verified=Mock(side_effect=[True, True, False]))
        result = run.run()
        self.assertFalse(result.clear_observed)
        self.assertTrue(result.restored)
        self.assertTrue(result.journal_retained)

    def test_invalid_scan_values_never_count_as_clear(self):
        for observation in (None, HolderObservation((), 1), HolderObservation([], True),
                            HolderObservation(('',), True)):
            with self.subTest(observation=observation):
                run, ports, _ = self.fixture(observe=Mock(return_value=observation))
                result = run.run()
                self.assertFalse(result.clear_observed)
                self.assertTrue(result.journal_retained)
                ports['restore'].assert_called_once()

    def test_interrupt_restores_but_never_retires(self):
        run, ports, _ = self.fixture(observe=Mock(side_effect=KeyboardInterrupt()))
        with self.assertRaises(KeyboardInterrupt):
            run.run()
        ports['restore'].assert_called_once()
        ports['retire'].assert_not_called()


if __name__ == '__main__':
    unittest.main()
