"""Pure policy for a future post-sleep game-relaunch flow.

This module classifies supplied categorical evidence only.  It never launches,
saves, closes, or otherwise controls a game or the host.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SleepRelaunchOutcome(StrEnum):
    EXPLAIN_RECOVERY = "explain_recovery"
    NO_RELAUNCH = "no_relaunch"
    PROMPT_PREFERENCE = "prompt_preference"
    ELIGIBLE_FOR_FUTURE_RELAUNCH = "eligible_for_future_relaunch"


class ObservedGameSessionState(StrEnum):
    STOPPED = "stopped"
    RUNNING = "running"
    UNKNOWN = "unknown"


class RelaunchPreference(StrEnum):
    UNKNOWN = "unknown"
    OPTED_IN = "opted_in"
    OPTED_OUT = "opted_out"


@dataclass(frozen=True, slots=True)
class SleepRelaunchFact:
    value: bool | None
    verified: bool
    generation: str
    sample_id: str

    def __post_init__(self) -> None:
        if not self.generation or not self.sample_id:
            raise ValueError("sleep relaunch fact requires observation identity")
        if self.verified and self.value is None:
            raise ValueError("verified sleep relaunch fact needs a value")


@dataclass(frozen=True, slots=True)
class SleepRelaunchEvidence:
    """Current opaque-bound observations without game, account, or device IDs."""

    incident_binding: str
    generation: str
    sample_id: str
    interrupted_docked_sleep: SleepRelaunchFact
    handheld_display: SleepRelaunchFact
    handheld_input: SleepRelaunchFact
    handheld_audio: SleepRelaunchFact
    update_risk: SleepRelaunchFact
    cloud_sync_risk: SleepRelaunchFact
    launch_risk: SleepRelaunchFact
    repeat_failure_risk: SleepRelaunchFact
    game_session: ObservedGameSessionState

    def __post_init__(self) -> None:
        if not all((self.incident_binding, self.generation, self.sample_id)):
            raise ValueError("sleep relaunch evidence requires opaque binding")

    @property
    def facts(self) -> tuple[SleepRelaunchFact, ...]:
        return (
            self.interrupted_docked_sleep,
            self.handheld_display,
            self.handheld_input,
            self.handheld_audio,
            self.update_risk,
            self.cloud_sync_risk,
            self.launch_risk,
            self.repeat_failure_risk,
        )


@dataclass(frozen=True, slots=True)
class SleepRelaunchAssessment:
    outcome: SleepRelaunchOutcome
    code: str

    @property
    def authorizes_action(self) -> bool:
        """A future flow still needs a separately reviewed action adapter."""
        return False


def assess_sleep_relaunch_eligibility(
    evidence: SleepRelaunchEvidence,
    *,
    expected_incident_binding: str,
    expected_generation: str,
    expected_sample_id: str,
    preference: RelaunchPreference,
) -> SleepRelaunchAssessment:
    """Classify future-flow eligibility; do not infer crash or game survival."""

    invalid = _invalidation(
        evidence,
        expected_incident_binding,
        expected_generation,
        expected_sample_id,
    )
    if invalid:
        return _explain(invalid)
    if not _is_verified(evidence.interrupted_docked_sleep, True):
        return _explain("sleep_relaunch.interrupted_sleep_unverified")
    for fact, code in (
        (evidence.handheld_display, "sleep_relaunch.handheld_display_unverified"),
        (evidence.handheld_input, "sleep_relaunch.handheld_input_unverified"),
        (evidence.handheld_audio, "sleep_relaunch.handheld_audio_unverified"),
    ):
        if not _is_verified(fact, True):
            return _explain(code)
    if evidence.game_session is ObservedGameSessionState.UNKNOWN:
        return _explain("sleep_relaunch.game_state_unknown")
    if evidence.game_session is ObservedGameSessionState.RUNNING:
        return _explain("sleep_relaunch.game_running_observed")
    for fact, code in (
        (evidence.update_risk, "sleep_relaunch.update_risk"),
        (evidence.cloud_sync_risk, "sleep_relaunch.cloud_sync_risk"),
        (evidence.launch_risk, "sleep_relaunch.launch_risk"),
        (evidence.repeat_failure_risk, "sleep_relaunch.repeat_failure_risk"),
    ):
        if not _is_verified(fact, False):
            return _explain(code)
    if preference is RelaunchPreference.OPTED_OUT:
        return SleepRelaunchAssessment(
            SleepRelaunchOutcome.NO_RELAUNCH, "sleep_relaunch.preference_opted_out"
        )
    if preference is RelaunchPreference.UNKNOWN:
        return SleepRelaunchAssessment(
            SleepRelaunchOutcome.PROMPT_PREFERENCE,
            "sleep_relaunch.preference_required",
        )
    return SleepRelaunchAssessment(
        SleepRelaunchOutcome.ELIGIBLE_FOR_FUTURE_RELAUNCH,
        "sleep_relaunch.future_flow_eligible",
    )


def _invalidation(evidence, expected_binding, expected_generation, expected_sample):
    if not all((expected_binding, expected_generation, expected_sample)):
        return "sleep_relaunch.expected_observation_invalid"
    if evidence.incident_binding != expected_binding:
        return "sleep_relaunch.incident_binding_changed"
    if evidence.generation != expected_generation or evidence.sample_id != expected_sample:
        return "sleep_relaunch.evidence_stale"
    if any(
        fact.generation != evidence.generation or fact.sample_id != evidence.sample_id
        for fact in evidence.facts
    ):
        return "sleep_relaunch.evidence_inconsistent"
    return ""


def _is_verified(fact: SleepRelaunchFact, expected: bool) -> bool:
    return fact.verified and fact.value is expected


def _explain(code: str) -> SleepRelaunchAssessment:
    return SleepRelaunchAssessment(SleepRelaunchOutcome.EXPLAIN_RECOVERY, code)
