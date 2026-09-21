"""Observed sleep lifecycle with actual guards/handoff and no OS calls."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

from tests.test_dock_sleep_lease import Process
from regear.adapters.steamos.sleep_inhibitor import Login1SleepInhibitor, SleepGuardController
from regear.delivery.dock_power_service import create_power_request
from regear.delivery.dock_sleep_service import run_observed_sleep


class ObservedSleepTests(unittest.TestCase):
    def setUp(self):
        self.request = create_power_request('sleep', 'session', monotonic=lambda: 10)
        self.guards = [SleepGuardController(Login1SleepInhibitor(Process)) for _ in range(2)]
        self.events = []
        self.consumed = False
        self.state = 'success'
        self.baseline = object()
        self.observer = NS(read=lambda: self.baseline, classify=self.classify)

    def classify(self, baseline):
        self.assertIs(baseline, self.baseline)
        self.events.append('observe')
        return self.state

    def consume(self, request):
        self.assertIs(request, self.request)
        self.events.append('consume')
        if self.consumed:
            return False
        self.consumed = True
        return True

    def submit(self, request):
        self.assertTrue(self.consumed)
        self.assertFalse(any(g.status().active for g in self.guards))
        self.events.append('submit')
        return True

    def run_sleep(self, **changes):
        args = dict(background=self.guards[0], transaction=self.guards[1],
            verify=lambda r: r is self.request, consume=self.consume, submit=self.submit,
            observer=self.observer, session=lambda: 'session', cancelled=lambda: False,
            monotonic=lambda: 11, wait=lambda seconds: None)
        args.update(changes)
        return run_observed_sleep(self.request, **args)

    def test_completed_cycle_restores_controls_and_does_not_repeat_sleep(self):
        result = self.run_sleep()
        self.assertEqual(result.code, 'dock_power.sleep_cycle_observed')
        self.assertTrue(result.requested)
        self.assertTrue(all(g.status().active for g in self.guards))
        self.assertFalse(self.run_sleep().requested)
        self.assertEqual(self.events.count('submit'), 1)

    def test_no_transaction_lease_supports_keep_connected_route(self):
        self.assertTrue(self.run_sleep(transaction=None).requested)
        self.assertTrue(self.guards[0].status().active)
        self.assertFalse(self.guards[1].status().active)

    def test_missing_baseline_does_not_consume_or_release(self):
        self.baseline = None
        self.assertEqual(self.run_sleep().code, 'dock_power.sleep_observer_unavailable')
        self.assertEqual(self.events, [])

    def test_failed_unknown_and_timeout_cycles_restore_without_retry(self):
        for state, suffix in [('fail', 'failed'), ('unresolved', 'unresolved'), ('unchanged', 'unresolved')]:
            with self.subTest(state=state):
                self.setUp()
                self.state = state
                result = self.run_sleep()
                self.assertEqual(result.code, 'dock_power.sleep_cycle_' + suffix)
                self.assertTrue(all(g.status().active for g in self.guards))
                self.assertEqual(self.events.count('submit'), 1)

    def test_refused_submission_restores_immediately(self):
        result = self.run_sleep(submit=lambda r: False)
        self.assertFalse(result.requested)
        self.assertTrue(all(g.status().active for g in self.guards))
        self.assertNotIn('observe', self.events)

    def test_failed_protection_restore_is_reported_without_submission(self):
        with patch.object(self.guards[1], 'reacquire_handoff', return_value=False):
            result = self.run_sleep()
        self.assertEqual(result.code, 'dock_power.sleep_protection_unverified')
        self.assertFalse(result.requested)
        self.assertNotIn('submit', self.events)
        self.assertFalse(self.run_sleep().requested)


if __name__ == '__main__':
    unittest.main()
