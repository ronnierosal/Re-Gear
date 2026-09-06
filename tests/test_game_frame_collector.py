import sys
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from hdm.adapters.steamos.gamescope_performance import PerformanceReading, PerformanceTarget
from hdm.adapters.steamos.gamescope_performance_target import PerformanceTargetResolution
from hdm.delivery.game_frame_collector import GameFrameCollector


class FrameCollectorTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.target = PerformanceTarget(Path.cwd() / "resolved-socket", 1000, 4321, 42, "opaque-context", 12345)
        self.resolution = PerformanceTargetResolution("performance.target_resolved", self.target)
        self.reader = SimpleNamespace(observe=lambda target: PerformanceReading("performance.observed", target.context_key, int(self.now * 1000), 20_000_000))
        self.collector = GameFrameCollector(resolve=lambda: self.resolution, reader=self.reader, clock=lambda: self.now)

    def warm(self):
        for _ in range(5):
            result = self.collector.collect()
            self.now += 1
        return result

    def test_independent_bound_reads_build_sampled_estimate(self):
        result = self.warm()
        self.assertEqual(result.sampled_fps, 50)
        self.assertEqual(result.newest_received_at_ms, 14_000)
        self.assertEqual(result.sample_count, 5)
        self.assertEqual(result.span_ms, 4000)
        self.assertEqual(result.context_key, "opaque-context")

    def test_resolution_changes_after_read_discard_all_history(self):
        self.warm()
        for target in (None, replace(self.target, context_key="new-generation"), replace(self.target, app_id=43)):
            resolutions = iter((self.resolution, PerformanceTargetResolution("performance.target_resolved", target)))
            self.collector._resolve = lambda: next(resolutions)
            result = self.collector.collect()
            self.assertEqual(result.code, "frames.context_changed")
            self.assertIsNone(result.sampled_fps)

    def test_missing_target_does_not_call_reader_and_clears_history(self):
        self.warm()
        self.resolution = PerformanceTargetResolution("performance.target_unavailable")
        self.reader.observe = lambda _: self.fail("must not query a missing target")
        result = self.collector.collect()
        self.assertEqual(result.code, "frames.target_unavailable")
        self.assertEqual(result.sample_count, 0)

    def test_timeout_or_exception_never_reuses_last_fps(self):
        self.warm()
        self.reader.observe = lambda _: PerformanceReading("performance.timeout")
        result = self.collector.collect()
        self.assertIsNone(result.sampled_fps)
        def fail(_):
            raise OSError("private socket path")
        self.reader.observe = fail
        self.assertEqual(self.collector.collect().code, "frames.unavailable")

    def test_slow_final_resolution_cannot_refresh_sample_timestamp(self):
        calls = [0]
        def resolve():
            calls[0] += 1
            if calls[0] == 2:
                self.now += 3
            return self.resolution
        self.collector._resolve = resolve
        result = self.collector.collect()
        self.assertEqual(result.code, "frames.stale")
        self.assertIsNone(result.sampled_fps)
        self.assertEqual(result.collection_cost_ms, 3000)

    def test_reader_response_cannot_claim_different_game(self):
        self.reader.observe = lambda _: PerformanceReading("performance.observed", "other-game", 10_000, 20_000_000)
        self.assertEqual(self.collector.collect().code, "frames.context_changed")

    def test_overlapping_call_does_not_send_second_request(self):
        self.collector._lock.acquire()
        try:
            self.assertEqual(self.collector.collect().code, "frames.busy")
        finally:
            self.collector._lock.release()
        self.assertEqual(self.collector.collect().code, "frames.warming")
