import threading
import unittest
from types import SimpleNamespace

import test_tdp_runtime as fixtures
from hdm.application.tdp_control import TdpControlService
from hdm.delivery.auto_tdp_benchmark import AutoTdpBenchmarkResult
from hdm.delivery.tdp_runtime import TdpRuntime
from hdm.domain.auto_tdp import AutoTdpPolicy


class BenchmarkLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.journal = fixtures.MemoryJournal()
        self.provider = fixtures.GuardedProvider(self.journal)
        self.lease = fixtures.Lease()
        def provider(guard):
            self.provider.guard = guard
            return self.provider
        self.runtime = TdpRuntime(provider_factory=provider, journal=self.journal,
            lease=self.lease, preflight=lambda: "tdp.ready",
            service_factory=lambda p, j: TdpControlService(p, j, wait=lambda _: None))
        self.release, self.entered = threading.Event(), threading.Event()
        self.results = []
        self.thread = None
        self.cancel = None
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.release.set()
        self.runtime.close()
        if self.thread is not None:
            self.thread.join(2)
            self.assertFalse(self.thread.is_alive())

    @staticmethod
    def report(code="auto_tdp.benchmark_within_budget"):
        return AutoTdpBenchmarkResult(code, 12, 8, 8, 5, 11060, 1000)

    def operation(self, provider, cancel):
        self.assertIs(provider, self.provider)
        self.cancel = cancel
        self.entered.set()
        if not self.release.wait(2):
            raise TimeoutError("test release missing")
        return self.report("auto_tdp.benchmark_cancelled" if cancel.is_set() else "auto_tdp.benchmark_within_budget")

    def start(self):
        self.runtime.set_enabled(True)
        self.thread = threading.Thread(target=lambda: self.results.append(
            self.runtime.run_benchmark(self.operation, admission_guard=lambda: True)))
        self.thread.start()
        self.assertTrue(self.entered.wait(1))

    def finish(self):
        self.release.set()
        self.thread.join(2)
        self.assertFalse(self.thread.is_alive())

    def test_benchmark_needs_manual_ownership_and_never_enables_it(self):
        result = self.runtime.run_benchmark(lambda *args: self.fail("must not collect"), admission_guard=lambda: True)
        self.assertEqual(result["code"], "tdp.disabled")
        self.assertFalse(self.lease.held)
        self.assertEqual(self.provider.writes, [])

    def test_runtime_lock_excludes_auto_and_manual_writes_until_benchmark_finishes(self):
        self.start()
        self.assertTrue(self.runtime.benchmark_status()["running"])
        self.assertIsNone(self.runtime.start_auto(AutoTdpPolicy(7, 30, 60)))
        self.assertEqual(self.runtime.apply(20)["code"], "tdp.busy")
        self.assertTrue(self.cancel.is_set())
        self.assertEqual(self.provider.writes, [])
        self.finish()
        self.assertFalse(self.runtime.benchmark_status()["running"])
        self.assertIsNone(self.journal.record)

    def test_disable_cancels_collection_then_restores_without_overlapping(self):
        self.runtime.set_enabled(True)
        self.runtime.apply(20)
        self.start()
        self.assertEqual(self.runtime.set_enabled(False)["code"], "tdp.busy")
        self.assertTrue(self.cancel.is_set())
        self.assertTrue(self.lease.held)
        self.assertEqual(self.provider.writes, [20])
        self.finish()
        self.assertEqual(self.provider.writes, [20, 15])
        self.assertFalse(self.lease.held)
        self.assertIsNone(self.journal.record)

    def test_close_cancels_and_releases_ownership_after_read_only_drain(self):
        self.start()
        self.runtime.close()
        self.assertTrue(self.cancel.is_set())
        self.assertTrue(self.lease.held)
        self.finish()
        self.assertFalse(self.lease.held)
        self.assertEqual(self.provider.writes, [])

    def test_cancel_during_readiness_cannot_be_cleared_by_old_run(self):
        self.runtime.set_enabled(True)
        def readiness():
            self.entered.set()
            if not self.release.wait(2):
                raise TimeoutError("test release missing")
            return "tdp.ready"
        self.runtime._preflight = readiness
        calls = []
        self.thread = threading.Thread(target=lambda: self.results.append(self.runtime.run_benchmark(
            lambda *args: calls.append(True) or self.report(), admission_guard=lambda: True)))
        self.thread.start()
        self.assertTrue(self.entered.wait(1))
        self.runtime.cancel_benchmark()
        self.finish()
        self.assertEqual(calls, [])
        self.assertEqual(self.results[0]["code"], "auto_tdp.benchmark_cancelled")

    def test_running_auto_worker_and_revoked_rpc_reject_before_collection(self):
        self.runtime.set_enabled(True)
        self.runtime._auto_worker = SimpleNamespace(status=lambda: SimpleNamespace(running=True), stop=lambda: None)
        operation = lambda *args: self.fail("must not collect")
        self.assertEqual(self.runtime.run_benchmark(operation, admission_guard=lambda: True)["code"], "auto_tdp.benchmark_stop_auto_first")
        self.assertEqual(self.runtime.run_benchmark(operation, admission_guard=lambda: False)["code"], "auto_tdp.benchmark_cancelled")

    def test_completed_measurement_is_reported_without_journal_or_writes(self):
        self.runtime.set_enabled(True)
        result = self.runtime.run_benchmark(lambda *args: self.report(), admission_guard=lambda: True)
        self.assertFalse(result["running"])
        self.assertEqual(result["result"]["maximum_collection_and_revalidation_ms"], 5)
        self.assertEqual(self.provider.writes, [])
        self.assertIsNone(self.journal.record)

    def test_exception_drops_running_state_and_preserves_manual_readiness(self):
        self.runtime.set_enabled(True)
        def fail(*args):
            raise OSError("private path")
        result = self.runtime.run_benchmark(fail, admission_guard=lambda: True)
        self.assertEqual(result["code"], "auto_tdp.benchmark_unavailable")
        self.assertFalse(result["running"])
        self.assertTrue(self.runtime.status()["ready"])
