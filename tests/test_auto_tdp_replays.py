"""Synthetic closed-loop workloads, using real session/service and verified readback."""
import unittest
from dataclasses import replace

import test_auto_tdp_session as fixtures
from hdm.domain.models import GameState


class AutoTdpReplayTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.AutoSessionTests()
        self.case.setUp()
        self.case.session.start(self.case.policy)

    def run_until(self, end, fps=None):
        case = self.case
        result = None
        while case.now <= end:
            if fps is not None:
                case.fps = fps(case.provider.current.sustained.current)
            result = case.session.tick()
            case.now += 1000
        return result

    def test_flat_fps_caps_power_growth_after_two_ineffective_verified_increases(self):
        for fps in (30, 45):
            with self.subTest(fps=fps):
                self.setUp()
                result = self.run_until(120000, lambda watts: fps)
                self.assertEqual(self.case.provider.writes, [16, 17])
                self.assertEqual(result.code, "auto_tdp.no_performance_gain")
                self.assertTrue(result.enabled)
                self.assertEqual(self.case.journal.record.baseline.sustained.current, 15)

    def test_responsive_workload_can_continue_increasing(self):
        self.run_until(30000, lambda watts: 25 + 4 * (watts - 15))
        self.assertGreater(len(self.case.provider.writes), 2)
        self.assertLessEqual(max(self.case.provider.writes), 30)

    def test_realistic_frame_rewarming_preserves_only_verified_response_baseline(self):
        original = self.case.session._collect
        writes_seen = 0
        warmup_remaining = 0
        def collect():
            nonlocal writes_seen, warmup_remaining
            if len(self.case.provider.writes) != writes_seen:
                writes_seen = len(self.case.provider.writes)
                warmup_remaining = 4
            if warmup_remaining:
                warmup_remaining -= 1
                return None
            return original()
        self.case.session._collect = collect
        result = self.run_until(120000, lambda watts: 45)
        self.assertEqual(self.case.provider.writes, [16, 17])
        self.assertEqual(result.code, "auto_tdp.no_performance_gain")

    def test_changed_workload_reassesses_after_hold(self):
        self.run_until(40000, lambda watts: 45)
        self.assertEqual(self.case.provider.writes, [16, 17])
        self.run_until(50000, lambda watts: 35)
        self.assertEqual(self.case.provider.writes, [16, 17, 18])

    def test_regained_target_allows_power_reduction(self):
        self.run_until(40000, lambda watts: 45)
        self.run_until(52000, lambda watts: 60)
        self.assertEqual(self.case.provider.writes, [16, 17, 16])

    def test_one_frame_rate_spike_does_not_release_no_gain_hold(self):
        self.run_until(40000, lambda watts: 45)
        self.run_until(41000, lambda watts: 48)
        self.run_until(60000, lambda watts: 45)
        self.assertEqual(self.case.provider.writes, [16, 17])

    def test_missing_live_context_discards_pending_response_baseline(self):
        self.run_until(7000)
        self.case.session._collect = lambda: None
        self.case.ready = False
        self.run_until(9000)
        self.assertIsNone(self.case.session._pending_response)

    def test_game_exit_and_restart_require_fresh_settling_and_streak(self):
        self.run_until(6000)
        self.case.game = GameState.IDLE
        self.run_until(20000)
        self.assertEqual(self.case.provider.writes, [])
        self.case.game = GameState.RUNNING
        self.case.workload = "new-game"
        self.run_until(27000)
        self.assertEqual(self.case.provider.writes, [])
        self.run_until(28000)
        self.assertEqual(self.case.provider.writes, [16])

    def test_mode_or_ownership_loss_before_dispatch_retains_settings(self):
        for field in ("internal_render_verified", "controller_owned", "power_source_ready"):
            with self.subTest(field=field):
                self.setUp()
                self.run_until(6000)
                original = self.case.session._collect
                def missing():
                    evidence = original()
                    return replace(evidence, observation=replace(evidence.observation, **{field: False}))
                self.case.session._collect = missing
                self.run_until(20000)
                self.assertEqual(self.case.provider.writes, [])
                self.case.session._collect = original
                self.run_until(27000)
                self.assertEqual(self.case.provider.writes, [])
                self.run_until(28000)
                self.assertEqual(self.case.provider.writes, [16])

    def test_uncertain_write_stops_all_future_adjustments(self):
        self.case.provider.behavior = "timeout"
        self.run_until(7000)
        self.run_until(120000)
        self.assertFalse(self.case.session.enabled)
        self.assertEqual(self.case.provider.writes, [16])
        self.assertEqual(self.case.journal.record.phase, "pending")
