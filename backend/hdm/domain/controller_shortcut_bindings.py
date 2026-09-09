"""Pure validation for player-configurable controller shortcut chords.

The existing :mod:`controller_shortcuts` policy is already generic over chords,
but nothing validated a set a *player* could change, and the live frontend
listener hard-coded one chord. This module owns the rules a configured set must
satisfy before an adapter binds it.

Two properties are kept apart on purpose. A binding is *well formed* when its
chord is safe to watch for; it is *deliverable* when some runtime can actually
perform its action. A chord may be perfectly well formed and still have nothing
able to act on it, and presenting that difference honestly is the point: a
shortcut that silently does nothing is worse than one shown as unavailable.

Player-supplied configuration is rejected per binding rather than by raising, so
a single bad chord cannot discard a whole configuration and the caller can
explain each refusal. This module has no input listener, no persistence, no
device identity, and no transition authority.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .controller_shortcuts import (
    DEFAULT_SAFE_UNDOCK_HOLD_MS,
    ControllerButton,
    ControllerShortcut,
    ControllerShortcutPolicy,
)
from .logical_actions import LogicalAction

#: Buttons Steam owns natively. Our listener is non-exclusive and cannot
#: suppress the platform's own handling, so binding one of these would race
#: Steam's menu rather than replace it. Compare the Raikiri II note against
#: emitting a duplicate menu when Steam already handles a button.
RESERVED_BUTTONS = frozenset({ControllerButton.GUIDE})

#: A single button fires during ordinary play, so a chord needs at least two.
#: There is deliberately no upper bound: with today's button names, minus the
#: reserved ones, no configuration can exceed three buttons anyway, and an
#: unreachable rule is worse than none. Add one with a test that runs when the
#: button catalog grows.
MINIMUM_CHORD_BUTTONS = 2

MINIMUM_HOLD_MS = 500
MAXIMUM_HOLD_MS = 10_000


@dataclass(frozen=True, slots=True)
class ShortcutBindingRequest:
    """One chord a player asked to bind, before any validation."""

    action: LogicalAction
    buttons: frozenset[ControllerButton]
    minimum_hold_ms: int = DEFAULT_SAFE_UNDOCK_HOLD_MS


@dataclass(frozen=True, slots=True)
class RejectedBinding:
    request: ShortcutBindingRequest
    code: str


@dataclass(frozen=True, slots=True)
class ShortcutBindingSet:
    """Accepted chords plus the exact reason each refused chord was refused."""

    accepted: tuple[ControllerShortcut, ...]
    rejected: tuple[RejectedBinding, ...]

    @property
    def policy(self) -> ControllerShortcutPolicy | None:
        """The evaluable policy, or None when nothing survived validation."""
        if not self.accepted:
            return None
        return ControllerShortcutPolicy(self.accepted)


@dataclass(frozen=True, slots=True)
class ShortcutBindingStatus:
    shortcut: ControllerShortcut
    available: bool
    code: str


def build_shortcut_binding_set(
    requests: Sequence[ShortcutBindingRequest],
) -> ShortcutBindingSet:
    """Validate configured chords in order, refusing individually with a reason.

    Order is significant only for duplicates: the first chord wins and any later
    identical chord is refused, so the outcome is deterministic instead of
    depending on which of two ambiguous bindings happened to be evaluated first.
    """
    accepted: list[ControllerShortcut] = []
    rejected: list[RejectedBinding] = []
    seen: set[frozenset[ControllerButton]] = set()
    for request in requests:
        code = _refusal_code(request, seen)
        if code:
            rejected.append(RejectedBinding(request, code))
            continue
        seen.add(request.buttons)
        accepted.append(
            ControllerShortcut(request.action, request.buttons, request.minimum_hold_ms)
        )
    return ShortcutBindingSet(tuple(accepted), tuple(rejected))


def _refusal_code(
    request: ShortcutBindingRequest, seen: set[frozenset[ControllerButton]]
) -> str:
    if request.buttons & RESERVED_BUTTONS:
        return "controller_binding.reserved_button"
    if len(request.buttons) < MINIMUM_CHORD_BUTTONS:
        return "controller_binding.single_button_chord"
    if request.buttons in seen:
        return "controller_binding.duplicate_chord"
    if not MINIMUM_HOLD_MS <= request.minimum_hold_ms <= MAXIMUM_HOLD_MS:
        return "controller_binding.hold_out_of_range"
    return ""


def resolve_binding_availability(
    bindings: ShortcutBindingSet,
    *,
    deliverable_actions: Iterable[LogicalAction],
) -> tuple[ShortcutBindingStatus, ...]:
    """Report which accepted chords a runtime can currently act on.

    ``deliverable_actions`` is supplied by the caller from what its runtime
    genuinely wires today. It is deliberately not inferred from the logical
    action vocabulary: an action existing in the enum, or even routing to an
    intent, does not establish that anything performs it on this surface.
    """
    deliverable = frozenset(deliverable_actions)
    return tuple(
        ShortcutBindingStatus(
            shortcut,
            shortcut.action in deliverable,
            (
                "controller_binding.available"
                if shortcut.action in deliverable
                else "controller_binding.action_not_deliverable"
            ),
        )
        for shortcut in bindings.accepted
    )


#: The one chord with delivered behavior today: Back/View + Y opens the existing
#: guarded display confirmation. Additional chords stay configuration, not new
#: defaults, until their buttons and actions are separately verified.
DEFAULT_BINDING_REQUESTS: tuple[ShortcutBindingRequest, ...] = (
    ShortcutBindingRequest(
        LogicalAction.SAFE_UNDOCK,
        frozenset({ControllerButton.VIEW, ControllerButton.Y}),
    ),
)
