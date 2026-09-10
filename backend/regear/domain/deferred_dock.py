"""Pure, non-authorizing player dock intent deferred for a running game."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .control_plane import RequestSource
from .models import GameState


MIN_DEFERRED_DOCK_TTL_MS = 1_000
MAX_DEFERRED_DOCK_TTL_MS = 15 * 60_000


class DeferredDockState(StrEnum):
    DEFERRED = "deferred"
    ELIGIBLE = "eligible"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class DeferredDockIntent:
    """A bounded player request, not a transition plan or execution permit."""

    intent_id: str
    source: RequestSource
    attachment_binding: str
    requested_at_monotonic_ms: int
    expires_at_monotonic_ms: int

    def __post_init__(self) -> None:
        if not self.intent_id or not self.attachment_binding:
            raise ValueError("deferred dock intent requires opaque identities")
        if self.source not in {RequestSource.MANUAL, RequestSource.CONTROLLER}:
            raise ValueError("deferred dock intent requires direct player intent")
        if self.requested_at_monotonic_ms < 0:
            raise ValueError("deferred dock intent time is invalid")
        ttl_ms = self.expires_at_monotonic_ms - self.requested_at_monotonic_ms
        if not MIN_DEFERRED_DOCK_TTL_MS <= ttl_ms <= MAX_DEFERRED_DOCK_TTL_MS:
            raise ValueError("deferred dock intent expiry is invalid")


@dataclass(frozen=True, slots=True)
class DeferredDockHandoff:
    """Fresh eligibility evidence for a future owner; never an execution permit."""

    intent_id: str
    attachment_binding: str
    observed_generation: str

    def __post_init__(self) -> None:
        if not all((self.intent_id, self.attachment_binding, self.observed_generation)):
            raise ValueError("deferred dock handoff is incomplete")


@dataclass(frozen=True, slots=True)
class DeferredDockResolution:
    state: DeferredDockState
    code: str
    intent: DeferredDockIntent | None = None
    handoff: DeferredDockHandoff | None = None

    def __post_init__(self) -> None:
        if self.state is DeferredDockState.DEFERRED and self.intent is None:
            raise ValueError("deferred dock state requires an intent")
        if self.state is DeferredDockState.ELIGIBLE:
            if self.intent is not None or self.handoff is None:
                raise ValueError("eligible deferred dock requires only a handoff")
        elif self.handoff is not None:
            raise ValueError("only eligible deferred dock states expose a handoff")


def create_deferred_dock_intent(
    *,
    intent_id: str,
    source: RequestSource,
    attachment_binding: str,
    game_state: GameState,
    now_monotonic_ms: int,
    ttl_ms: int,
) -> DeferredDockResolution:
    """Record direct player intent only while the game state is exactly running."""
    if game_state is GameState.UNKNOWN:
        return DeferredDockResolution(
            DeferredDockState.REJECTED, "dock_intent.game_state_unknown"
        )
    if game_state is not GameState.RUNNING:
        return DeferredDockResolution(
            DeferredDockState.REJECTED, "dock_intent.game_not_running"
        )
    try:
        intent = DeferredDockIntent(
            intent_id,
            source,
            attachment_binding,
            now_monotonic_ms,
            now_monotonic_ms + ttl_ms,
        )
    except ValueError:
        return DeferredDockResolution(
            DeferredDockState.REJECTED, "dock_intent.request_invalid"
        )
    return DeferredDockResolution(
        DeferredDockState.DEFERRED, "dock_intent.game_running", intent
    )


def cancel_deferred_dock_intent(intent: DeferredDockIntent) -> DeferredDockResolution:
    """Cancel locally; no state owner or transition is invoked."""
    return DeferredDockResolution(DeferredDockState.CANCELLED, "dock_intent.cancelled")


def evaluate_deferred_dock_intent(
    intent: DeferredDockIntent,
    *,
    attachment_binding: str,
    game_state: GameState,
    observed_generation: str,
    now_monotonic_ms: int,
) -> DeferredDockResolution:
    """Return fresh idle eligibility or terminate safely; never schedules work."""
    if now_monotonic_ms >= intent.expires_at_monotonic_ms:
        return DeferredDockResolution(DeferredDockState.EXPIRED, "dock_intent.expired")
    if attachment_binding != intent.attachment_binding:
        return DeferredDockResolution(
            DeferredDockState.INVALIDATED, "dock_intent.attachment_changed"
        )
    if game_state is GameState.UNKNOWN:
        return DeferredDockResolution(
            DeferredDockState.INVALIDATED, "dock_intent.game_state_unknown"
        )
    if game_state is GameState.RUNNING:
        return DeferredDockResolution(
            DeferredDockState.DEFERRED, "dock_intent.game_running", intent
        )
    if not observed_generation:
        return DeferredDockResolution(
            DeferredDockState.INVALIDATED, "dock_intent.observation_unavailable"
        )
    return DeferredDockResolution(
        DeferredDockState.ELIGIBLE,
        "dock_intent.game_closed",
        handoff=DeferredDockHandoff(
            intent.intent_id, intent.attachment_binding, observed_generation
        ),
    )
