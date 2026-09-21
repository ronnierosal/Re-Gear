"""Sleep readiness reports the retained transaction lease as its own fact."""
import asyncio
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from tests.test_dock_sleep_lease import Process
from tests.test_main_process_delivery import load_main_module


class SleepReadinessRetainedLeaseTests(unittest.TestCase):
    """The snapshot's sleep_guard is the background controller only.

    The 2026-09-13 trial recorded two Handheld Dock Mode inhibitors still up
    after a successful software removal: the background guard and the
    disconnect transaction's retained lease. A sleep path that only watches
    the first would suspend into the second. So readiness carries the second
    explicitly, in every branch, and never guesses when it cannot read it.
    """

    def setUp(self):
        self.module = load_main_module(real_dock_gate=True)
        self.plugin = self.module.Plugin.__new__(self.module.Plugin)
        self.presence = self.module.EgpuPresence.ABSENT
        self.plugin._sleep_hardware = NS(observe_presence=lambda: self.presence)

    def readiness(self):
        return asyncio.run(self.plugin.get_sleep_readiness())

    def test_no_transaction_this_lifetime_means_nothing_retained(self):
        # The attribute does not exist until a trial ran; that is a False, not a crash.
        payload = self.readiness()
        self.assertEqual(payload['code'], 'sleep.available')
        self.assertIs(payload['retained_inhibitor'], False)

    def test_a_held_transaction_lease_is_reported_even_when_the_egpu_is_absent(self):
        # Exactly the trial shape: software removal done, lease still up.
        self.plugin._whole_dock_trial_lease = self.module.Login1SleepInhibitor(Process)
        self.plugin._whole_dock_trial_lease.acquire()
        payload = self.readiness()
        self.assertEqual(payload['code'], 'sleep.available')
        self.assertIs(payload['retained_inhibitor'], True)

    def test_a_released_transaction_lease_is_not_retained(self):
        self.plugin._whole_dock_trial_lease = self.module.Login1SleepInhibitor(Process)
        self.plugin._whole_dock_trial_lease.acquire()
        self.plugin._whole_dock_trial_lease.release()
        self.assertIs(self.readiness()['retained_inhibitor'], False)

    def test_an_unreadable_lease_is_none_not_false(self):
        class Broken:
            def status(self):
                raise RuntimeError('inhibitor status unavailable')
        self.plugin._whole_dock_trial_lease = Broken()
        self.assertIsNone(self.readiness()['retained_inhibitor'])

    def test_the_unknown_presence_branch_carries_it_too(self):
        self.presence = self.module.EgpuPresence.UNKNOWN
        self.plugin._whole_dock_trial_lease = self.module.Login1SleepInhibitor(Process)
        self.plugin._whole_dock_trial_lease.acquire()
        payload = self.readiness()
        self.assertEqual(payload['code'], 'sleep.readiness_unknown')
        self.assertIs(payload['retained_inhibitor'], True)

    def test_the_requires_disconnect_branch_carries_it_too(self):
        # The branch the disconnect-and-sleep press actually consumes.
        self.presence = self.module.EgpuPresence.PRESENT
        self.plugin._whole_dock_trial_lease = self.module.Login1SleepInhibitor(Process)
        self.plugin._whole_dock_trial_lease.acquire()
        self.plugin._live_disconnect_runtime = lambda: NS(status=lambda: NS(game=None))
        with patch.object(self.module, 'disconnect_status_to_payload',
                          return_value={'game': None}):
            payload = self.readiness()
        self.assertEqual(payload['code'], 'sleep.requires_disconnect')
        self.assertIs(payload['requires_disconnect'], True)
        self.assertIs(payload['retained_inhibitor'], True)


if __name__ == '__main__':
    unittest.main()
