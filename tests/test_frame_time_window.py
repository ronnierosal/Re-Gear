import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from hdm.domain.frame_time_window import FrameTimeSample, FrameWindowPolicy, FrameWindowState, update_frame_window


class FrameWindowTests(unittest.TestCase):
    def setUp(self):
        self.policy = FrameWindowPolicy()

    def feed(self, times, *, intervals=None, state=FrameWindowState(), key="game-generation"):
        for index, at in enumerate(times):
            sample = FrameTimeSample(key, at, intervals[index] if intervals else 20_000_000)
            result = update_frame_window(self.policy, state, sample, now_ms=at)
            state = result.state
        return result

    def test_estimate_uses_duration_mean_not_mean_of_instantaneous_fps(self):
        result = self.feed(range(0, 5000, 1000), intervals=(10_000_000, 10_000_000, 10_000_000, 10_000_000, 60_000_000))
        self.assertEqual(result.estimated_fps, 50)
        self.assertEqual(result.newest_received_at_ms, 4000)
        self.assertEqual(result.code, "frames.estimated")

    def test_sample_burst_cannot_substitute_for_time_coverage(self):
        result = self.feed(range(10))
        self.assertIsNone(result.estimated_fps)
        self.assertEqual(result.code, "frames.warming")

    def test_changed_game_and_sample_gap_start_new_history(self):
        state = self.feed(range(0, 5000, 1000)).state
        for times, key in (((5000,), "new-game"), ((7001,), "game-generation")):
            result = self.feed(times, state=state, key=key)
            self.assertIsNone(result.estimated_fps)
            self.assertEqual(len(result.state.samples), 1)

    def test_duplicate_or_out_of_order_input_clears_window_and_keeps_watermark(self):
        state = self.feed(range(0, 5000, 1000)).state
        for at in (4000, 3000):
            result = self.feed((at,), state=state)
            self.assertEqual(result.code, "frames.repeated")
            self.assertEqual(result.state.last_sample_ms, 4000)
            self.assertEqual(result.state.samples, ())
            again = self.feed((4000,), state=result.state)
            self.assertEqual(again.code, "frames.repeated")

    def test_unavailable_stale_and_clock_reset_discard_old_estimate(self):
        state = self.feed(range(0, 5000, 1000)).state
        sample = FrameTimeSample("game-generation", 5000, 20_000_000)
        for value, now in ((None, 5000), (sample, 7001), (sample, 4999)):
            result = update_frame_window(self.policy, state, value, now_ms=now)
            self.assertIsNone(result.estimated_fps)
            self.assertEqual(result.state.samples, ())

    def test_count_and_age_bound_long_running_history(self):
        result = self.feed(range(0, 200_000, 1000))
        self.assertEqual(len(result.state.samples), 10)
        self.assertEqual(result.estimated_fps, 50)
        self.policy = replace(self.policy, window_ms=4000, minimum_span_ms=3000, minimum_samples=4)
        result = self.feed(range(0, 10_000, 1000))
        self.assertEqual(len(result.state.samples), 5)

    def test_invalid_readings_and_unbounded_policy_are_rejected(self):
        for duration in (0, -1, True, float("nan"), float("inf"), 1.5, 1 << 64):
            with self.assertRaises(ValueError):
                FrameTimeSample("game", 0, duration)
        for changes in ({"maximum_samples": 61}, {"minimum_samples": 1}, {"minimum_span_ms": 20_000}, {"window_ms": True}, {"minimum_samples": 2, "maximum_samples": 2}):
            with self.assertRaises(ValueError):
                replace(self.policy, **changes)
