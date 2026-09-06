import threading
import unittest
from unittest.mock import patch

import test_tdp_runtime as runtime_fixtures
import test_tdp_control as control_fixtures
from hdm.application.auto_tdp_session import AutoTdpSessionResult
from hdm.application.tdp_control import TdpControlService
from hdm.delivery.tdp_runtime import TdpRuntime
from hdm.delivery.auto_tdp_worker import AutoTdpWorker
from hdm.domain.auto_tdp import AutoTdpPolicy
from hdm.ports.tdp import TdpWriteOutcome


class Provider(runtime_fixtures.GuardedProvider):
    def __init__(self, journal):
        super().__init__(journal)
        self.entered = threading.Event()
        self.release = threading.Event()
        self.delay = True

    def set_limit(self, expected, watts, *, dispatch_guard=None):
        if not self.guard() or (dispatch_guard is not None and dispatch_guard() is not True):
            return TdpWriteOutcome(False, False, "tdp.dispatch_rejected")
        if self.delay:
            self.delay = False
            self.entered.set()
            if not self.release.wait(2):
                raise TimeoutError("test release missing")
        # Model an already-dispatched write finishing after stop was requested.
        return control_fixtures.Provider.set_limit(self, expected, watts)


class Session:
    collection_interval_ms = 1000

    def __init__(self, actuator, gate):
        self.actuator = actuator
        self.gate = gate
        self.enabled = False

    def start(self, policy):
        self.enabled = True
        return AutoTdpSessionResult("auto_tdp.started", True)

    def stop(self):
        self.enabled = False

    def tick(self):
        if not self.gate.wait(2):
            raise TimeoutError("test gate missing")
        result = self.actuator.apply(20, dispatch_guard=lambda: self.enabled)
        return AutoTdpSessionResult(result.code, self.enabled, 20, result)


class AutoLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.journal = control_fixtures.MemoryJournal()
        self.provider = Provider(self.journal)
        self.lease = runtime_fixtures.Lease()
        self.gate = threading.Event()
        self.session = None
        def provider_factory(guard):
            self.provider.guard = guard
            return self.provider
        def auto_factory(actuator, provider):
            self.session = Session(actuator, self.gate)
            return self.session
        self.runtime = TdpRuntime(provider_factory=provider_factory, journal=self.journal,
            lease=self.lease, preflight=lambda: "tdp.ready", auto_session_factory=auto_factory,
            service_factory=lambda p, j: TdpControlService(p, j, wait=lambda _: None))
        self.policy = AutoTdpPolicy(7, 30, 60)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.runtime.close()
        self.gate.set()
        self.provider.release.set()
        if self.runtime._auto_worker is not None:
            self.assertTrue(self.runtime._auto_worker.wait_stopped(2))

    def start_inflight(self):
        self.runtime.set_enabled(True)
        self.assertTrue(self.runtime.start_auto(self.policy).running)
        self.gate.set()
        self.assertTrue(self.provider.entered.wait(1))

    def test_no_auto_start_without_manual_ownership_or_configured_factory(self):
        self.assertIsNone(self.runtime.start_auto(self.policy))
        self.assertIsNone(self.runtime.auto_status())
        self.runtime.set_enabled(True)
        self.runtime._auto_factory = None
        self.assertIsNone(self.runtime.start_auto(self.policy))
        self.assertEqual(self.provider.writes, [])

    def test_restart_after_drain_recreates_session_for_current_configuration(self):
        self.runtime.set_enabled(True)
        self.runtime.start_auto(self.policy)
        previous = self.session
        self.runtime.stop_auto()
        self.gate.set()
        self.assertTrue(self.runtime._auto_worker.wait_stopped(2))
        self.gate.clear()
        self.assertTrue(self.runtime.start_auto(AutoTdpPolicy(7, 30, 45)).running)
        self.assertIsNot(self.session, previous)
        self.assertEqual(self.runtime.auto_policy.target_fps, 45)
        self.assertEqual(self.provider.writes, [])

    def test_start_range_must_fit_provider_and_include_current_setting(self):
        self.runtime.set_enabled(True)
        for policy in (AutoTdpPolicy(7, 40, 60), AutoTdpPolicy(7, 14, 60), AutoTdpPolicy(16, 30, 60)):
            self.assertIsNone(self.runtime.start_auto(policy))
        self.assertIsNone(self.session)
        self.assertEqual(self.provider.writes, [])

    def test_rpc_admission_is_checked_again_at_final_dispatch(self):
        admitted = [True]
        finished = threading.Event()
        original = self.provider.set_limit
        def attempt(*args, **kwargs):
            result = original(*args, **kwargs)
            finished.set()
            return result
        self.provider.set_limit = attempt
        self.provider.release.set()
        self.runtime.set_enabled(True)
        self.runtime.start_auto(self.policy, admission_guard=lambda: admitted[0])
        admitted[0] = False
        self.gate.set()
        self.assertTrue(finished.wait(1))
        self.runtime.stop_auto()
        self.assertTrue(self.runtime._auto_worker.wait_stopped(2))
        self.assertEqual(self.provider.writes, [])
        self.assertIsNone(self.journal.record)

    def test_disable_queues_restore_after_inflight_auto_transaction(self):
        self.start_inflight()
        response = self.runtime.set_enabled(False)
        self.assertEqual(response["code"], "tdp.busy")
        self.assertFalse(self.session.enabled)
        self.assertTrue(self.lease.held)
        self.assertEqual(self.journal.record.phase, "pending")
        self.provider.release.set()
        self.assertTrue(self.runtime._auto_worker.wait_stopped(1))
        self.assertEqual(self.provider.writes, [20, 15])
        self.assertIsNone(self.journal.record)
        self.assertFalse(self.lease.held)
        self.assertFalse(self.runtime.status()["enabled"])

    def test_close_retains_inflight_lease_and_uncertain_journal_without_restore(self):
        self.start_inflight()
        self.runtime.close()
        self.assertTrue(self.lease.held)
        self.assertFalse(self.session.enabled)
        self.provider.release.set()
        self.assertTrue(self.runtime._auto_worker.wait_stopped(1))
        self.assertEqual(self.provider.writes, [20])
        self.assertEqual(self.journal.record.phase, "pending")
        self.assertFalse(self.lease.held)

    def test_manual_apply_cancels_auto_but_cannot_overlap_dispatched_write(self):
        self.start_inflight()
        self.assertEqual(self.runtime.apply(18)["code"], "tdp.busy")
        self.assertFalse(self.session.enabled)
        self.assertTrue(self.lease.held)
        self.provider.release.set()
        self.assertTrue(self.runtime._auto_worker.wait_stopped(1))
        self.assertEqual(self.runtime.apply(18)["last_result"]["state"], "applied")
        self.assertEqual(self.provider.writes, [20, 18])

    def test_close_during_read_only_collection_prevents_later_dispatch(self):
        self.runtime.set_enabled(True)
        self.runtime.start_auto(self.policy)
        self.runtime.close()
        self.gate.set()
        self.assertTrue(self.runtime._auto_worker.wait_stopped(1))
        self.assertEqual(self.provider.writes, [])
        self.assertFalse(self.lease.held)

    def test_close_or_manual_stop_during_factory_cannot_start_worker(self):
        self.runtime.set_enabled(True)
        factory = self.runtime._auto_factory
        def stop_factory(actuator, provider):
            self.runtime.stop_auto()
            return factory(actuator, provider)
        self.runtime._auto_factory = stop_factory
        self.assertIsNone(self.runtime.start_auto(self.policy))
        self.assertFalse(self.runtime.auto_status().running)
        self.runtime._auto_worker = None
        def close_factory(actuator, provider):
            self.runtime.close()
            return factory(actuator, provider)
        self.runtime._auto_factory = close_factory
        self.assertIsNone(self.runtime.start_auto(self.policy))
        self.assertFalse(self.runtime.auto_status().running)
        self.assertFalse(self.lease.held)

    def cleanup_gap(self, action):
        self.runtime.set_enabled(True)
        entered, release = threading.Event(), threading.Event()
        original = self.runtime._finish_operation
        def finish():
            original()
            entered.set()
            if not release.wait(2):
                raise TimeoutError("test cleanup gap not released")
        self.runtime._finish_operation = finish
        thread = threading.Thread(target=self.runtime.status)
        thread.start()
        try:
            self.assertTrue(entered.wait(1))
            action()
        finally:
            release.set()
            thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertFalse(self.lease.held)
        self.assertFalse(self.runtime._enabled)
        self.assertFalse(self.runtime._disable_requested.is_set())

    def test_close_between_cleanup_and_unlock_cannot_strand_lease(self):
        self.cleanup_gap(self.runtime.close)

    def test_disable_between_cleanup_and_unlock_is_not_lost(self):
        self.cleanup_gap(lambda: self.runtime.set_enabled(False))

    def start_gap(self, action):
        self.runtime.set_enabled(True)
        entered, release = threading.Event(), threading.Event()
        original = AutoTdpWorker.start
        def start(worker, policy):
            entered.set()
            if not release.wait(2):
                raise TimeoutError("test start gap not released")
            return original(worker, policy)
        with patch.object(AutoTdpWorker, "start", start):
            thread = threading.Thread(target=lambda: self.runtime.start_auto(self.policy))
            thread.start()
            try:
                self.assertTrue(entered.wait(1))
                action()
            finally:
                release.set()
                thread.join(1)
        self.assertFalse(thread.is_alive())
        self.gate.set()
        self.assertTrue(self.runtime._auto_worker.wait_stopped(1))
        self.assertFalse(self.session.enabled)
        self.assertEqual(self.provider.writes, [])

    def test_close_immediately_before_worker_start_cancels_new_loop(self):
        self.start_gap(self.runtime.close)
        self.assertFalse(self.lease.held)

    def test_stop_immediately_before_worker_start_cancels_new_loop(self):
        self.start_gap(self.runtime.stop_auto)
