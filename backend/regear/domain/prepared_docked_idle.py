"""Pure five-second prepared-docked-idle eligibility, without a timer or action."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import GameState


PREPARED_DOCKED_IDLE_MS = 5_000


class PreparedDockedIdleState(StrEnum):
    NOT_YET_STABLE = "not_yet_stable"
    PREPARED = "prepared"
    INVALIDATED = "invalidated"


@dataclass(frozen=True, slots=True)
class PreparedDockedIdleEvidence:
    """One caller-supplied categorical eligibility observation."""

    attachment_binding: str
    generation: str
    sample_id: str
    observed_at_monotonic_ms: int
    game_state: GameState
    combined_handoff_eligible: bool
    evidence_generation: str
    evidence_sample_id: str

    def __post_init__(self) -> None:
        if not all(
            (
                self.attachment_binding,
                self.generation,
                self.sample_id,
                self.evidence_generation,
                self.evidence_sample_id,
            )
        ):
            raise ValueError("prepared docked idle evidence requires opaque identities")
        if self.observed_at_monotonic_ms < 0:
            raise ValueError("prepared docked idle time is invalid")

    @property
    def fresh_consistent(self) -> bool:
        return (
            self.combined_handoff_eligible
            and self.evidence_generation == self.generation
            and self.evidence_sample_id == self.sample_id
        )


@dataclass(frozen=True, slots=True)
class PreparedDockedIdleWindow:
    attachment_binding: str
    generation: str
    sample_id: str
    started_at_monotonic_ms: int


@dataclass(frozen=True, slots=True)
class PreparedDockedIdleEligibility:
    """Evidence only for a future owner; never a command or transition permit."""

    attachment_binding: str
    observed_generation: str
    observed_sample_id: str


@dataclass(frozen=True, slots=True)
class PreparedDockedIdleOutcome:
    state: PreparedDockedIdleState
    code: str
    window: PreparedDockedIdleWindow | None = None
    eligibility: PreparedDockedIdleEligibility | None = None

    def __post_init__(self) -> None:
        if self.state is PreparedDockedIdleState.NOT_YET_STABLE and self.window is None:
            raise ValueError("unstable prepared docked idle needs a window")
        if self.state is PreparedDockedIdleState.PREPARED:
            if self.window is not None or self.eligibility is None:
                raise ValueError("prepared docked idle needs only eligibility evidence")
        elif self.eligibility is not None:
            raise ValueError("only prepared state exposes eligibility evidence")


def begin_prepared_docked_idle(
    evidence: PreparedDockedIdleEvidence,
) -> PreparedDockedIdleOutcome:
    """Start one caller-owned stability window; no loop or timer is created."""
    failure = _evidence_failure(evidence)
    if failure:
        return PreparedDockedIdleOutcome(PreparedDockedIdleState.INVALIDATED, failure)
    return PreparedDockedIdleOutcome(
        PreparedDockedIdleState.NOT_YET_STABLE,
        "prepared_docked_idle.started",
        PreparedDockedIdleWindow(
            evidence.attachment_binding,
            evidence.generation,
            evidence.sample_id,
            evidence.observed_at_monotonic_ms,
        ),
    )


def assess_prepared_docked_idle(
    window: PreparedDockedIdleWindow,
    evidence: PreparedDockedIdleEvidence,
) -> PreparedDockedIdleOutcome:
    """Classify a later supplied observation; never schedules revalidation."""
    failure = _evidence_failure(evidence)
    if failure:
        return PreparedDockedIdleOutcome(PreparedDockedIdleState.INVALIDATED, failure)
    if evidence.attachment_binding != window.attachment_binding:
        return PreparedDockedIdleOutcome(
            PreparedDockedIdleState.INVALIDATED, "prepared_docked_idle.attachment_changed"
        )
    if evidence.generation != window.generation:
        return PreparedDockedIdleOutcome(
            PreparedDockedIdleState.INVALIDATED, "prepared_docked_idle.generation_changed"
        )
    elapsed_ms = evidence.observed_at_monotonic_ms - window.started_at_monotonic_ms
    if elapsed_ms < 0:
        return PreparedDockedIdleOutcome(
            PreparedDockedIdleState.INVALIDATED, "prepared_docked_idle.clock_invalid"
        )
    if evidence.sample_id == window.sample_id:
        return PreparedDockedIdleOutcome(
            PreparedDockedIdleState.NOT_YET_STABLE,
            "prepared_docked_idle.observation_not_fresh",
            window,
        )
    if elapsed_ms < PREPARED_DOCKED_IDLE_MS:
        return PreparedDockedIdleOutcome(
            PreparedDockedIdleState.NOT_YET_STABLE,
            "prepared_docked_idle.stabilizing",
            window,
        )
    return PreparedDockedIdleOutcome(
        PreparedDockedIdleState.PREPARED,
        "prepared_docked_idle.ready",
        eligibility=PreparedDockedIdleEligibility(
            evidence.attachment_binding, evidence.generation, evidence.sample_id
        ),
    )


def _evidence_failure(evidence: PreparedDockedIdleEvidence) -> str:
    if evidence.game_state is GameState.RUNNING:
        return "prepared_docked_idle.game_running"
    if evidence.game_state is GameState.UNKNOWN:
        return "prepared_docked_idle.game_state_unknown"
    if not evidence.fresh_consistent:
        return "prepared_docked_idle.evidence_stale_or_inconsistent"
    return ""
