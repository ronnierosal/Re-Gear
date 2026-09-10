"""Logical player actions that route into existing Re-Gear request vocabulary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .control_plane import RequestIntent, RequestSource, TransitionRequest


class LogicalAction(StrEnum):
    SAFE_UNDOCK = "safe_undock"
    RETURN_TO_HANDHELD = "return_to_handheld"
    RECOVERY = "recovery"
    CHANGE_PERFORMANCE_PROFILE = "change_performance_profile"


class ActionSurface(StrEnum):
    DECKY_UI = "decky_ui"
    CONTROLLER = "controller"
    DEVICE_BUTTON = "device_button"


@dataclass(frozen=True, slots=True)
class LogicalActionRequest:
    action: LogicalAction
    surface: ActionSurface
    requested_at: str
    expected_generation: str

    def __post_init__(self) -> None:
        if not self.requested_at or not self.expected_generation:
            raise ValueError("logical action time and generation are required")


@dataclass(frozen=True, slots=True)
class LogicalActionRoute:
    action: LogicalAction
    intent: RequestIntent | None
    source: RequestSource
    blocker: str = ""

    @property
    def requestable(self) -> bool:
        return self.intent is not None and not self.blocker


def route_logical_action(request: LogicalActionRequest) -> LogicalActionRoute:
    """Route input surfaces without introducing a second transition path."""
    source = {
        ActionSurface.DECKY_UI: RequestSource.MANUAL,
        ActionSurface.CONTROLLER: RequestSource.CONTROLLER,
        ActionSurface.DEVICE_BUTTON: RequestSource.PHYSICAL_BUTTON,
    }[request.surface]
    intent = {
        LogicalAction.SAFE_UNDOCK: RequestIntent.UNDOCK,
        LogicalAction.RETURN_TO_HANDHELD: RequestIntent.UNDOCK,
        LogicalAction.RECOVERY: RequestIntent.RECOVER,
    }.get(request.action)
    if intent is None:
        return LogicalActionRoute(
            request.action,
            None,
            source,
            "action.performance_profile_unimplemented",
        )
    return LogicalActionRoute(request.action, intent, source)


def transition_request_from_logical_action(
    request: LogicalActionRequest, request_id: str
) -> TransitionRequest | None:
    """Create the ordinary transition request, or no request when unavailable."""
    route = route_logical_action(request)
    if not route.requestable:
        return None
    return TransitionRequest(
        request_id=request_id,
        intent=route.intent,
        source=route.source,
        requested_at=request.requested_at,
        expected_generation=request.expected_generation,
    )
