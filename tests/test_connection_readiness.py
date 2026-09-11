from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.connection_readiness import (  # noqa: E402
    WINDOW_TIMEOUT_SECONDS,
    ConnectionReadinessLifecycle,
    ConnectionReadinessObservation,
    ConnectionReadinessStage,
    poll_after_ms,
)
from regear.domain.models import GameState  # noqa: E402


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

    def begin_late_enumeration(self):
        self.lifecycle.update(sample(0, g1_identity="", pci_complete=False))
        self.clock.now = 120
        self.assertEqual(self.lifecycle.update(
            sample(1, g1_identity="", pci_complete=False)).stage,
            ConnectionReadinessStage.TIMED_OUT)
        self.clock.now = 169
        return self.lifecycle.update(sample(2))

    def test_late_exact_enumeration_starts_fresh_bounded_settling(self):
        recovered = self.begin_late_enumeration()
        self.assertEqual(recovered.stage, ConnectionReadinessStage.STABILIZING)
        self.assertEqual(recovered.code, "connection.late_enumeration_detected")
        self.assertEqual(recovered.window_age_ms, 0)
        self.assertEqual(recovered.topology_samples, 0)
        # Neither the triggering sample nor repeated samples count as quorum.
        self.assertEqual(self.lifecycle.update(sample(2)).topology_samples, 0)
        for index in range(3, 6):
            self.assertEqual(self.lifecycle.update(sample(index)).stage,
                             ConnectionReadinessStage.STABILIZING)
        self.assertEqual(self.lifecycle.update(sample(6)).stage,
                         ConnectionReadinessStage.READY_IDLE)

    def test_late_enumeration_retains_all_readiness_guards(self):
        cases = (
            ({"driver_ready": False}, ConnectionReadinessStage.WAITING_FOR_DRIVER),
            ({"link_up": False}, ConnectionReadinessStage.WAITING_FOR_LINK),
            # An absent display no longer reads as "still coming up" once the
            # eGPU side is stable, but it still must not reach READY_IDLE.
            ({"hdmi_ready": False}, ConnectionReadinessStage.READY_DISPLAY_PENDING),
            ({"audio_ready": False}, ConnectionReadinessStage.WAITING_FOR_AUDIO),
            ({"session_ready": False}, ConnectionReadinessStage.WAITING_FOR_SESSION),
            ({"game_state": GameState.RUNNING}, ConnectionReadinessStage.GAME_RUNNING),
            ({"game_state": GameState.UNKNOWN}, ConnectionReadinessStage.ACTION_REQUIRED),
        )
        for changes, expected in cases:
            with self.subTest(changes=changes):
                self.setUp()
                self.begin_late_enumeration()
                for index in range(3, 8):
                    result = self.lifecycle.update(sample(index, **changes))
                self.assertEqual(result.stage, expected)
                # The guard this table exists to protect: no missing fact may
                # ever produce the one stage that authorizes a transition.
                self.assertNotEqual(result.stage, ConnectionReadinessStage.READY_IDLE)

    def test_late_recheck_cannot_restart_repeatedly_on_same_attachment(self):
        self.begin_late_enumeration()
        self.clock.now = 289
        for index in range(3, 8):
            self.assertEqual(self.lifecycle.update(sample(index)).stage,
                             ConnectionReadinessStage.TIMED_OUT)

    def test_timeout_without_exact_identity_does_not_restart(self):
        self.lifecycle.update(sample(0, g1_identity="", pci_complete=False))
        for index, seconds in enumerate((120, 169, 300), start=1):
            self.clock.now = seconds
            result = self.lifecycle.update(sample(index, g1_identity="", pci_complete=False))
            self.assertEqual(result.stage, ConnectionReadinessStage.TIMED_OUT)
            self.assertEqual(result.window_age_ms, seconds * 1000)

    def test_late_readiness_preserves_one_shot_and_portable_suppression(self):
        from tests.test_automatic_dock import current
        from regear.application.automatic_dock import AutomaticDockCoordinator
        self.begin_late_enumeration()
        for index in range(3, 7):
            ready = self.lifecycle.update(sample(index))
        coordinator = AutomaticDockCoordinator()
        observed = current("connected-internal.json")
        self.assertTrue(coordinator.update(enabled=True, readiness=ready,
                                           current=observed).should_switch)
        self.assertFalse(coordinator.update(enabled=True, readiness=ready,
                                            current=observed).should_switch)
        suppressed = AutomaticDockCoordinator()
        suppressed.suppress_current_attachment_after_portable_return()
        self.assertFalse(suppressed.update(enabled=True, readiness=ready,
                                           current=observed).should_switch)

    def test_unknown_game_fails_closed_after_other_layers_are_ready(self):
        result = self.lifecycle.update(sample(0, game_state=GameState.UNKNOWN))
        self.assertEqual(result.stage, ConnectionReadinessStage.ACTION_REQUIRED)
        self.assertEqual(result.code, "connection.game_state_unknown")


if __name__ == "__main__":
    unittest.main()


class DisplayPendingTests(unittest.TestCase):
    """A television that is merely switched off must not end the eGPU lifecycle.

    Absent HDMI used to park the stage on ``WAITING_FOR_HDMI`` and, because the
    deadline latch also required HDMI, expire the window into ``TIMED_OUT``.
    ``AutomaticDockCoordinator`` only offers a transition at ``READY_IDLE`` and
    treats ``TIMED_OUT`` as action required, so the automatic switch was never
    offered at all. See issue #28.
    """

    def setUp(self) -> None:
        self.clock = Clock()
        self.lifecycle = ConnectionReadinessLifecycle(self.clock)

    def reach_display_pending(self) -> ConnectionReadinessStage:
        for index in range(6):
            status = self.lifecycle.update(sample(index, hdmi_ready=False, audio_ready=False))
        return status

    def test_an_egpu_that_is_up_with_the_television_off_is_ready_and_pending(self):
        status = self.reach_display_pending()
        self.assertEqual(status.stage, ConnectionReadinessStage.READY_DISPLAY_PENDING)
        self.assertEqual(status.code, "connection.ready_display_pending")

    def test_an_absent_display_never_authorizes_a_transition(self):
        """The safety property. READY_IDLE is the only stage that permits one."""
        for index in range(40):
            status = self.lifecycle.update(sample(index, hdmi_ready=False, audio_ready=False))
            self.assertNotEqual(status.stage, ConnectionReadinessStage.READY_IDLE)

    def test_the_window_no_longer_expires_because_a_television_is_off(self):
        """The bug. Before, the deadline latch required HDMI, so this timed out."""
        self.reach_display_pending()
        self.clock.now = WINDOW_TIMEOUT_SECONDS * 3
        status = self.lifecycle.update(sample(99, hdmi_ready=False, audio_ready=False))
        self.assertNotEqual(status.stage, ConnectionReadinessStage.TIMED_OUT)
        self.assertEqual(status.stage, ConnectionReadinessStage.READY_DISPLAY_PENDING)

    def test_turning_the_television_on_reaches_ready_with_no_further_action(self):
        """What makes the switch automatic: the same loop simply proceeds."""
        self.reach_display_pending()
        for index in range(100, 104):
            status = self.lifecycle.update(sample(index))
        self.assertEqual(status.stage, ConnectionReadinessStage.READY_IDLE)

    def test_it_still_reaches_ready_after_the_deadline_has_passed(self):
        """A player may leave the television off for longer than the window."""
        self.reach_display_pending()
        self.clock.now = WINDOW_TIMEOUT_SECONDS * 5
        for index in range(200, 204):
            status = self.lifecycle.update(sample(index))
        self.assertEqual(status.stage, ConnectionReadinessStage.READY_IDLE)

    def test_every_condition_of_the_new_stage_is_load_bearing(self):
        """Mutation coverage: drop one requirement at a time and it must not fire.

        Written because three guards of mine passed against broken code today.
        Each case keeps HDMI absent and removes exactly one other requirement,
        so a guard that stopped checking that requirement fails here.
        """
        cases = (
            # Topology quorum not yet met: this is genuinely "still coming up".
            ("topology_not_stable", 1, {}, ConnectionReadinessStage.WAITING_FOR_HDMI),
            # The next three keep the ORIGINAL precedence, which checked HDMI
            # before session and game state. The new branch declines to fire
            # because its extra requirement is missing, so the chain falls
            # through to the pre-existing HDMI wait. What matters for safety is
            # the assertion below: none of them reach the pending-display
            # stage, so none of them can be mistaken for "ready when the TV
            # arrives" while something else is also wrong.
            ("session_absent", 6, {"session_ready": False},
             ConnectionReadinessStage.WAITING_FOR_HDMI),
            ("game_running", 6, {"game_state": GameState.RUNNING},
             ConnectionReadinessStage.WAITING_FOR_HDMI),
            ("game_unknown", 6, {"game_state": GameState.UNKNOWN},
             ConnectionReadinessStage.WAITING_FOR_HDMI),
            # The eGPU itself absent is not a display question at all.
            ("driver_absent", 6, {"driver_ready": False},
             ConnectionReadinessStage.WAITING_FOR_DRIVER),
            ("link_down", 6, {"link_up": False},
             ConnectionReadinessStage.WAITING_FOR_LINK),
        )
        for name, samples, changes, expected in cases:
            with self.subTest(case=name):
                self.setUp()
                for index in range(samples):
                    status = self.lifecycle.update(
                        sample(index, hdmi_ready=False, audio_ready=False, **changes)
                    )
                self.assertEqual(status.stage, expected)
                self.assertNotEqual(status.stage, ConnectionReadinessStage.READY_DISPLAY_PENDING)

    def test_audio_alone_pending_is_still_the_audio_wait_not_display_pending(self):
        """HDMI observed but audio not yet settled is a different answer."""
        for index in range(6):
            status = self.lifecycle.update(sample(index, audio_ready=False))
        self.assertEqual(status.stage, ConnectionReadinessStage.WAITING_FOR_AUDIO)
