"""Simulated operation-aware ports; these are not production sleep adapters."""
import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from regear.delivery.dock_power_service import DockPowerRequest, create_power_request
from regear.delivery.dock_sleep_handoff import HandoffCapabilities, SleepLeaseHandoff


class Lease:
    def __init__(self, name, events):
        self.name, self.events = name, events
        self.owner, self.held = None, True
        self.fail, self.hook = '', lambda: None

    def event(self, action, request):
        self.events.append((self.name, action, request))
        if self.fail == action:
            raise OSError('injected ' + action)

    def prepare(self, request):
        self.owner = request
        self.event('prepare', request)
        return True

    def owned(self, request):
        return self.owner is request

    def active(self):
        return self.held

    def release(self, request):
        self.held = False  # failures may happen after the side effect
        self.event('release', request)
        self.hook()
        return True

    def reacquire(self, request):
        self.event('reacquire', request)
        self.held = True
        return True

    def finish(self, request):
        self.event('finish', request)
        self.owner = None
        return True


class SleepLeaseHandoffTests(unittest.TestCase):
    def setUp(self):
        self.request = DockPowerRequest('a' * 32, 'sleep', 'boot:process', 10, 20)
        self.events = []
        self.background = Lease('background', self.events)
        self.transaction = Lease('transaction', self.events)
        self.now, self.cancelled, self.consumed = 11, False, True
        self.session, self.claim = self.request.session, True
        self.capability = HandoffCapabilities(True, True, True, True)
        self.outcome = True

    def submit_platform(self, request):
        self.assertIs(request, self.request)
        self.assertFalse(self.background.held)
        self.assertFalse(self.transaction.held)
        self.events.append(('platform', 'submit', request))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    def handoff(self, **overrides):
        args = dict(background=self.background, transaction=self.transaction,
                    verify_original=lambda request: request is self.request and self.claim,
                    intent_consumed=lambda request: request is self.request and self.consumed,
                    request_sleep=self.submit_platform, session=lambda: self.session,
                    cancelled=lambda: self.cancelled, monotonic=lambda: self.now,
                    capabilities=lambda: self.capability)
        args.update(overrides)
        return SleepLeaseHandoff(self.request, **args)

    def test_default_capabilities_cannot_release_or_submit(self):
        handoff = self.handoff(capabilities=HandoffCapabilities)
        self.assertFalse(handoff.submit('sleep'))
        self.assertEqual(self.events, [])

    def test_every_unknown_capability_refuses_including_crash_continuity(self):
        for field in ('profile', 'wake_without_reauthorization', 'thermal', 'crash_continuity'):
            for missing in (False, None, 1, 'verified'):
                with self.subTest(field=field, missing=missing):
                    self.capability = replace(HandoffCapabilities(True, True, True, True),
                                              **{field: missing})
                    self.assertFalse(self.handoff().submit('sleep'))
                    self.assertEqual(self.events, [])

    def test_stale_cancelled_unconsumed_and_wrong_session_refuse_before_prepare(self):
        for field, bad in (('now', 20), ('now', float('nan')), ('cancelled', True),
                           ('consumed', False), ('session', 'another-boot'), ('claim', False)):
            with self.subTest(field=field, bad=bad):
                old = getattr(self, field)
                setattr(self, field, bad)
                self.assertFalse(self.handoff().submit('sleep'))
                self.assertEqual(self.events, [])
                setattr(self, field, old)

    def test_exact_request_both_releases_then_one_submission(self):
        handoff = self.handoff()
        self.assertFalse(handoff.submit('shutdown'))
        self.assertEqual(self.events, [])
        handoff = self.handoff()
        self.assertTrue(handoff.submit('sleep'))
        self.assertFalse(handoff.submit('sleep'))
        self.assertEqual([(n, action) for n, action, _ in self.events], [
            ('background', 'prepare'), ('transaction', 'prepare'),
            ('background', 'release'), ('transaction', 'release'), ('platform', 'submit')])
        self.assertTrue(all(request is self.request for _, _, request in self.events))
        self.assertEqual(handoff.status.submission, 'accepted')
        self.assertFalse(handoff.status.protection_verified)

    def test_refused_and_ambiguous_submission_restore_both_without_replay(self):
        for outcome, status in ((False, 'refused'), (TimeoutError(), 'unknown')):
            with self.subTest(status=status):
                self.setUp()
                self.outcome = outcome
                handoff = self.handoff()
                self.assertFalse(handoff.submit('sleep'))
                self.assertTrue(handoff.status.protection_verified)
                self.assertEqual(handoff.status.submission, status)
                self.assertTrue(self.background.held and self.transaction.held)
                self.assertFalse(handoff.submit('sleep'))
                self.assertEqual(sum(name == 'platform' for name, _, _ in self.events), 1)
                actions = [(name, action) for name, action, _ in self.events]
                self.assertLess(actions.index(('transaction', 'reacquire')),
                                actions.index(('background', 'finish')))

    def test_each_partial_prepare_or_release_failure_restores_owned_leases(self):
        for name in ('background', 'transaction'):
            for stage in ('prepare', 'release'):
                with self.subTest(name=name, stage=stage):
                    self.setUp()
                    getattr(self, name).fail = stage
                    handoff = self.handoff()
                    self.assertFalse(handoff.submit('sleep'))
                    self.assertTrue(handoff.status.protection_verified)
                    self.assertTrue(self.background.held and self.transaction.held)
                    self.assertFalse(any(n == 'platform' for n, _, _ in self.events))

    def test_expiry_or_cancel_between_releases_restores_without_platform_call(self):
        for field, value in (('now', 21), ('cancelled', True), ('claim', False)):
            with self.subTest(field=field):
                self.setUp()
                self.background.hook = lambda: setattr(self, field, value)
                handoff = self.handoff()
                self.assertFalse(handoff.submit('sleep'))
                self.assertTrue(handoff.status.protection_verified)
                self.assertFalse(any(n == 'platform' for n, _, _ in self.events))

    def test_failed_reacquisition_attempts_other_lease_and_keeps_pauses(self):
        self.outcome = False
        self.background.fail = 'reacquire'
        handoff = self.handoff()
        self.assertFalse(handoff.submit('sleep'))
        self.assertFalse(handoff.status.protection_verified)
        self.assertTrue(self.transaction.held)
        self.assertIs(self.transaction.owner, self.request)
        self.assertFalse(any(action == 'finish' for _, action, _ in self.events))

    def test_lost_owner_never_reacquires_someone_elses_lease(self):
        self.background.hook = lambda: setattr(self.transaction, 'owner', object())
        handoff = self.handoff()
        self.assertFalse(handoff.submit('sleep'))
        self.assertFalse(handoff.status.protection_verified)
        self.assertFalse(any(n == 'transaction' and a in ('release', 'reacquire', 'finish')
                             for n, a, _ in self.events))

    def test_wake_restore_is_protection_only_not_a_second_power_request(self):
        handoff = self.handoff()
        self.assertTrue(handoff.submit('sleep'))
        self.now = 100  # recovery must still work after original deadline
        self.assertTrue(handoff.restore())
        self.assertTrue(self.background.held and self.transaction.held)
        self.assertEqual(sum(n == 'platform' for n, _, _ in self.events), 1)

    def test_cross_session_restore_refuses_process_local_handles(self):
        handoff = self.handoff()
        self.assertTrue(handoff.submit('sleep'))
        self.events.clear()
        self.session = 'new-boot'
        self.assertFalse(handoff.restore())
        self.assertEqual(self.events, [])

    def test_shared_lease_and_existing_delivery_sleep_enablement_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'distinct_leases'):
            self.handoff(transaction=self.background)
        with self.assertRaisesRegex(ValueError, 'sleep_unverified'):
            create_power_request('sleep', 'boot:process')

    def test_expiry_during_consumed_intent_readback_refuses_without_releasing(self):
        def consumed(request):
            self.now = 21
            return True
        self.assertFalse(self.handoff(intent_consumed=consumed).submit('sleep'))
        self.assertEqual(self.events, [])

    def test_consumed_intent_readback_exception_never_submits(self):
        def consumed(request):
            raise OSError('durable state unreadable')
        self.assertFalse(self.handoff(intent_consumed=consumed).submit('sleep'))
        self.assertEqual(self.events, [])

    def test_release_ack_without_inactive_readback_restores(self):
        self.background.hook = lambda: setattr(self.background, 'held', True)
        handoff = self.handoff()
        self.assertFalse(handoff.submit('sleep'))
        self.assertTrue(handoff.status.protection_verified)
        self.assertFalse(any(n == 'platform' for n, _, _ in self.events))
