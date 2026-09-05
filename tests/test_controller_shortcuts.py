from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.domain.controller_shortcuts import (  # noqa: E402
    ControllerButton,
    ControllerInputEvidence,
    evaluate_controller_shortcut,
)
from hdm.domain.control_plane import RequestIntent, RequestSource  # noqa: E402
from hdm.domain.logical_actions import (  # noqa: E402
    LogicalAction,
    transition_request_from_logical_action,
)


def evidence(
    *,
    verified: bool = True,
    buttons: frozenset[ControllerButton] | None = None,
    held_ms: int = 3_000,
) -> ControllerInputEvidence:
    return ControllerInputEvidence(
        verified,
        buttons or frozenset({ControllerButton.GUIDE, ControllerButton.Y}),
        held_ms,
        "2026-08-31T12:00:00Z",
        "generation-1",
        "controller-event-0001",
    )


class ControllerShortcutTests(unittest.TestCase):
    def test_verified_guide_y_hold_emits_the_existing_safe_undock_action(self):
        decision = evaluate_controller_shortcut(evidence())
        self.assertTrue(decision.matched)
        self.assertEqual(decision.request.action, LogicalAction.SAFE_UNDOCK)
        request = transition_request_from_logical_action(decision.request, "request-1")
        self.assertEqual(request.intent, RequestIntent.UNDOCK)
        self.assertEqual(request.source, RequestSource.CONTROLLER)

    def test_unverified_short_or_non_exact_chords_never_emit_a_request(self):
        cases = (
            (evidence(verified=False), "controller_shortcut.input_unverified"),
            (evidence(held_ms=1_200), "controller_shortcut.hold_incomplete"),
            (evidence(held_ms=2_999), "controller_shortcut.hold_incomplete"),
            (evidence(buttons=frozenset({ControllerButton.GUIDE})), "controller_shortcut.no_exact_match"),
        )
        for value, reason in cases:
            with self.subTest(reason=reason):
                decision = evaluate_controller_shortcut(value)
                self.assertFalse(decision.matched)
                self.assertEqual(decision.reason, reason)

    def test_invalid_evidence_and_ambiguous_policy_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "evidence"):
            ControllerInputEvidence(True, frozenset(), -1, "", "", "")


if __name__ == "__main__":
    unittest.main()
