"""Non-authorizing player presentation for the future controller Safe Undock chord."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .controller_shortcuts import ControllerShortcutDecision


class ControllerShortcutPresentationState(StrEnum):
    DELIVERY_NOT_CONNECTED = "delivery_not_connected"
    READY_FOR_VERIFIED_INPUT = "ready_for_verified_input"
    INPUT_NOT_VERIFIED = "input_not_verified"
    HOLD_INCOMPLETE = "hold_incomplete"
    CHORD_NOT_MATCHED = "chord_not_matched"
    REVALIDATE_REQUIRED = "revalidate_required"


@dataclass(frozen=True, slots=True)
class ControllerShortcutPresentation:
    state: ControllerShortcutPresentationState
    code: str
    gesture: str = "Xbox/Guide + Y hold (3 seconds)"

    @property
    def authorizes_action(self) -> bool:
        """Presentation never listens for input or authorizes an undock."""
        return False


def present_controller_safe_undock(
    decision: ControllerShortcutDecision | None,
    *,
    delivery_connected: bool,
) -> ControllerShortcutPresentation:
    """Describe only the existing policy outcome without exposing event identity."""

    if not delivery_connected:
        return ControllerShortcutPresentation(
            ControllerShortcutPresentationState.DELIVERY_NOT_CONNECTED,
            "controller_shortcut.delivery_not_connected",
        )
    if decision is None:
        return ControllerShortcutPresentation(
            ControllerShortcutPresentationState.READY_FOR_VERIFIED_INPUT,
            "controller_shortcut.awaiting_verified_input",
        )
    if decision.request is not None:
        return ControllerShortcutPresentation(
            ControllerShortcutPresentationState.REVALIDATE_REQUIRED,
            "controller_shortcut.request_revalidation_required",
        )
    states = {
        "controller_shortcut.input_unverified": ControllerShortcutPresentationState.INPUT_NOT_VERIFIED,
        "controller_shortcut.hold_incomplete": ControllerShortcutPresentationState.HOLD_INCOMPLETE,
        "controller_shortcut.no_exact_match": ControllerShortcutPresentationState.CHORD_NOT_MATCHED,
    }
    return ControllerShortcutPresentation(
        states.get(decision.reason, ControllerShortcutPresentationState.INPUT_NOT_VERIFIED),
        decision.reason,
    )
