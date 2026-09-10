"""Pure, non-authorizing HDMI-CEC TV-wake feasibility and result contract."""
from dataclasses import dataclass
from enum import StrEnum

class TvWakeState(StrEnum):
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    ATTEMPT_ELIGIBLE = "attempt_eligible"
    ATTEMPTED_UNVERIFIED = "attempted_unverified"
    VERIFIED_AWAKE = "verified_awake"
    FAILED_OR_UNKNOWN = "failed_or_unknown"
class TvWakeTrigger(StrEnum):
    ELIGIBLE_ATTACH = "eligible_attach"
    VERIFIED_CONTROLLER = "verified_controller"

@dataclass(frozen=True, slots=True)
class TvWakeEvidence:
    profile_support: bool | None
    adapter_configured: bool
    exact_external_display_before: bool
    attempt_recorded: bool = False
    external_display_verified_after: bool = False
    adapter_result: bool | None = None

def assess_tv_wake(evidence: TvWakeEvidence) -> TvWakeState:
    if evidence.profile_support is False:
        return TvWakeState.UNSUPPORTED
    if evidence.profile_support is not True or not evidence.adapter_configured:
        return TvWakeState.UNAVAILABLE
    if not evidence.exact_external_display_before:
        return TvWakeState.FAILED_OR_UNKNOWN if evidence.attempt_recorded else TvWakeState.UNAVAILABLE
    if not evidence.attempt_recorded:
        return TvWakeState.ATTEMPT_ELIGIBLE
    if evidence.adapter_result is False:
        return TvWakeState.FAILED_OR_UNKNOWN
    if evidence.adapter_result is True and evidence.external_display_verified_after:
        return TvWakeState.VERIFIED_AWAKE
    return TvWakeState.ATTEMPTED_UNVERIFIED

@dataclass(frozen=True, slots=True)
class TvWakeRequestEvidence:
    trigger: TvWakeTrigger
    game_idle_verified: bool
    cec_eligible: bool
    external_display_fresh: bool
    controller_input_verified: bool = False
    already_attempted: bool = False

def request_tv_wake(evidence: TvWakeRequestEvidence) -> bool:
    """Return only one future adapter request eligibility; never performs a wake."""
    return (not evidence.already_attempted and evidence.game_idle_verified
        and evidence.cec_eligible and evidence.external_display_fresh
        and (evidence.trigger is TvWakeTrigger.ELIGIBLE_ATTACH or evidence.controller_input_verified))
