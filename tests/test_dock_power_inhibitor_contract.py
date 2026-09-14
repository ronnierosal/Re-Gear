"""Offline evidence for the existing two-lease boundary, not sleep support."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from regear.adapters.steamos.sleep_inhibitor import Login1SleepInhibitor, SleepGuardController
from regear.domain.models import EgpuPresence
from regear.delivery.dock_power_service import DockPowerRequest, continue_dock_power
from regear.application.dock_power import DockPowerCoordinator


class Process:
    def __init__(self):
        self.running = False

    def status(self):
        return SimpleNamespace(running=self.running, error='')

    def start(self):
        self.running = True
        return self.status()

    def stop(self):
        self.running = False
        return self.status()


class DockPowerInhibitorContractTests(unittest.TestCase):
    def test_background_absence_does_not_release_transaction_lease(self):
        background = Login1SleepInhibitor(Process)
        transaction = Login1SleepInhibitor(Process)
        guard = SleepGuardController(background)
        guard.reconcile(EgpuPresence.PRESENT)
        transaction.acquire()
        guard.reconcile(EgpuPresence.ABSENT)
        self.assertFalse(background.status().active)
        self.assertTrue(transaction.status().active)
        transaction.release()

    def test_releasing_background_lease_alone_does_not_pause_reconciliation(self):
        lease = Login1SleepInhibitor(Process)
        guard = SleepGuardController(lease)
        guard.reconcile(EgpuPresence.PRESENT)
        lease.release()
        self.assertTrue(guard.reconcile(EgpuPresence.PRESENT).active)
        guard.close()

    def test_close_is_terminal_not_a_cancel_reacquisition_mechanism(self):
        guard = SleepGuardController(Login1SleepInhibitor(Process))
        guard.reconcile(EgpuPresence.PRESENT)
        guard.close()
        self.assertFalse(guard.reconcile(EgpuPresence.PRESENT).active)

    def test_forged_sleep_request_cannot_reach_any_continuation_dependency(self):
        class Forbidden:
            def __getattr__(self, name):
                raise AssertionError('sleep accessed dependency: ' + name)

        forbidden = Forbidden()
        request = DockPowerRequest('a' * 32, 'sleep', 'session', 10, 20)
        result = continue_dock_power(
            request, runtime=forbidden, store=forbidden,
            portable_verified=forbidden, power=forbidden,
            admission_held=forbidden, monotonic=lambda: 11,
        )
        self.assertEqual(result.code, 'dock_power.sleep_unverified')
        self.assertFalse(result.requested)

    def test_ambiguous_original_request_stays_consumed_with_both_leases_held(self):
        background = Login1SleepInhibitor(Process)
        transaction = Login1SleepInhibitor(Process)
        background.acquire()
        transaction.acquire()
        calls = []

        def submit(action):
            calls.append(action)
            self.assertTrue(background.status().active)
            self.assertTrue(transaction.status().active)
            raise TimeoutError('submission may have reached the platform')

        coordinator = DockPowerCoordinator(
            operation_id='b' * 32, action='shutdown', requested_at=10, deadline=20,
            verify_down=lambda _: True, record_intent=lambda *args: True,
            request_power=submit, admission_held=lambda: True, monotonic=lambda: 11,
        )
        self.assertEqual(coordinator.execute().code, 'dock_power.unresolved')
        self.assertEqual(coordinator.execute().code, 'dock_power.already_consumed')
        self.assertEqual(calls, ['shutdown'])
        self.assertTrue(background.status().active)
        self.assertTrue(transaction.status().active)
        background.release()
        transaction.release()
