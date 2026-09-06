"""Pure menu-button routing; no device capture, injection, or dock actions.

Bindings must come from separately verified per-transport hardware evidence.
There are deliberately no guessed Raikiri report offsets or enabled profiles.
"""

from dataclasses import dataclass
from enum import StrEnum


class ControllerTransport(StrEnum):
    USB = "usb"
    DONGLE = "dongle"
    BLUETOOTH = "bluetooth"


class MenuAction(StrEnum):
    MAIN_MENU = "main_menu"
    QUICK_ACCESS = "quick_access"


@dataclass(frozen=True)
class MenuBinding:
    """Exact opaque source token includes the interface as well as the button."""

    source: str
    action: MenuAction


@dataclass(frozen=True)
class ControllerMenuProfile:
    device: str
    transport: ControllerTransport
    bindings: tuple[MenuBinding, ...]
    verified: bool = False

    def __post_init__(self):
        sources = [binding.source for binding in self.bindings]
        if not self.device or not isinstance(self.transport, ControllerTransport):
            raise ValueError("exact device and transport required")
        if not sources or any(not source for source in sources) or len(set(sources)) != len(sources):
            raise ValueError("unique nonempty button sources required")
        if any(not isinstance(binding.action, MenuAction) for binding in self.bindings):
            raise ValueError("only menu actions allowed")


@dataclass(frozen=True)
class MenuInput:
    device: str
    transport: ControllerTransport
    session: str
    sequence: int
    pressed: frozenset[str]
    verified: bool = False


@dataclass(frozen=True)
class MenuState:
    session: str = ""
    sequence: int = -1
    pressed: frozenset[str] = frozenset()


@dataclass(frozen=True)
class MenuDecision:
    state: MenuState
    action: MenuAction | None
    reason: str


def route_menu_input(profile: ControllerMenuProfile, event: MenuInput,
                     state: MenuState = MenuState()) -> MenuDecision:
    """Consume ordered complete button snapshots, emitting one press edge.

    Caller owns one state per device/transport, discards callbacks from retired
    capture sessions, and resets on profile changes. Session strings are not
    ordered epochs and this function cannot identify a retired capture.
    Reconnect or lost verification requires an observed release before a held
    button can trigger. A pair in one snapshot is suppressed; a staggered pair
    can already emit the first button and needs separate timing policy if
    hardware evidence requires it. Inputs are never consumed from Steam.
    """
    if (not profile.verified or not event.verified or not event.session
            or event.sequence < 0 or event.device != profile.device
            or event.transport != profile.transport):
        return MenuDecision(MenuState(), None, "input_unverified")
    if event.session == state.session and event.sequence <= state.sequence:
        return MenuDecision(state, None, "stale_input")
    current = MenuState(event.session, event.sequence, event.pressed)
    if event.session != state.session:
        return MenuDecision(current, None, "session_baseline")
    mapped = {binding.source: binding.action for binding in profile.bindings}
    active = event.pressed & mapped.keys()
    if len(active) > 1:
        return MenuDecision(current, None, "ambiguous_chord")
    rising = active - state.pressed
    if not rising:
        return MenuDecision(current, None, "no_press")
    return MenuDecision(current, mapped[next(iter(rising))], "menu_requested")
