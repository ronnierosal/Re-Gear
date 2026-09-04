import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from hdm.application.auto_tdp_dispatch import AutoTdpDispatchContext, AutoTdpDispatchGuard
from test_tdp_control import reading


class AutoDispatchTests(unittest.TestCase):
    def test_missing_expected_context_or_reading_never_authorizes(self):
        with self.assertRaises(ValueError):
            AutoTdpDispatchGuard(None, 0, 2000, lambda: None, lambda: 1000)
        with self.assertRaises(ValueError):
            AutoTdpDispatchContext("enable", "game", None)

    def setUp(self):
        self.context = AutoTdpDispatchContext("enable-generation", "game-generation", reading())
        self.live = self.context
        self.now = 1000
        self.guard = AutoTdpDispatchGuard(self.context, 0, 2000, lambda: self.live, lambda: self.now)

    def test_only_exact_live_context_and_fresh_sample_pass(self):
        self.assertTrue(self.guard())
        for current in (None, replace(self.context, activation_key="new-enable"), replace(self.context, workload_key="other-game"), replace(self.context, reading=reading(20, 20, 20))):
            self.live = current
            self.assertFalse(self.guard())

    def test_slow_context_observation_cannot_extend_sample_lifetime(self):
        def observe():
            self.now = 2001
            return self.context
        self.assertFalse(replace(self.guard, observe_context=observe)())

    def test_stale_future_or_invalid_clock_is_refused_before_observation(self):
        def fail():
            self.fail("stale guard must not start expensive observation")
        guard = replace(self.guard, observe_context=fail)
        for now in (-1, 2001, True, float("nan")):
            self.now = now
            self.assertFalse(guard())
