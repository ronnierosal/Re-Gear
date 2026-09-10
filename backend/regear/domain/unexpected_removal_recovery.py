"""Pure evidence assessment for an unexpected eGPU-removal incident.

The assessment describes observed bridge loss and handheld fallback only.  It
does not recover hardware, infer a game's outcome, or authorize any system
action.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import GameState


class RecoveryFactState(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class UnexpectedRemovalRecoveryState(StrEnum):
    PORTABLE_FALLBACK_VERIFIED = "portable_fallback_verified"
    RECOVERY_INCOMPLETE = "recovery_incomplete"
    NEEDS_SUPERVISED_DIAGNOSIS = "needs_supervised_diagnosis"


class GameOutcomeObservation(StrEnum):
    STOPPED_OBSERVED = "stopped_observed"
    RUNNING_OBSERVED = "running_observed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class UnexpectedRemovalFact:
    value: RecoveryFactState
    verified: bool
    generation: str
    sample_id: str

    def __post_init__(self) -> None:
        if not self.generation or not self.sample_id:
            raise ValueError("unexpected-removal fact requires observation identity")
        if self.verified and self.value is RecoveryFactState.UNKNOWN:
            raise ValueError("verified unexpected-removal fact cannot be unknown")


@dataclass(frozen=True, slots=True)
class UnexpectedRemovalObservation:
    """One opaque-bound observation; no device or process identities are kept."""

    attachment_binding: str
    generation: str
    sample_id: str
    bridge: UnexpectedRemovalFact
    external_topology: UnexpectedRemovalFact
    internal_display: UnexpectedRemovalFact
    builtin_input: UnexpectedRemovalFact
    internal_audio: UnexpectedRemovalFact
    game_state: GameState

    def __post_init__(self) -> None:
        if not all((self.attachment_binding, self.generation, self.sample_id)):
            raise ValueError("unexpected-removal observation requires opaque binding")

    @property
    def facts(self) -> tuple[UnexpectedRemovalFact, ...]:
        return (
            self.bridge,
            self.external_topology,
            self.internal_display,
            self.builtin_input,
            self.internal_audio,
        )


@dataclass(frozen=True, slots=True)
class UnexpectedRemovalRecoveryAssessment:
    state: UnexpectedRemovalRecoveryState
    code: str
    removal_detected: bool
    portable_fallback_verified: bool
    game_outcome: GameOutcomeObservation

    @property
    def authorizes_action(self) -> bool:
        """Evidence classification can never authorize recovery or relaunch."""
        return False


def assess_unexpected_removal_recovery(
    before: UnexpectedRemovalObservation,
    after: UnexpectedRemovalObservation,
    *,
    expected_attachment_binding: str,
    expected_generation: str,
    expected_sample_id: str,
) -> UnexpectedRemovalRecoveryAssessment:
    """Compare fresh before/after evidence without attempting recovery.

    The initial sample must match the expected docked observation.  The later
    sample must retain its opaque attachment binding while advancing both
    observation identities; otherwise no loss or handheld conclusion is made.
    """

    game_outcome = _game_outcome(after.game_state)
    invalid = _invalidation(
        before,
        after,
        expected_attachment_binding,
        expected_generation,
        expected_sample_id,
    )
    if invalid:
        return _diagnosis(invalid, game_outcome)
    if not _is_verified(before.bridge, RecoveryFactState.PRESENT) or not _is_verified(
        before.external_topology, RecoveryFactState.PRESENT
    ):
        return _diagnosis("unexpected_removal.before_dock_unverified", game_outcome)

    after_states = (after.bridge, after.external_topology)
    if any(not fact.verified or fact.value is RecoveryFactState.UNKNOWN for fact in after_states):
        return _diagnosis("unexpected_removal.loss_evidence_unknown", game_outcome)
    if after.bridge.value is not after.external_topology.value:
        return _diagnosis("unexpected_removal.topology_contradictory", game_outcome)
    if any(fact.value is RecoveryFactState.PRESENT for fact in after_states):
        return UnexpectedRemovalRecoveryAssessment(
            UnexpectedRemovalRecoveryState.RECOVERY_INCOMPLETE,
            "unexpected_removal.loss_not_verified",
            False,
            False,
            game_outcome,
        )

    removal_detected = True
    fallback = (after.internal_display, after.builtin_input, after.internal_audio)
    if any(not fact.verified or fact.value is RecoveryFactState.UNKNOWN for fact in fallback):
        return _diagnosis(
            "unexpected_removal.portable_evidence_unknown", game_outcome, removal_detected
        )
    if any(fact.value is not RecoveryFactState.PRESENT for fact in fallback):
        return UnexpectedRemovalRecoveryAssessment(
            UnexpectedRemovalRecoveryState.RECOVERY_INCOMPLETE,
            "unexpected_removal.portable_fallback_incomplete",
            removal_detected,
            False,
            game_outcome,
        )
    if after.game_state is GameState.UNKNOWN:
        return _diagnosis(
            "unexpected_removal.game_state_unknown", game_outcome, removal_detected
        )
    if after.game_state is GameState.RUNNING:
        return _diagnosis(
            "unexpected_removal.game_running_observed", game_outcome, removal_detected
        )
    return UnexpectedRemovalRecoveryAssessment(
        UnexpectedRemovalRecoveryState.PORTABLE_FALLBACK_VERIFIED,
        "unexpected_removal.portable_fallback_verified",
        removal_detected,
        True,
        game_outcome,
    )


def _invalidation(before, after, expected_binding, expected_generation, expected_sample):
    if not all((expected_binding, expected_generation, expected_sample)):
        return "unexpected_removal.expected_observation_invalid"
    if before.attachment_binding != expected_binding:
        return "unexpected_removal.before_binding_changed"
    if before.generation != expected_generation or before.sample_id != expected_sample:
        return "unexpected_removal.before_stale"
    if any(
        fact.generation != before.generation or fact.sample_id != before.sample_id
        for fact in before.facts
    ):
        return "unexpected_removal.before_inconsistent"
    if after.attachment_binding != before.attachment_binding:
        return "unexpected_removal.after_binding_changed"
    if after.generation == before.generation or after.sample_id == before.sample_id:
        return "unexpected_removal.after_not_fresh"
    if any(
        fact.generation != after.generation or fact.sample_id != after.sample_id
        for fact in after.facts
    ):
        return "unexpected_removal.after_inconsistent"
    return ""


def _is_verified(fact: UnexpectedRemovalFact, expected: RecoveryFactState) -> bool:
    return fact.verified and fact.value is expected


def _game_outcome(game_state: GameState) -> GameOutcomeObservation:
    if game_state is GameState.IDLE:
        return GameOutcomeObservation.STOPPED_OBSERVED
    if game_state is GameState.RUNNING:
        return GameOutcomeObservation.RUNNING_OBSERVED
    return GameOutcomeObservation.UNKNOWN


def _diagnosis(code, game_outcome, removal_detected=False):
    return UnexpectedRemovalRecoveryAssessment(
        UnexpectedRemovalRecoveryState.NEEDS_SUPERVISED_DIAGNOSIS,
        code,
        removal_detected,
        False,
        game_outcome,
    )
