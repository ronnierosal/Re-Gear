"""Pure combined TV/audio/controller handoff eligibility and rollback policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import GameState


class CombinedHandoffState(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    ROLLBACK_REQUIRED = "rollback_required"


@dataclass(frozen=True, slots=True)
class HandoffFact:
    """One categorical fact bound to the same private observation."""

    value: bool | None
    verified: bool
    generation: str
    sample_id: str

    def __post_init__(self) -> None:
        if not self.generation or not self.sample_id:
            raise ValueError("handoff fact requires observation identity")
        if self.verified and self.value is None:
            raise ValueError("verified handoff fact needs a value")


@dataclass(frozen=True, slots=True)
class CombinedHandoffEvidence:
    """Explicit current facts only; it carries no device command or identity."""

    attachment_binding: str
    generation: str
    sample_id: str
    game_state: GameState
    external_display_active: HandoffFact
    external_render_gpu: HandoffFact
    external_audio_active: HandoffFact
    external_controller_active: HandoffFact
    portable_display_rollback: HandoffFact
    portable_audio_rollback: HandoffFact
    builtin_controller_rollback: HandoffFact
    handoff_attempted: bool = False

    def __post_init__(self) -> None:
        if not all((self.attachment_binding, self.generation, self.sample_id)):
            raise ValueError("combined handoff requires opaque observation binding")

    @property
    def facts(self) -> tuple[HandoffFact, ...]:
        return (
            self.external_display_active,
            self.external_render_gpu,
            self.external_audio_active,
            self.external_controller_active,
            self.portable_display_rollback,
            self.portable_audio_rollback,
            self.builtin_controller_rollback,
        )


@dataclass(frozen=True, slots=True)
class CombinedHandoffEligibility:
    """Fresh evidence for a future unified engine, never an execution permit."""

    attachment_binding: str
    observed_generation: str
    observed_sample_id: str

    def __post_init__(self) -> None:
        if not all(
            (self.attachment_binding, self.observed_generation, self.observed_sample_id)
        ):
            raise ValueError("combined handoff eligibility is incomplete")


@dataclass(frozen=True, slots=True)
class CombinedHandoffOutcome:
    state: CombinedHandoffState
    code: str
    eligibility: CombinedHandoffEligibility | None = None

    def __post_init__(self) -> None:
        if self.state is CombinedHandoffState.ELIGIBLE and self.eligibility is None:
            raise ValueError("eligible combined handoff needs evidence")
        if self.state is not CombinedHandoffState.ELIGIBLE and self.eligibility:
            raise ValueError("only eligible combined handoff exposes evidence")


def assess_combined_handoff(
    evidence: CombinedHandoffEvidence,
    *,
    expected_attachment_binding: str,
    expected_generation: str,
    expected_sample_id: str,
) -> CombinedHandoffOutcome:
    """Classify one explicit snapshot without scheduling or applying a handoff."""
    failure = _failure_code(
        evidence, expected_attachment_binding, expected_generation, expected_sample_id
    )
    if failure:
        return CombinedHandoffOutcome(
            CombinedHandoffState.ROLLBACK_REQUIRED
            if evidence.handoff_attempted
            else CombinedHandoffState.INELIGIBLE,
            "handoff.rollback_required" if evidence.handoff_attempted else failure,
        )
    return CombinedHandoffOutcome(
        CombinedHandoffState.ELIGIBLE,
        "handoff.eligible",
        CombinedHandoffEligibility(
            evidence.attachment_binding, evidence.generation, evidence.sample_id
        ),
    )


def _failure_code(
    evidence: CombinedHandoffEvidence,
    expected_attachment_binding: str,
    expected_generation: str,
    expected_sample_id: str,
) -> str:
    if not all((expected_attachment_binding, expected_generation, expected_sample_id)):
        return "handoff.expected_observation_invalid"
    if evidence.attachment_binding != expected_attachment_binding:
        return "handoff.attachment_changed"
    if (
        evidence.generation != expected_generation
        or evidence.sample_id != expected_sample_id
        or any(
            fact.generation != evidence.generation or fact.sample_id != evidence.sample_id
            for fact in evidence.facts
        )
    ):
        return "handoff.observation_stale_or_inconsistent"
    if evidence.game_state is not GameState.IDLE:
        return (
            "handoff.game_running"
            if evidence.game_state is GameState.RUNNING
            else "handoff.game_state_unknown"
        )
    if (
        evidence.external_display_active.verified
        and evidence.external_render_gpu.verified
        and evidence.external_display_active.value is not evidence.external_render_gpu.value
    ):
        return "handoff.display_render_contradictory"
    for fact, code in (
        (evidence.external_display_active, "handoff.external_display_inactive"),
        (evidence.external_render_gpu, "handoff.external_render_unverified"),
        (evidence.external_audio_active, "handoff.external_audio_unverified"),
        (evidence.external_controller_active, "handoff.external_controller_unverified"),
        (evidence.portable_display_rollback, "handoff.display_rollback_unverified"),
        (evidence.portable_audio_rollback, "handoff.audio_rollback_unverified"),
        (evidence.builtin_controller_rollback, "handoff.controller_rollback_unverified"),
    ):
        if not fact.verified or fact.value is not True:
            return code
    return ""
