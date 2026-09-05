from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.domain.controller_shortcut_presentation import (  # noqa: E402
    ControllerShortcutPresentationState,
    present_controller_safe_undock,
)
from hdm.domain.controller_shortcuts import (  # noqa: E402
    ControllerButton,
    ControllerInputEvidence,
    evaluate_controller_shortcut,
)


def evidence(**changes):
    values = {
        "event_id": "controller-event-0001",
        "occurred_at": "2026-09-01T12:00:00Z",
        "expected_generation": "generation-1",
        "pressed_buttons": frozenset({ControllerButton.GUIDE, ControllerButton.Y}),
        "held_ms": 3_000,
        "input_verified": True,
    }
    values.update(changes)
    return ControllerInputEvidence(**values)


class ControllerShortcutPresentationTests(unittest.TestCase):
    def test_unwired_delivery_is_explicit_not_a_controller_claim(self):
        result = present_controller_safe_undock(None, delivery_connected=False)
        self.assertEqual(ControllerShortcutPresentationState.DELIVERY_NOT_CONNECTED, result.state)
        self.assertFalse(result.authorizes_action)

    def test_connected_policy_waits_for_verified_input(self):
        result = present_controller_safe_undock(None, delivery_connected=True)
        self.assertEqual(ControllerShortcutPresentationState.READY_FOR_VERIFIED_INPUT, result.state)
        self.assertEqual("Xbox/Guide + Y hold (3 seconds)", result.gesture)

    def test_unverified_short_and_nonexact_input_remain_non_authorizing(self):
        for value, state in (
            (evidence(input_verified=False), ControllerShortcutPresentationState.INPUT_NOT_VERIFIED),
            (evidence(held_ms=2_999), ControllerShortcutPresentationState.HOLD_INCOMPLETE),
            (evidence(pressed_buttons=frozenset({ControllerButton.GUIDE})), ControllerShortcutPresentationState.CHORD_NOT_MATCHED),
        ):
            with self.subTest(state=state):
                result = present_controller_safe_undock(
                    evaluate_controller_shortcut(value), delivery_connected=True
                )
                self.assertEqual(state, result.state)
                self.assertFalse(result.authorizes_action)

    def test_matched_chord_requires_later_normal_request_revalidation(self):
        result = present_controller_safe_undock(
            evaluate_controller_shortcut(evidence()), delivery_connected=True
        )
        self.assertEqual(ControllerShortcutPresentationState.REVALIDATE_REQUIRED, result.state)
        self.assertEqual("controller_shortcut.request_revalidation_required", result.code)


if __name__ == "__main__":
    unittest.main()
