from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.control_plane import RequestIntent, RequestSource  # noqa: E402
from regear.domain.logical_actions import (  # noqa: E402
    ActionSurface,
    LogicalAction,
    LogicalActionRequest,
    route_logical_action,
    transition_request_from_logical_action,
)


def request(action: LogicalAction, surface: ActionSurface) -> LogicalActionRequest:
    return LogicalActionRequest(action, surface, "2026-08-31T12:00:00Z", "gen-1")


class LogicalActionRoutingTests(unittest.TestCase):
    def test_decky_and_controller_safe_undock_share_undock_intent(self):
        decky = transition_request_from_logical_action(
            request(LogicalAction.SAFE_UNDOCK, ActionSurface.DECKY_UI), "request-decky"
        )
        controller = transition_request_from_logical_action(
            request(LogicalAction.SAFE_UNDOCK, ActionSurface.CONTROLLER),
            "request-controller",
        )
        self.assertEqual(decky.intent, RequestIntent.UNDOCK)
        self.assertEqual(controller.intent, RequestIntent.UNDOCK)
        self.assertEqual(decky.source, RequestSource.MANUAL)
        self.assertEqual(controller.source, RequestSource.CONTROLLER)

    def test_device_button_uses_the_existing_physical_source(self):
        routed = route_logical_action(
            request(LogicalAction.RETURN_TO_HANDHELD, ActionSurface.DEVICE_BUTTON)
        )
        self.assertEqual(routed.intent, RequestIntent.UNDOCK)
        self.assertEqual(routed.source, RequestSource.PHYSICAL_BUTTON)

    def test_recovery_routes_to_existing_recovery_intent(self):
        routed = route_logical_action(
            request(LogicalAction.RECOVERY, ActionSurface.CONTROLLER)
        )
        self.assertTrue(routed.requestable)
        self.assertEqual(routed.intent, RequestIntent.RECOVER)

    def test_unimplemented_performance_action_never_creates_a_transition(self):
        action = request(
            LogicalAction.CHANGE_PERFORMANCE_PROFILE, ActionSurface.CONTROLLER
        )
        routed = route_logical_action(action)
        self.assertFalse(routed.requestable)
        self.assertEqual(routed.blocker, "action.performance_profile_unimplemented")
        self.assertIsNone(transition_request_from_logical_action(action, "request-1"))

    def test_missing_generation_fails_before_routing(self):
        with self.assertRaisesRegex(ValueError, "generation"):
            LogicalActionRequest(
                LogicalAction.SAFE_UNDOCK,
                ActionSurface.CONTROLLER,
                "2026-08-31T12:00:00Z",
                "",
            )


if __name__ == "__main__":
    unittest.main()
