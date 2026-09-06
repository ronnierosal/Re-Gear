import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_portable_trial_store as store_fixtures
from hdm.delivery.steam_trial_wait import wait_for_steam_trial
from hdm.adapters.presentation_transition import PresentationTransitionMechanism
from hdm.application.transition_orchestrator import RuntimeTransitionResult
from hdm.domain.control_plane import TransitionOutcomeKind


class SteamWaitTests(unittest.TestCase):
    def setUp(self):
        self.fixture = store_fixtures.TrialStoreTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store
        self.now = 50000.0
        self.fixture.values['expires_at'] = self.now + 120.0
        self.store.arm(**self.fixture.values)
        self.operation = self.fixture.values['operation_id']
        self.sleeps = []

    def receipt(self):
        self.store.consume()
        self.store.publish_gamescope_launch(self.operation, 'a' * 32)

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def run_wait(self, **kwargs):
        wait_for_steam_trial(self.store, self.operation, clock=lambda: self.now,
                            wait=kwargs.get('wait', self.sleep))

    def test_absent_receipt_does_not_wait(self):
        self.run_wait()
        self.assertEqual(self.sleeps, [])

    def test_timeout_is_bounded_and_does_not_claim(self):
        self.receipt()
        self.run_wait()
        self.assertLessEqual(len(self.sleeps), 100)
        self.assertLessEqual(sum(self.sleeps), 10)
        self.assertGreater(sum(self.sleeps), 9.9)
        self.assertFalse(self.store._steam_consumed.exists())

    def test_expiry_bounds_wait(self):
        self.receipt()
        self.now = self.fixture.values['expires_at'] - .05
        self.run_wait()
        self.assertAlmostEqual(sum(self.sleeps), .05)

    def test_claim_ends_wait_without_success_claim(self):
        self.receipt()
        def claim(seconds):
            self.sleep(seconds)
            self.store.consume_steam()
        self.run_wait(wait=claim)
        self.assertEqual(len(self.sleeps), 1)

    def test_exclusive_marker_creation_before_write_is_pending(self):
        self.receipt()
        descriptor = os.open(self.store._steam_consumed,
                             os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self.addCleanup(os.close, descriptor)
        def finish_write(seconds):
            self.sleep(seconds)
            os.write(descriptor, self.operation.encode('ascii'))
            os.fsync(descriptor)
        self.run_wait(wait=finish_write)
        self.assertEqual(len(self.sleeps), 1)
        self.assertEqual(self.store._read_small_file(self.store._steam_consumed), self.operation)

    def test_empty_marker_from_interrupted_writer_remains_bounded(self):
        self.receipt()
        descriptor = os.open(self.store._steam_consumed,
                             os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        self.run_wait()
        self.assertLessEqual(len(self.sleeps), 100)
        self.assertGreater(sum(self.sleeps), 9.9)
        self.assertEqual(self.store._read_small_file(self.store._steam_consumed), '')

    def test_wrong_claim_fails(self):
        self.receipt()
        self.store._steam_consumed.write_text('other')
        with self.assertRaises(ValueError):
            self.run_wait()

    def test_frozen_clock_still_bounded(self):
        self.receipt()
        self.run_wait(wait=self.sleeps.append)
        self.assertEqual(len(self.sleeps), 100)

    def test_backward_clock_still_bounded(self):
        self.receipt()
        def backward(seconds):
            self.sleeps.append(seconds)
            self.now -= 1.0
        self.run_wait(wait=backward)
        self.assertEqual(len(self.sleeps), 100)
        self.assertLessEqual(sum(self.sleeps), 10)

    def test_monotonic_expiry_does_not_consult_calendar_time(self):
        self.receipt()
        with patch('time.time', side_effect=AssertionError('calendar clock consulted')):
            self.run_wait()
        self.assertGreater(len(self.sleeps), 0)

    def test_receipt_identity_mismatch_does_not_wait(self):
        self.receipt()
        self.store._receipt.write_text('other\n' + 'a' * 32)
        self.run_wait()
        self.assertEqual(self.sleeps, [])


class MechanismWaitTests(unittest.TestCase):
    def mechanism(self, waiter):
        store = Mock()
        store.read.return_value = {'operation_id': 'op'}
        mechanism = PresentationTransitionMechanism(integration=None, config=None,
            commands=None, resolve_user=lambda: None, read_boot_id=lambda: '',
            trial_store=store, trial_steam_waiter=waiter)
        return mechanism, store

    def test_only_durable_success_waits_then_cancels(self):
        for durable, kind in ((True, TransitionOutcomeKind.SUCCEEDED),
                              (False, TransitionOutcomeKind.SUCCEEDED),
                              (True, TransitionOutcomeKind.FAILED)):
            with self.subTest(durable=durable, kind=kind):
                calls = []
                mechanism, store = self.mechanism(lambda op: calls.append('wait'))
                store.cancel.side_effect = lambda op: calls.append('cancel')
                result = RuntimeTransitionResult(None, SimpleNamespace(kind=kind), durable)
                engine = SimpleNamespace(run=lambda *args, **kwargs: result)
                self.assertIs(mechanism.run_portable_trial(SimpleNamespace(plan_id='op'), engine), result)
                self.assertEqual(calls, ['wait', 'cancel'] if durable and kind is TransitionOutcomeKind.SUCCEEDED else ['cancel'])

    def test_engine_and_waiter_exceptions_cancel_and_clear_context(self):
        for source in ('engine', 'waiter'):
            def fail(*args, **kwargs):
                raise RuntimeError('failure')
            mechanism, store = self.mechanism(fail)
            result = RuntimeTransitionResult(None, SimpleNamespace(kind=TransitionOutcomeKind.SUCCEEDED), True)
            engine = SimpleNamespace(run=fail if source == 'engine' else lambda *a, **k: result)
            with self.assertRaises(RuntimeError):
                mechanism.run_portable_trial(SimpleNamespace(plan_id='op'), engine)
            store.cancel.assert_called_once_with('op')
            self.assertIsNone(mechanism._trial_plan)

