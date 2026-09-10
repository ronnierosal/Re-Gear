"""Pure performance budget policy for future Re-Gear background work."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import GameState


class RuntimeWorkKind(StrEnum):
    TRANSITION_SAFETY = "transition_safety"
    EXPLICIT_PLAYER_REQUEST = "explicit_player_request"
    PLACEMENT_WATCH = "placement_watch"
    EXPLICIT_DIAGNOSTICS = "explicit_diagnostics"
    BACKGROUND_TELEMETRY = "background_telemetry"


class RuntimeBudgetDecisionKind(StrEnum):
    RUN = "run"
    DEFER = "defer"


@dataclass(frozen=True, slots=True)
class RuntimeBudgetDecision:
    kind: RuntimeBudgetDecisionKind
    defer_for_ms: int
    reason: str

    def __post_init__(self) -> None:
        if self.kind is RuntimeBudgetDecisionKind.RUN and self.defer_for_ms != 0:
            raise ValueError("runnable work cannot have a delay")
        if self.kind is RuntimeBudgetDecisionKind.DEFER and self.defer_for_ms <= 0:
            raise ValueError("deferred work needs a positive delay")


RUNNABLE_WHILE_GAME_ACTIVE = frozenset(
    {
        RuntimeWorkKind.TRANSITION_SAFETY,
        RuntimeWorkKind.EXPLICIT_PLAYER_REQUEST,
        RuntimeWorkKind.PLACEMENT_WATCH,
    }
)


def decide_runtime_budget(
    work: RuntimeWorkKind, game_state: GameState
) -> RuntimeBudgetDecision:
    """Decide whether optional work may run without a background loop.

    The policy has no clock, telemetry collector, scheduler, or mechanism
    authority. A caller must still own its cadence and re-observe state when a
    deferred task is reconsidered.
    """
    if work in RUNNABLE_WHILE_GAME_ACTIVE:
        return RuntimeBudgetDecision(
            RuntimeBudgetDecisionKind.RUN, 0, "runtime.required_work"
        )
    if game_state is GameState.RUNNING:
        delay = (
            5_000
            if work is RuntimeWorkKind.EXPLICIT_DIAGNOSTICS
            else 30_000
        )
        return RuntimeBudgetDecision(
            RuntimeBudgetDecisionKind.DEFER,
            delay,
            "runtime.game_active",
        )
    if game_state is GameState.UNKNOWN:
        return RuntimeBudgetDecision(
            RuntimeBudgetDecisionKind.DEFER,
            15_000,
            "runtime.game_state_unknown",
        )
    return RuntimeBudgetDecision(
        RuntimeBudgetDecisionKind.RUN, 0, "runtime.idle"
    )
