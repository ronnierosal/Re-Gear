from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.domain.controller_shortcut_bindings import (  # noqa: E402
    DEFAULT_BINDING_REQUESTS,
    ShortcutBindingRequest,
    build_shortcut_binding_set,
    resolve_binding_availability,
)
from hdm.domain.controller_shortcuts import (  # noqa: E402
    ControllerButton,
    ControllerInputEvidence,
    evaluate_controller_shortcut,
)
from hdm.domain.logical_actions import LogicalAction  # noqa: E402


VIEW_Y = frozenset({ControllerButton.VIEW, ControllerButton.Y})
VIEW_X = frozenset({ControllerButton.VIEW, ControllerButton.X})


def request(
    *,
    action: LogicalAction = LogicalAction.SAFE_UNDOCK,
    buttons: frozenset[ControllerButton] = VIEW_Y,
    hold_ms: int = 3_000,
) -> ShortcutBindingRequest:
    return ShortcutBindingRequest(action, buttons, hold_ms)


class ShortcutBindingValidationTests(unittest.TestCase):
    def test_two_distinct_chords_are_accepted_and_evaluate_independently(self):
        bindings = build_shortcut_binding_set(
            (
                request(),
                request(action=LogicalAction.RECOVERY, buttons=VIEW_X),
            )
        )
        self.assertEqual(len(bindings.accepted), 2)
        self.assertEqual(bindings.rejected, ())
        policy = bindings.policy
        self.assertIsNotNone(policy)
        for buttons, action in ((VIEW_Y, LogicalAction.SAFE_UNDOCK), (VIEW_X, LogicalAction.RECOVERY)):
            with self.subTest(action=action):
                decision = evaluate_controller_shortcut(
                    ControllerInputEvidence(
                        True, buttons, 3_000, "2026-09-08T12:00:00Z", "generation-1", "event-00000001"
                    ),
                    policy,
                )
                self.assertTrue(decision.matched)
                self.assertEqual(decision.request.action, action)

    def test_each_unsafe_chord_is_refused_with_its_own_reason(self):
        cases = (
            (request(buttons=frozenset({ControllerButton.VIEW})), "controller_binding.single_button_chord"),
            (request(buttons=frozenset()), "controller_binding.single_button_chord"),
            (
                request(buttons=frozenset({ControllerButton.GUIDE, ControllerButton.Y})),
                "controller_binding.reserved_button",
            ),
            (
                request(
                    buttons=frozenset(
                        {ControllerButton.VIEW, ControllerButton.X, ControllerButton.Y}
                    )
                    | {ControllerButton.GUIDE}
                ),
                "controller_binding.reserved_button",
            ),
            (request(hold_ms=499), "controller_binding.hold_out_of_range"),
            (request(hold_ms=10_001), "controller_binding.hold_out_of_range"),
            (request(hold_ms=0), "controller_binding.hold_out_of_range"),
        )
        for value, code in cases:
            with self.subTest(code=code, buttons=sorted(value.buttons), hold=value.minimum_hold_ms):
                bindings = build_shortcut_binding_set((value,))
                self.assertEqual(bindings.accepted, ())
                self.assertIsNone(bindings.policy)
                self.assertEqual([entry.code for entry in bindings.rejected], [code])

    def test_a_reserved_button_is_refused_before_the_chord_length_rule(self):
        """Guide is refused for owning the button, not for the chord's shape."""
        bindings = build_shortcut_binding_set((request(buttons=frozenset({ControllerButton.GUIDE})),))
        self.assertEqual(
            [entry.code for entry in bindings.rejected], ["controller_binding.reserved_button"]
        )

    def test_a_three_button_chord_of_bindable_buttons_is_accepted(self):
        """Every chord the current button catalog can express stays bindable.

        Minus the reserved names there are only three bindable buttons today, so
        this is also the longest configurable chord that exists.
        """
        chord = frozenset({ControllerButton.VIEW, ControllerButton.X, ControllerButton.Y})
        bindings = build_shortcut_binding_set((request(buttons=chord),))
        self.assertEqual(bindings.rejected, ())
        self.assertEqual([shortcut.buttons for shortcut in bindings.accepted], [chord])

    def test_the_first_of_two_identical_chords_wins_deterministically(self):
        bindings = build_shortcut_binding_set(
            (
                request(action=LogicalAction.SAFE_UNDOCK),
                request(action=LogicalAction.RECOVERY),
            )
        )
        self.assertEqual(len(bindings.accepted), 1)
        self.assertEqual(bindings.accepted[0].action, LogicalAction.SAFE_UNDOCK)
        self.assertEqual(
            [entry.code for entry in bindings.rejected], ["controller_binding.duplicate_chord"]
        )
        self.assertEqual(bindings.rejected[0].request.action, LogicalAction.RECOVERY)

    def test_one_bad_chord_never_discards_the_rest_of_the_configuration(self):
        bindings = build_shortcut_binding_set(
            (
                request(buttons=frozenset({ControllerButton.VIEW})),
                request(buttons=VIEW_Y),
                request(action=LogicalAction.RECOVERY, buttons=frozenset({ControllerButton.GUIDE, ControllerButton.X})),
                request(action=LogicalAction.RETURN_TO_HANDHELD, buttons=VIEW_X),
            )
        )
        self.assertEqual(
            [shortcut.buttons for shortcut in bindings.accepted], [VIEW_Y, VIEW_X]
        )
        self.assertEqual(
            [entry.code for entry in bindings.rejected],
            ["controller_binding.single_button_chord", "controller_binding.reserved_button"],
        )

    def test_an_empty_configuration_yields_no_policy_rather_than_a_default(self):
        bindings = build_shortcut_binding_set(())
        self.assertEqual(bindings.accepted, ())
        self.assertIsNone(bindings.policy)

    def test_the_shipped_default_is_exactly_the_delivered_view_y_chord(self):
        bindings = build_shortcut_binding_set(DEFAULT_BINDING_REQUESTS)
        self.assertEqual(bindings.rejected, ())
        self.assertEqual(len(bindings.accepted), 1)
        self.assertEqual(bindings.accepted[0].buttons, VIEW_Y)
        self.assertEqual(bindings.accepted[0].action, LogicalAction.SAFE_UNDOCK)
        self.assertEqual(bindings.accepted[0].minimum_hold_ms, 3_000)


class ShortcutBindingAvailabilityTests(unittest.TestCase):
    def test_a_well_formed_chord_for_an_undeliverable_action_is_not_available(self):
        bindings = build_shortcut_binding_set(
            (
                request(),
                request(action=LogicalAction.CHANGE_PERFORMANCE_PROFILE, buttons=VIEW_X),
            )
        )
        statuses = resolve_binding_availability(
            bindings, deliverable_actions=(LogicalAction.SAFE_UNDOCK,)
        )
        self.assertEqual([status.available for status in statuses], [True, False])
        self.assertEqual(
            [status.code for status in statuses],
            ["controller_binding.available", "controller_binding.action_not_deliverable"],
        )

    def test_availability_never_invents_delivery_from_an_empty_runtime(self):
        bindings = build_shortcut_binding_set(DEFAULT_BINDING_REQUESTS)
        statuses = resolve_binding_availability(bindings, deliverable_actions=())
        self.assertEqual([status.available for status in statuses], [False])
        self.assertEqual(statuses[0].code, "controller_binding.action_not_deliverable")

    def test_refused_chords_are_absent_from_availability_entirely(self):
        bindings = build_shortcut_binding_set((request(buttons=frozenset({ControllerButton.VIEW})),))
        self.assertEqual(
            resolve_binding_availability(
                bindings, deliverable_actions=(LogicalAction.SAFE_UNDOCK,)
            ),
            (),
        )


if __name__ == "__main__":
    unittest.main()
