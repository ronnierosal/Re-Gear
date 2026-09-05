"""Pure controller-chord policy that emits existing logical HDM requests only."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .logical_actions import ActionSurface, LogicalAction, LogicalActionRequest


class ControllerButton(StrEnum):
    GUIDE = "guide"
    Y = "y"


DEFAULT_SAFE_UNDOCK_HOLD_MS = 3_000
EVENT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{8,96}$")


@dataclass(frozen=True, slots=True)
class ControllerShortcut:
    action: LogicalAction
    buttons: frozenset[ControllerButton]
    minimum_hold_ms: int = DEFAULT_SAFE_UNDOCK_HOLD_MS

    def __post_init__(self) -> None:
        if not self.buttons or self.minimum_hold_ms < 500 or self.minimum_hold_ms > 10_000:
            raise ValueError("controller shortcut configuration is invalid")


@dataclass(frozen=True, slots=True)
class ControllerShortcutPolicy:
    shortcuts: tuple[ControllerShortcut, ...]

    def __post_init__(self) -> None:
        chords = tuple(shortcut.buttons for shortcut in self.shortcuts)
        if len(chords) != len(set(chords)):
            raise ValueError("controller shortcut chords must be unique")


@dataclass(frozen=True, slots=True)
class ControllerInputEvidence:
    """One delivery-provided input event; no device identity crosses this boundary."""

    input_verified: bool
    pressed_buttons: frozenset[ControllerButton]
    held_ms: int
    occurred_at: str
    expected_generation: str
    event_id: str

    def __post_init__(self) -> None:
        if (
            self.held_ms < 0
            or not self.occurred_at
            or not self.expected_generation
            or not EVENT_ID_RE.fullmatch(self.event_id)
        ):
            raise ValueError("controller shortcut evidence is invalid")


@dataclass(frozen=True, slots=True)
class ControllerShortcutDecision:
    request: LogicalActionRequest | None
    reason: str

    @property
    def matched(self) -> bool:
        return self.request is not None


DEFAULT_CONTROLLER_SHORTCUTS = ControllerShortcutPolicy(
    (
        ControllerShortcut(
            LogicalAction.SAFE_UNDOCK,
            frozenset({ControllerButton.GUIDE, ControllerButton.Y}),
        ),
    )
)


def evaluate_controller_shortcut(
    evidence: ControllerInputEvidence,
    policy: ControllerShortcutPolicy = DEFAULT_CONTROLLER_SHORTCUTS,
) -> ControllerShortcutDecision:
    """Match only verified, exact held chords and emit the ordinary logical action.

    A delivery adapter must independently debounce a physical event and confirm
    its source before providing evidence. This policy has no input listener,
    controller binding, transition execution, or hardware authority.
    """
    if not evidence.input_verified:
        return ControllerShortcutDecision(None, "controller_shortcut.input_unverified")
    matching = tuple(
        shortcut
        for shortcut in policy.shortcuts
        if shortcut.buttons == evidence.pressed_buttons
    )
    if len(matching) != 1:
        return ControllerShortcutDecision(None, "controller_shortcut.no_exact_match")
    shortcut = matching[0]
    if evidence.held_ms < shortcut.minimum_hold_ms:
        return ControllerShortcutDecision(None, "controller_shortcut.hold_incomplete")
    return ControllerShortcutDecision(
        LogicalActionRequest(
            shortcut.action,
            ActionSurface.CONTROLLER,
            evidence.occurred_at,
            evidence.expected_generation,
        ),
        "controller_shortcut.matched",
    )
