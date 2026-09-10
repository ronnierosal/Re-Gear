"""Pure Safe Undock evidence classification; never a physical-removal claim."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import GameState


class SafeUndockReadinessState(StrEnum):
    READY_FOR_REVALIDATION = "ready_for_revalidation"
    NOT_READY = "not_ready"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    INVALIDATED = "invalidated"


@dataclass(frozen=True, slots=True)
class SafeUndockFact:
    value: bool | None
    verified: bool
    generation: str
    sample_id: str

    def __post_init__(self) -> None:
        if not self.generation or not self.sample_id:
            raise ValueError("safe undock fact requires observation identity")
        if self.verified and self.value is None:
            raise ValueError("verified safe undock fact needs a value")


@dataclass(frozen=True, slots=True)
class SafeUndockEvidence:
    """Explicit current facts without client, device, or command identities."""

    attachment_binding: str
    generation: str
    sample_id: str
    game_state: GameState
    exact_attachment: SafeUndockFact
    topology_exact: SafeUndockFact
    client_scan_complete: SafeUndockFact
    clients_clear: SafeUndockFact
    portable_display_active: SafeUndockFact
    portable_render_gpu: SafeUndockFact
    portable_audio_active: SafeUndockFact
    builtin_controller_active: SafeUndockFact
    external_display_active: SafeUndockFact

    def __post_init__(self) -> None:
        if not all((self.attachment_binding, self.generation, self.sample_id)):
            raise ValueError("safe undock evidence requires opaque observation binding")

    @property
    def facts(self) -> tuple[SafeUndockFact, ...]:
        return (
            self.exact_attachment,
            self.topology_exact,
            self.client_scan_complete,
            self.clients_clear,
            self.portable_display_active,
            self.portable_render_gpu,
            self.portable_audio_active,
            self.builtin_controller_active,
            self.external_display_active,
        )


@dataclass(frozen=True, slots=True)
class SafeUndockRevalidation:
    """Opaque evidence a future supervised owner must independently revalidate."""

    attachment_binding: str
    observed_generation: str
    observed_sample_id: str

    def __post_init__(self) -> None:
        if not all(
            (self.attachment_binding, self.observed_generation, self.observed_sample_id)
        ):
            raise ValueError("safe undock revalidation is incomplete")


@dataclass(frozen=True, slots=True)
class SafeUndockReadiness:
    state: SafeUndockReadinessState
    code: str
    revalidation: SafeUndockRevalidation | None = None

    def __post_init__(self) -> None:
        if self.state is SafeUndockReadinessState.READY_FOR_REVALIDATION:
            if self.revalidation is None:
                raise ValueError("safe undock readiness requires revalidation evidence")
        elif self.revalidation is not None:
            raise ValueError("only ready safe undock state exposes revalidation evidence")


def assess_safe_undock_readiness(
    evidence: SafeUndockEvidence,
    *,
    expected_attachment_binding: str,
    expected_generation: str,
    expected_sample_id: str,
) -> SafeUndockReadiness:
    """Classify one fresh explicit observation without invoking any action."""
    invalid = invalidation_code(
        evidence, expected_attachment_binding, expected_generation, expected_sample_id
    )
    if invalid:
        return SafeUndockReadiness(SafeUndockReadinessState.INVALIDATED, invalid)
    if evidence.game_state is GameState.RUNNING:
        return SafeUndockReadiness(SafeUndockReadinessState.NOT_READY, "safe_undock.game_running")
    if evidence.game_state is GameState.UNKNOWN:
        return SafeUndockReadiness(
            SafeUndockReadinessState.EVIDENCE_INSUFFICIENT,
            "safe_undock.game_state_unknown",
        )
    if (
        evidence.portable_display_active.verified
        and evidence.external_display_active.verified
        and evidence.portable_display_active.value is True
        and evidence.external_display_active.value is True
    ):
        return SafeUndockReadiness(
            SafeUndockReadinessState.EVIDENCE_INSUFFICIENT,
            "safe_undock.display_contradictory",
        )
    for fact, state, code, expected in (
        (evidence.exact_attachment, SafeUndockReadinessState.EVIDENCE_INSUFFICIENT, "safe_undock.attachment_unverified", True),
        (evidence.topology_exact, SafeUndockReadinessState.EVIDENCE_INSUFFICIENT, "safe_undock.topology_unverified", True),
        (evidence.client_scan_complete, SafeUndockReadinessState.EVIDENCE_INSUFFICIENT, "safe_undock.client_scan_incomplete", True),
        (evidence.clients_clear, SafeUndockReadinessState.NOT_READY, "safe_undock.clients_active_or_protected", True),
        (evidence.portable_display_active, SafeUndockReadinessState.NOT_READY, "safe_undock.portable_display_unverified", True),
        (evidence.portable_render_gpu, SafeUndockReadinessState.NOT_READY, "safe_undock.portable_render_unverified", True),
        (evidence.portable_audio_active, SafeUndockReadinessState.NOT_READY, "safe_undock.portable_audio_unverified", True),
        (evidence.builtin_controller_active, SafeUndockReadinessState.NOT_READY, "safe_undock.builtin_controller_unverified", True),
        (evidence.external_display_active, SafeUndockReadinessState.NOT_READY, "safe_undock.external_display_still_active", False),
    ):
        if not fact.verified or fact.value is not expected:
            return SafeUndockReadiness(state, code)
    return SafeUndockReadiness(
        SafeUndockReadinessState.READY_FOR_REVALIDATION,
        "safe_undock.ready_for_revalidation",
        SafeUndockRevalidation(
            evidence.attachment_binding, evidence.generation, evidence.sample_id
        ),
    )


def invalidation_code(
    evidence: SafeUndockEvidence,
    expected_attachment_binding: str,
    expected_generation: str,
    expected_sample_id: str,
) -> str:
    """Return the invalidation code for one observation, or an empty string.

    Shared with `regear.domain.removal_safety`, which classifies a narrower
    subset of the same evidence under identical staleness rules.
    """
    if not all((expected_attachment_binding, expected_generation, expected_sample_id)):
        return "safe_undock.expected_observation_invalid"
    if evidence.attachment_binding != expected_attachment_binding:
        return "safe_undock.attachment_changed"
    if (
        evidence.generation != expected_generation
        or evidence.sample_id != expected_sample_id
        or any(
            fact.generation != evidence.generation or fact.sample_id != evidence.sample_id
            for fact in evidence.facts
        )
    ):
        return "safe_undock.evidence_stale_or_inconsistent"
    return ""
