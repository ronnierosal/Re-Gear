from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.control_plane import RequestSource  # noqa: E402
from regear.domain.deferred_dock import (  # noqa: E402
    DeferredDockState,
    cancel_deferred_dock_intent,
    create_deferred_dock_intent,
    evaluate_deferred_dock_intent,
)
from regear.domain.models import GameState  # noqa: E402


class DeferredDockIntentTests(unittest.TestCase):
    def create(self):
        return create_deferred_dock_intent(
            intent_id="player-dock-1",
            source=RequestSource.MANUAL,
            attachment_binding="opaque-attach-1",
            game_state=GameState.RUNNING,
            now_monotonic_ms=10_000,
            ttl_ms=60_000,
        )

    def test_running_game_records_a_bounded_player_intent(self):
        result = self.create()

        self.assertEqual(result.state, DeferredDockState.DEFERRED)
        self.assertEqual(result.code, "dock_intent.game_running")
        self.assertIsNotNone(result.intent)
        self.assertIsNone(result.handoff)

    def test_cancellation_discards_intent_without_a_handoff(self):
        result = cancel_deferred_dock_intent(self.create().intent)

        self.assertEqual(result.state, DeferredDockState.CANCELLED)
        self.assertIsNone(result.intent)
        self.assertIsNone(result.handoff)

    def test_expiry_binding_change_and_uncertain_game_state_fail_closed(self):
        intent = self.create().intent
        for values, state, code in (
            (
                {"now_monotonic_ms": 70_000},
                DeferredDockState.EXPIRED,
                "dock_intent.expired",
            ),
            (
                {"attachment_binding": "opaque-attach-2"},
                DeferredDockState.INVALIDATED,
                "dock_intent.attachment_changed",
            ),
            (
                {"game_state": GameState.UNKNOWN},
                DeferredDockState.INVALIDATED,
                "dock_intent.game_state_unknown",
            ),
        ):
            with self.subTest(code=code):
                result = evaluate_deferred_dock_intent(
                    intent,
                    attachment_binding=values.get("attachment_binding", intent.attachment_binding),
                    game_state=values.get("game_state", GameState.RUNNING),
                    observed_generation="fresh-generation",
                    now_monotonic_ms=values.get("now_monotonic_ms", 10_001),
                )
                self.assertEqual(result.state, state)
                self.assertEqual(result.code, code)
                self.assertIsNone(result.handoff)

    def test_idle_game_close_returns_fresh_non_authorizing_handoff(self):
        intent = self.create().intent

        result = evaluate_deferred_dock_intent(
            intent,
            attachment_binding=intent.attachment_binding,
            game_state=GameState.IDLE,
            observed_generation="fresh-idle-generation",
            now_monotonic_ms=10_001,
        )

        self.assertEqual(result.state, DeferredDockState.ELIGIBLE)
        self.assertEqual(result.code, "dock_intent.game_closed")
        self.assertIsNone(result.intent)
        self.assertEqual(result.handoff.observed_generation, "fresh-idle-generation")

    def test_unknown_or_non_running_request_never_creates_intent(self):
        for game_state, code in (
            (GameState.UNKNOWN, "dock_intent.game_state_unknown"),
            (GameState.IDLE, "dock_intent.game_not_running"),
        ):
            with self.subTest(game_state=game_state):
                result = create_deferred_dock_intent(
                    intent_id="player-dock-1",
                    source=RequestSource.MANUAL,
                    attachment_binding="opaque-attach-1",
                    game_state=game_state,
                    now_monotonic_ms=10_000,
                    ttl_ms=60_000,
                )
                self.assertEqual(result.state, DeferredDockState.REJECTED)
                self.assertEqual(result.code, code)
                self.assertIsNone(result.intent)

    def test_automatic_source_never_becomes_deferred_player_intent(self):
        result = create_deferred_dock_intent(
            intent_id="automatic-dock-1",
            source=RequestSource.AUTOMATIC,
            attachment_binding="opaque-attach-1",
            game_state=GameState.RUNNING,
            now_monotonic_ms=10_000,
            ttl_ms=60_000,
        )

        self.assertEqual(result.state, DeferredDockState.REJECTED)
        self.assertEqual(result.code, "dock_intent.request_invalid")
        self.assertIsNone(result.intent)


if __name__ == "__main__":
    unittest.main()
