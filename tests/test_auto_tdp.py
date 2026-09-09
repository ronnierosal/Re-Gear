from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from hdm.domain.auto_tdp import AutoTdpObservation, AutoTdpPolicy, AutoTdpState, propose_auto_tdp
from hdm.domain.models import GameState


class AutoTdpTests(unittest.TestCase):
    def setUp(self):
        self.policy = AutoTdpPolicy(7, 30, 60)
        self.sample = AutoTdpObservation("opaque-session", 0, 60, 15, GameState.RUNNING, True, True, True, True)
        self.state = propose_auto_tdp(self.policy, AutoTdpState(), self.sample, now_ms=0).state
        for at in (1000, 2000, 3000, 4000):
            decision = self.decide(at, self.state)
            self.assertIsNone(decision.proposed_watts)
            self.state = decision.state

    def decide(self, at, state=None, **changes):
        sample = replace(self.sample, sampled_at_ms=at, **changes)
        return propose_auto_tdp(self.policy, state or self.state, sample, now_ms=at)

    def test_sustained_misses_propose_one_bounded_step(self):
        state = self.state
        for at in (5000, 6000):
            decision = self.decide(at, state, fps=45)
            self.assertIsNone(decision.proposed_watts)
            state = decision.state
        decision = self.decide(7000, state, fps=45)
        self.assertEqual(decision.proposed_watts, 16)
        self.assertFalse(decision.authorizes_action)
        self.assertIsNone(self.decide(8000, decision.state, fps=45).proposed_watts)

    def test_capped_target_probes_down_without_requiring_above_cap_fps(self):
        state = self.state
        for at in (5000, 6000, 7000, 8000, 9000):
            decision = self.decide(at, state)
            state = decision.state
        self.assertEqual(decision.proposed_watts, 14)

    def test_context_or_readback_change_restarts_settling(self):
        for changes in ({"context_key": "new-session"}, {"configured_watts": 16}):
            with self.subTest(changes=changes):
                decision = self.decide(9000, **changes)
                self.assertIsNone(decision.proposed_watts)
                self.assertEqual(decision.state.last_change_ms, 9000)

    def test_missing_guards_or_running_game_never_propose(self):
        for field in ("internal_render_verified", "controller_owned", "thermal_ready", "power_source_ready"):
            with self.subTest(field=field):
                self.assertIsNone(self.decide(9000, **{field: False}).proposed_watts)
                self.assertEqual(self.decide(9000, **{field: False}).state, AutoTdpState())
        for game in (GameState.UNKNOWN, GameState.IDLE):
            self.assertEqual(self.decide(9000, game_state=game).state, AutoTdpState())

    def test_invalid_values_never_become_power_increase(self):
        for fps in (None, 0, -1, float("nan"), float("inf"), True, 10**1000):
            with self.subTest(fps=fps):
                self.assertEqual(self.decide(9000, fps=fps).code, "auto_tdp.fps_unavailable")
        for watts in (None, True, 0, 31, 15.5):
            self.assertEqual(self.decide(9000, configured_watts=watts).code, "auto_tdp.readback_invalid")

    def test_repeated_or_out_of_order_samples_break_streak(self):
        state = self.decide(5000, fps=40).state
        for at in (4999, 5000):
            decision = self.decide(at, state, fps=40)
            self.assertEqual(decision.code, "auto_tdp.sample_repeated")
            self.assertEqual(decision.state.missed_samples, 0)
            self.assertEqual(decision.state.last_sample_ms, 5000)

    def test_stale_or_future_evidence_resets(self):
        for sampled, now in ((0, 9000), (9001, 9000), (-1, 0)):
            decision = propose_auto_tdp(self.policy, self.state, replace(self.sample, sampled_at_ms=sampled), now_ms=now)
            self.assertEqual(decision.code, "auto_tdp.sample_stale")

    def test_bounds_never_exceeded(self):
        for watts, fps, samples in ((30, 20, 3), (7, 60, 5)):
            state = replace(self.state, configured_watts=watts)
            for offset in range(samples):
                decision = self.decide(5000 + offset * 1000, state, configured_watts=watts, fps=fps)
                state = decision.state
            self.assertEqual(decision.code, "auto_tdp.at_bound")
            self.assertIsNone(decision.proposed_watts)

    def test_fluctuating_frames_do_not_accumulate_unrelated_streaks(self):
        state = self.state
        for index in range(20):
            decision = self.decide(5000 + 1000 * index, state, fps=40 if index % 2 else 60)
            self.assertIsNone(decision.proposed_watts)
            state = decision.state

    def test_policy_rejects_invalid_configuration(self):
        for change in ({"minimum_watts": 31}, {"target_fps": float("nan")}, {"target_fps": 10**1000}, {"step_watts": True}, {"deadband_fps": 60}, {"settling_ms": 0}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(self.policy, **change)

    def test_fresh_sample_after_gap_cannot_reuse_old_streak(self):
        for fps, count in ((40, 2), (60, 4)):
            with self.subTest(fps=fps):
                state = self.state
                for offset in range(count):
                    state = self.decide(5000 + offset * 1000, state, fps=fps).state
                decision = self.decide(3_600_000, state, fps=fps)
                self.assertEqual(decision.code, "auto_tdp.sample_gap")
                self.assertIsNone(decision.proposed_watts)
                self.assertEqual(decision.state.missed_samples, 0)
                self.assertEqual(decision.state.stable_samples, 0)
                self.assertEqual(decision.state.last_change_ms, 3_600_000)


if __name__ == "__main__":
    unittest.main()
