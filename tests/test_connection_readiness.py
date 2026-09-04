from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.application.connection_readiness import (  # noqa: E402
    ConnectionReadinessLifecycle,
    ConnectionReadinessObservation,
    ConnectionReadinessStage,
    poll_after_ms,
)
from hdm.domain.models import GameState  # noqa: E402


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def sample(index: int, **changes) -> ConnectionReadinessObservation:
    base = ConnectionReadinessObservation(
        sample_id=f"sample-{index}",
        transport_identity="transport-a",
        transport_present=True,
        g1_identity="g1-a",
        pci_complete=True,
        driver_ready=True,
        link_up=True,
        hdmi_ready=True,
        audio_ready=True,
        session_ready=True,
        game_state=GameState.IDLE,
    )
    return replace(base, **changes)


class ConnectionReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.lifecycle = ConnectionReadinessLifecycle(self.clock)

    def test_adaptive_polling_covers_delayed_enumeration(self):
        self.assertEqual(poll_after_ms(0), 500)
        self.assertEqual(poll_after_ms(9.999), 500)
        self.assertEqual(poll_after_ms(10), 1_000)
        self.assertEqual(poll_after_ms(30), 5_000)
        self.assertEqual(poll_after_ms(77), 5_000)
        self.assertEqual(poll_after_ms(0, active=False), 5_000)

        waiting = self.lifecycle.update(
            sample(0, g1_identity="", pci_complete=False)
        )
        self.clock.now = 77
        waiting = self.lifecycle.update(
            sample(1, g1_identity="", pci_complete=False)
        )
        self.assertEqual(waiting.stage, ConnectionReadinessStage.WAITING_FOR_PCI)
        self.assertEqual(waiting.poll_after_ms, 5_000)
        results = [self.lifecycle.update(sample(index)) for index in range(2, 6)]
        self.assertEqual(results[-1].stage, ConnectionReadinessStage.READY_IDLE)

    def test_per_layer_stages_and_independent_hdmi_audio_quorums(self):
        cases = (
            ({"g1_identity": "", "pci_complete": False}, ConnectionReadinessStage.TRANSPORT_DETECTED),
            ({"driver_ready": False}, ConnectionReadinessStage.WAITING_FOR_DRIVER),
            ({"link_up": False}, ConnectionReadinessStage.WAITING_FOR_LINK),
            ({"hdmi_ready": False}, ConnectionReadinessStage.WAITING_FOR_HDMI),
            ({"audio_ready": False}, ConnectionReadinessStage.WAITING_FOR_AUDIO),
            ({"session_ready": False}, ConnectionReadinessStage.WAITING_FOR_SESSION),
        )
        for index, (changes, expected) in enumerate(cases):
            lifecycle = ConnectionReadinessLifecycle(self.clock)
            self.assertEqual(lifecycle.update(sample(index, **changes)).stage, expected)

        lifecycle = ConnectionReadinessLifecycle(self.clock)
        lifecycle.update(sample(20, audio_ready=False))
        lifecycle.update(sample(21, audio_ready=False))
        lifecycle.update(sample(22))
        result = lifecycle.update(sample(23))
        self.assertEqual(result.stage, ConnectionReadinessStage.READY_IDLE)
        self.assertEqual(result.audio_samples, 2)

        audio_first = ConnectionReadinessLifecycle(self.clock)
        audio_first.update(sample(30, hdmi_ready=False))
        audio_first.update(sample(31, hdmi_ready=False))
        audio_first.update(sample(32))
        result = audio_first.update(sample(33))
        self.assertEqual(result.stage, ConnectionReadinessStage.READY_IDLE)
        self.assertEqual(result.hdmi_samples, 2)

    def test_duplicate_samples_do_not_advance_stability(self):
        same = sample(1)
        for _ in range(10):
            result = self.lifecycle.update(same)
        self.assertEqual(result.stage, ConnectionReadinessStage.STABILIZING)
        self.assertEqual(result.topology_samples, 1)

    def test_identity_change_invalidates_accumulated_stability(self):
        for index in range(3):
            self.lifecycle.update(sample(index))
        changed = self.lifecycle.update(sample(3, g1_identity="g1-b"))
        self.assertEqual(changed.topology_samples, 1)
        self.assertEqual(changed.stage, ConnectionReadinessStage.STABILIZING)

        transport = self.lifecycle.update(sample(4, transport_identity="transport-b"))
        self.assertEqual(transport.topology_samples, 1)
        self.assertEqual(transport.window_age_ms, 0)

    def test_game_defers_action_without_discarding_readiness(self):
        for index in range(4):
            result = self.lifecycle.update(sample(index, game_state=GameState.RUNNING))
        self.assertEqual(result.stage, ConnectionReadinessStage.GAME_RUNNING)
        ready = self.lifecycle.update(sample(4))
        self.assertEqual(ready.stage, ConnectionReadinessStage.READY_IDLE)

    def test_transport_drop_before_exact_pci_is_link_training_failure(self):
        self.lifecycle.update(sample(0, g1_identity="", pci_complete=False))
        failed = self.lifecycle.update(
            ConnectionReadinessObservation(sample_id="drop")
        )
        self.assertEqual(failed.stage, ConnectionReadinessStage.LINK_TRAINING_FAILED)

        blocked = self.lifecycle.update(sample(1, transport_identity="transport-b"))
        self.assertEqual(blocked.stage, ConnectionReadinessStage.ACTION_REQUIRED)
        self.assertEqual(blocked.code, "connection.verified_absence_required")

        absent = self.lifecycle.update(
            ConnectionReadinessObservation(
                sample_id="absent", transport_absent_verified=True
            )
        )
        self.assertEqual(absent.stage, ConnectionReadinessStage.DISCONNECTED)
        restarted = self.lifecycle.update(sample(2, transport_identity="transport-b"))
        self.assertEqual(restarted.stage, ConnectionReadinessStage.STABILIZING)

    def test_absence_without_prior_transport_is_not_link_failure(self):
        unknown = self.lifecycle.update(ConnectionReadinessObservation(sample_id="unknown"))
        self.assertEqual(unknown.stage, ConnectionReadinessStage.DISCONNECTED)

    def test_unknown_transport_invalidates_ready_and_requires_fresh_quorum(self):
        for index in range(4):
            self.lifecycle.update(sample(index))
        unknown = self.lifecycle.update(ConnectionReadinessObservation(sample_id="unknown"))
        self.assertEqual(unknown.stage, ConnectionReadinessStage.ACTION_REQUIRED)
        self.assertEqual(unknown.code, "connection.transport_unknown")
        self.assertEqual(unknown.topology_samples, 0)
        for index in range(4, 7):
            self.assertEqual(self.lifecycle.update(sample(index)).stage,
                             ConnectionReadinessStage.STABILIZING)
        self.assertEqual(self.lifecycle.update(sample(7)).stage,
                         ConnectionReadinessStage.READY_IDLE)

    def test_established_readiness_survives_deadline_but_not_fresh_link_failure(self):
        for index in range(4):
            self.lifecycle.update(sample(index))
        self.clock.now = 121
        self.assertEqual(self.lifecycle.update(sample(4)).stage,
                         ConnectionReadinessStage.READY_IDLE)
        self.assertEqual(self.lifecycle.update(sample(5, link_up=False)).stage,
                         ConnectionReadinessStage.WAITING_FOR_LINK)
        self.assertEqual(self.lifecycle.update(sample(6)).stage,
                         ConnectionReadinessStage.STABILIZING)

    def test_game_exit_after_deadline_rechecks_idle_without_timing_out(self):
        for index in range(4):
            self.lifecycle.update(sample(index, game_state=GameState.RUNNING))
        self.clock.now = 121
        self.assertEqual(self.lifecycle.update(sample(4, game_state=GameState.UNKNOWN)).stage,
                         ConnectionReadinessStage.ACTION_REQUIRED)
        self.assertEqual(self.lifecycle.update(sample(5)).stage,
                         ConnectionReadinessStage.READY_IDLE)

    def test_verified_absence_restores_initial_deadline(self):
        for index in range(4):
            self.lifecycle.update(sample(index))
        self.lifecycle.update(ConnectionReadinessObservation(
            sample_id="absent", transport_absent_verified=True))
        self.clock.now = 200
        self.lifecycle.update(sample(5, g1_identity="", pci_complete=False))
        self.clock.now = 320
        self.assertEqual(self.lifecycle.update(sample(6)).stage,
                         ConnectionReadinessStage.TIMED_OUT)

    def test_window_times_out_at_120_seconds(self):
        self.lifecycle.update(sample(0, g1_identity="", pci_complete=False))
        self.clock.now = 119.9
        waiting = self.lifecycle.update(sample(1, g1_identity="", pci_complete=False))
        self.assertEqual(waiting.stage, ConnectionReadinessStage.WAITING_FOR_PCI)
        self.clock.now = 120
        timed_out = self.lifecycle.update(sample(2))
        self.assertEqual(timed_out.stage, ConnectionReadinessStage.TIMED_OUT)
        self.assertEqual(timed_out.poll_after_ms, 5_000)

    def test_unknown_game_fails_closed_after_other_layers_are_ready(self):
        result = self.lifecycle.update(sample(0, game_state=GameState.UNKNOWN))
        self.assertEqual(result.stage, ConnectionReadinessStage.ACTION_REQUIRED)
        self.assertEqual(result.code, "connection.game_state_unknown")


if __name__ == "__main__":
    unittest.main()
