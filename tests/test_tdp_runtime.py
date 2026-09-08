import unittest

from test_tdp_control import MemoryJournal, Provider, reading
from hdm.application.tdp_control import TdpControlService
from hdm.delivery.tdp_runtime import TdpRuntime
from hdm.ports.tdp import TdpObservation


class Lease:
    def __init__(self):
        self.held = False
        self.available = True
    def acquire(self):
        self.held = self.available
        return self.held
    def close(self):
        self.held = False


class GuardedProvider(Provider):
    def observe(self):
        observation = super().observe()
        return TdpObservation("tdp.ready" if self.guard() else "tdp.ownership_unverified", observation.reading)
    def set_limit(self, expected, watts):
        if not self.guard():
            from hdm.ports.tdp import TdpWriteOutcome
            return TdpWriteOutcome(False, False, "tdp.ownership_unverified")
        return super().set_limit(expected, watts)


class TdpRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.journal = MemoryJournal()
        self.provider = GuardedProvider(self.journal)
        self.lease = Lease()
        self.code = "tdp.ready"
        self.wait = lambda _: None
        def factory(guard):
            self.provider.guard = guard
            return self.provider
        self.runtime = TdpRuntime(
            provider_factory=factory, journal=self.journal, lease=self.lease,
            preflight=lambda: self.code,
            service_factory=lambda provider, journal: TdpControlService(provider, journal, wait=lambda delay: self.wait(delay)),
        )

    def test_status_is_read_only_and_enable_is_explicit(self):
        status = self.runtime.status()
        self.assertTrue(status["can_enable"])
        self.assertFalse(status["enabled"])
        self.assertFalse(status["ready"])
        self.assertEqual(status["current_watts"], 15)
        self.assertFalse(self.lease.held)
        self.assertEqual(self.runtime.apply(20)["code"], "tdp.enable_required")
        self.assertEqual(self.provider.writes, [])

    def test_enable_apply_disable_restores_original(self):
        self.assertTrue(self.runtime.set_enabled(True)["ready"])
        applied = self.runtime.apply(20)
        self.assertEqual(applied["last_result"]["state"], "applied")
        self.assertTrue(applied["restore_available"])
        disabled = self.runtime.set_enabled(False)
        self.assertFalse(disabled["enabled"])
        self.assertEqual(disabled["current_watts"], 15)
        self.assertFalse(self.lease.held)

    def test_manual_restore_is_available_after_reload_without_auto_writes(self):
        self.runtime.set_enabled(True)
        self.runtime.apply(20)
        self.runtime.close()
        reopened = TdpRuntime(provider_factory=lambda guard: self._rebind(guard), journal=self.journal, lease=self.lease, preflight=lambda: self.code,
                              service_factory=lambda p, j: TdpControlService(p, j, wait=lambda _: None))
        self.assertEqual(self.provider.writes, [20])
        self.assertTrue(reopened.status()["restore_available"])
        self.assertFalse(reopened.status()["enabled"])
        self.assertEqual(reopened.restore()["last_result"]["state"], "restored")
        self.assertFalse(self.lease.held)
    def _rebind(self, guard):
        self.provider.guard = guard
        return self.provider

    def test_competing_controller_blocks_enable_and_fresh_write(self):
        self.code = "tdp.conflict"
        self.assertFalse(self.runtime.set_enabled(True)["ready"])
        self.code = "tdp.ready"
        self.runtime.set_enabled(True)
        self.code = "tdp.conflict"
        self.assertFalse(self.runtime.apply(20)["ready"])
        self.assertEqual(self.provider.writes, [])

    def test_process_lease_refusal_never_enables(self):
        self.lease.available = False
        self.assertEqual(self.runtime.set_enabled(True)["code"], "tdp.writer_busy")
        self.assertFalse(self.runtime.status()["enabled"])

    def test_pending_or_external_state_blocks_controls(self):
        self.runtime.set_enabled(True)
        self.provider.behavior = "timeout"
        result = self.runtime.apply(20)
        self.assertTrue(result["recovery_required"])
        self.assertFalse(result["ready"])
        disabled = self.runtime.set_enabled(False)
        self.assertFalse(disabled["enabled"])
        self.assertFalse(self.lease.held)
        self.assertEqual(self.provider.writes, [20])

    def test_close_during_verification_does_not_wait_or_release_inflight_lease(self):
        self.runtime.set_enabled(True)
        self.provider.behavior = "partial"
        observed = []
        def closing_wait(_):
            self.runtime.close()
            observed.append(self.lease.held)
        self.wait = closing_wait
        self.runtime.apply(20)
        self.assertEqual(observed, [True])
        self.assertFalse(self.lease.held)
        self.assertEqual(self.journal.record.phase, "pending")
        self.assertEqual(self.runtime.apply(21)["code"], "tdp.closing")
        self.assertEqual(self.provider.writes, [20])

    def test_disable_releases_even_if_journal_read_fails(self):
        self.runtime.set_enabled(True)
        def fail():
            raise OSError("private details")
        self.journal.load = fail
        result = self.runtime.set_enabled(False)
        self.assertFalse(result["enabled"])
        self.assertFalse(self.lease.held)
        self.assertNotIn("private details", str(result))

    def test_late_preflight_regression_does_not_report_ready(self):
        self.runtime.set_enabled(True)
        self.provider.guard = lambda: False
        self.assertFalse(self.runtime.status()["ready"])

    def test_invalid_enable_type_does_not_acquire(self):
        self.assertEqual(self.runtime.set_enabled(1)["code"], "tdp.request_invalid")
        self.assertFalse(self.lease.held)
