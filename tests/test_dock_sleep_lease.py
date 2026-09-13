"""Exercise real guard/lease handoff with only the OS process replaced."""
import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from regear.adapters.steamos.commands import ManagedProcessStatus
from regear.adapters.steamos.sleep_inhibitor import Login1SleepInhibitor, SleepGuardController
from regear.delivery.dock_power_service import DockPowerRequest
from regear.delivery.dock_sleep_handoff import HandoffCapabilities, SleepLeaseHandoff
from regear.delivery.dock_sleep_lease import GuardSleepLease
from regear.domain.models import EgpuPresence


class Process:
    def __init__(self):
        self.running = False

    def start(self):
        self.running = True
        return self.status()

    def stop(self):
        self.running = False
        return self.status()

    def status(self):
        return ManagedProcessStatus(self.running)


class GuardSleepLeaseTests(unittest.TestCase):
    def setUp(self):
        self.request = DockPowerRequest('a' * 32, 'sleep', 'session', 10, 20)
        self.guards = [SleepGuardController(Login1SleepInhibitor(Process)) for _ in range(2)]
        for guard in self.guards:
            guard.reconcile(EgpuPresence.PRESENT)
        self.leases = [GuardSleepLease(g, self.request) for g in self.guards]

    def handoff(self, submit):
        return SleepLeaseHandoff(
            self.request, background=self.leases[0], transaction=self.leases[1],
            verify_original=lambda r: r is self.request,
            intent_consumed=lambda r: r is self.request,
            request_sleep=submit, session=lambda: 'session', cancelled=lambda: False,
            monotonic=lambda: 11,
            capabilities=lambda: HandoffCapabilities(True, True, True, True))

    def test_accepted_sleep_pauses_polling_until_restore_without_replay(self):
        calls = []
        def submit(request):
            calls.append(request)
            for guard in self.guards:
                self.assertFalse(guard.reconcile(EgpuPresence.PRESENT).active)
            return True
        handoff = self.handoff(submit)
        self.assertTrue(handoff.submit('sleep'))
        self.assertFalse(handoff.submit('sleep'))
        self.assertTrue(handoff.restore())
        self.assertEqual(calls, [self.request])
        for guard in self.guards:
            self.assertTrue(guard.status().active)
            self.assertFalse(guard.reconcile(EgpuPresence.ABSENT).active)

    def test_refused_sleep_restores_both_actual_guards(self):
        handoff = self.handoff(lambda request: False)
        self.assertFalse(handoff.submit('sleep'))
        self.assertTrue(handoff.status.protection_verified)
        self.assertTrue(all(g.status().active for g in self.guards))

    def test_another_request_or_adapter_cannot_release_owned_guard(self):
        lease = self.leases[0]
        self.assertTrue(lease.prepare(self.request))
        self.assertFalse(lease.release(replace(self.request)))
        other = GuardSleepLease(self.guards[0], self.request)
        self.assertFalse(other.prepare(self.request))
        self.assertFalse(other.release(self.request))
        self.assertTrue(lease.active())

    def test_prepare_keeps_protection_and_finish_requires_reacquisition(self):
        lease = self.leases[0]
        self.assertTrue(lease.prepare(self.request))
        self.assertTrue(self.guards[0].reconcile(EgpuPresence.ABSENT).active)
        self.assertTrue(lease.release(self.request))
        self.assertFalse(lease.finish(self.request))
        self.assertTrue(lease.reacquire(self.request))
        self.assertTrue(lease.finish(self.request))

    def test_close_cannot_be_reopened_by_late_restore(self):
        lease = self.leases[0]
        self.assertTrue(lease.prepare(self.request))
        self.guards[0].close()
        self.assertFalse(lease.owned(self.request))
        self.assertFalse(lease.reacquire(self.request))
        self.assertFalse(lease.prepare(self.request))
        self.assertFalse(self.guards[0].reconcile(EgpuPresence.PRESENT).active)


if __name__ == '__main__':
    unittest.main()
