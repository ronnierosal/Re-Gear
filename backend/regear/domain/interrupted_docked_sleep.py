"""Pure, privacy-safe evidence classifier for a docked sleep interruption.

Persistence and collection belong to future application adapters.  This value
layer deliberately accepts only categorical proof and cannot infer a sleep
event, a game crash, or a usable handheld from a connected panel alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


MAX_CHECKPOINT_AGE_MS = 24 * 60 * 60 * 1000


class EvidenceState(StrEnum):
    VERIFIED = "verified"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class InterruptedDockedSleepFact(StrEnum):
    G1_MISSING_AFTER_SLEEP = "g1_missing_after_sleep"
    GAME_SESSION_NOT_RUNNING = "game_session_not_running"
    HANDHELD_RESTORED = "handheld_restored"
    RECOVERY_INCOMPLETE_OR_UNKNOWN = "recovery_incomplete_or_unknown"


@dataclass(frozen=True, slots=True)
class DockedSleepCheckpoint:
    """Private persisted pre-sleep intent; no device or process identity."""

    incident_id: str
    captured_at_ms: int
    tv_docked_game_verified: bool

    def __post_init__(self) -> None:
        if not self.incident_id or len(self.incident_id) > 96:
            raise ValueError("checkpoint incident identity is invalid")
        if self.captured_at_ms < 0:
            raise ValueError("checkpoint time is invalid")


@dataclass(frozen=True, slots=True)
class PostWakeEvidence:
    g1: EvidenceState
    game_session: EvidenceState
    handheld_display: EvidenceState
    handheld_input: EvidenceState
    handheld_audio: EvidenceState


@dataclass(frozen=True, slots=True)
class InterruptedDockedSleepAssessment:
    incident_id: str
    facts: tuple[InterruptedDockedSleepFact, ...]
    stale: bool = False

    @property
    def handheld_restored(self) -> bool:
        return InterruptedDockedSleepFact.HANDHELD_RESTORED in self.facts


def assess_interrupted_docked_sleep(
    checkpoint: DockedSleepCheckpoint,
    evidence: PostWakeEvidence,
    *,
    now_ms: int,
) -> InterruptedDockedSleepAssessment:
    """Classify a current sample against an unexpired TV-docked game checkpoint."""
    if now_ms < checkpoint.captured_at_ms or now_ms - checkpoint.captured_at_ms > MAX_CHECKPOINT_AGE_MS:
        return InterruptedDockedSleepAssessment(checkpoint.incident_id, (), stale=True)
    if not checkpoint.tv_docked_game_verified or evidence.g1 is not EvidenceState.ABSENT:
        return InterruptedDockedSleepAssessment(checkpoint.incident_id, ())

    facts: list[InterruptedDockedSleepFact] = [
        InterruptedDockedSleepFact.G1_MISSING_AFTER_SLEEP,
    ]
    if evidence.game_session is EvidenceState.ABSENT:
        facts.append(InterruptedDockedSleepFact.GAME_SESSION_NOT_RUNNING)
    restored_signals = (
        evidence.handheld_display,
        evidence.handheld_input,
        evidence.handheld_audio,
    )
    if all(signal is EvidenceState.VERIFIED for signal in restored_signals):
        facts.append(InterruptedDockedSleepFact.HANDHELD_RESTORED)
    else:
        facts.append(InterruptedDockedSleepFact.RECOVERY_INCOMPLETE_OR_UNKNOWN)
    return InterruptedDockedSleepAssessment(checkpoint.incident_id, tuple(facts))
