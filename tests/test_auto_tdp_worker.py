import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from hdm.application.auto_tdp_session import AutoTdpSessionResult
from hdm.delivery.auto_tdp_worker import AutoTdpWorker
from hdm.domain.auto_tdp import AutoTdpPolicy


class Session:
    def __init__(self):
        self.enabled = False
        self.starts = 0
        self.ticks = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.allow_start = True
        self.fail = False

    def start(self, policy):
        self.starts += 1
        self.enabled = self.allow_start
        return AutoTdpSessionResult("test.start", self.enabled)

    def stop(self):
        self.enabled = False

    def tick(self):
        self.ticks += 1
        self.entered.set()
        if not self.release.wait(2):
            raise TimeoutError("test did not release")
        if self.fail:
            raise OSError("private detail")
        return AutoTdpSessionResult("test.tick", self.enabled)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.session = Session()
        self.worker = AutoTdpWorker(self.session, interval_ms=1000)
        self.policy = AutoTdpPolicy(7, 30, 60)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.worker.stop()
        self.session.release.set()
        self.assertTrue(self.worker.wait_stopped(2))

    def test_construction_and_rejected_start_do_not_run(self):
        self.assertFalse(self.worker.status().running)
        self.assertEqual(self.session.ticks, 0)
        self.session.allow_start = False
        self.assertFalse(self.worker.start(self.policy).running)
        self.assertEqual(self.session.ticks, 0)

    def test_stop_is_nonblocking_but_does_not_claim_inflight_tick_drained(self):
        self.worker.start(self.policy)
        self.assertTrue(self.session.entered.wait(1))
        status = self.worker.stop()
        self.assertFalse(self.session.enabled)
        self.assertTrue(status.running)
        self.assertTrue(status.stopping)
        self.assertFalse(self.worker.wait_stopped())
        self.session.release.set()
        self.assertTrue(self.worker.wait_stopped(1))
        self.assertFalse(self.worker.status().running)
        self.assertEqual(self.session.ticks, 1)

    def test_duplicate_start_and_restart_before_drain_do_not_create_second_loop(self):
        self.worker.start(self.policy)
        self.assertTrue(self.session.entered.wait(1))
        self.worker.start(self.policy)
        self.worker.stop()
        self.assertTrue(self.worker.start(self.policy).stopping)
        self.assertEqual(self.session.starts, 1)
        self.assertEqual(self.session.ticks, 1)

    def test_worker_failure_is_categorical_and_stops_session(self):
        self.session.fail = True
        self.session.release.set()
        self.worker.start(self.policy)
        self.assertTrue(self.worker.wait_stopped(1))
        self.assertFalse(self.session.enabled)
        self.assertEqual(self.worker.status().last_result.code, "auto_tdp.worker_unavailable")

    def test_stop_interrupts_cadence_wait(self):
        self.session.release.set()
        self.worker = AutoTdpWorker(self.session, interval_ms=60_000)
        self.worker.start(self.policy)
        self.assertTrue(self.session.entered.wait(1))
        self.worker.stop()
        self.assertTrue(self.worker.wait_stopped(1))
        self.assertEqual(self.session.ticks, 1)

    def test_drain_does_not_report_old_generation_as_current_worker_completion(self):
        self.worker.start(self.policy)
        self.assertTrue(self.session.entered.wait(1))
        self.worker.stop()
        self.session.release.set()
        self.assertTrue(self.worker.wait_stopped(1))
        old = self.worker._thread
        original_join = old.join
        def restart_after_join(timeout):
            original_join(timeout)
            self.worker.start(self.policy)
        with patch.object(old, "join", side_effect=restart_after_join):
            self.assertFalse(self.worker.wait_stopped(1))
        self.assertTrue(self.worker.status().running)

    def test_invalid_cadence_and_unbounded_drain_are_rejected(self):
        for interval in (True, 999, 60_001, 1000.0):
            with self.assertRaises(ValueError):
                AutoTdpWorker(self.session, interval_ms=interval)
        for timeout in (-1, 6, True, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                self.worker.wait_stopped(timeout)
