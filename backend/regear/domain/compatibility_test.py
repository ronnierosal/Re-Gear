"""Pure compatibility-test session policy; no mechanisms or publication."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import StrEnum

from .control_plane import PlacementState
from .game_compatibility import (
    CompatibilityEvidence,
    CompatibilityEvidenceKind,
    EgpuHandoffStatus,
    ObservedRenderGpu,
    SaveTestOutcome,
)
from .models import GameState


SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{8,96}$")
MAX_SESSION_TTL_MS = 2 * 60 * 60 * 1000


class CompatibilityTestStage(StrEnum):
    AWAITING_BASELINE = "awaiting_baseline"
    ACTIVE = "active"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ACTION_REQUIRED = "action_required"


class CompatibilityTestDirective(StrEnum):
    ENABLE_TEMP_DIAGNOSTICS = "enable_temp_diagnostics"
    CAPTURE_BASELINE = "capture_baseline"
    OBSERVE_EGPU_HANDOFF = "observe_egpu_handoff"
    OBSERVE_SAVE_EXIT = "observe_save_exit"
    DISABLE_TEMP_DIAGNOSTICS = "disable_temp_diagnostics"
    REVIEW_RESULTS = "review_results"
    ACTION_REQUIRED = "action_required"


@dataclass(frozen=True, slots=True)
class CompatibilityTestOptions:
    test_egpu_handoff: bool = True
    test_save_exit: bool = True

    def __post_init__(self) -> None:
        if not self.test_egpu_handoff and not self.test_save_exit:
            raise ValueError("compatibility test must select at least one dimension")


@dataclass(frozen=True, slots=True)
class CompatibilityBaseline:
    generation: str
    placement: PlacementState
    game_state: GameState
    steam_app_id: str
    render_gpu: ObservedRenderGpu

    def __post_init__(self) -> None:
        if not self.generation:
            raise ValueError("compatibility baseline generation is required")
        if self.steam_app_id and not re.fullmatch(r"[1-9][0-9]{0,9}", self.steam_app_id):
            raise ValueError("compatibility baseline Steam AppID is invalid")


@dataclass(frozen=True, slots=True)
class CompatibilityTestSession:
    session_id: str
    stage: CompatibilityTestStage
    directives: tuple[CompatibilityTestDirective, ...]
    options: CompatibilityTestOptions
    evidence_kind: CompatibilityEvidenceKind
    game_catalog_id: str
    host_profile_id: str
    egpu_profile_id: str
    regear_version: str
    steamos_version: str
    started_at_ms: int
    expires_at_ms: int
    baseline: CompatibilityBaseline | None = None
    egpu_handoff: EgpuHandoffStatus = EgpuHandoffStatus.UNTESTED
    observed_render_gpu: ObservedRenderGpu = ObservedRenderGpu.UNKNOWN
    save_outcome: SaveTestOutcome = SaveTestOutcome.NOT_TESTED
    observation_generations: tuple[str, ...] = field(default_factory=tuple)
    reason_code: str = "compatibility.started"

    def __post_init__(self) -> None:
        if not SESSION_ID_RE.fullmatch(self.session_id):
            raise ValueError("compatibility session ID is invalid")
        for value in (
            self.host_profile_id,
            self.egpu_profile_id,
            self.regear_version,
            self.steamos_version,
            self.game_catalog_id,
        ):
            if not value or len(value) > 96 or not re.fullmatch(r"[A-Za-z0-9_.:-]+", value):
                raise ValueError("compatibility session identity is invalid")
        if self.started_at_ms < 0 or self.expires_at_ms <= self.started_at_ms:
            raise ValueError("compatibility session deadline is invalid")
        if len(self.observation_generations) > 8:
            raise ValueError("compatibility observation history exceeds its bound")
        if self.stage is CompatibilityTestStage.AWAITING_BASELINE:
            if self.baseline is not None or self.observation_generations:
                raise ValueError("awaiting-baseline session contains premature evidence")
        if self.stage in {
            CompatibilityTestStage.ACTIVE,
            CompatibilityTestStage.AWAITING_REVIEW,
            CompatibilityTestStage.COMPLETED,
        }:
            if self.baseline is None or not self.observation_generations:
                raise ValueError("active compatibility session lacks baseline evidence")
            if self.observation_generations[0] != self.baseline.generation:
                raise ValueError("compatibility baseline generation does not match history")
        if self.stage in {
            CompatibilityTestStage.AWAITING_REVIEW,
            CompatibilityTestStage.COMPLETED,
        }:
            if (
                self.options.test_egpu_handoff
                and self.egpu_handoff is EgpuHandoffStatus.UNTESTED
            ) or (
                self.options.test_save_exit
                and self.save_outcome is SaveTestOutcome.NOT_TESTED
            ):
                raise ValueError("reviewable compatibility session lacks requested results")
        if self.stage in {
            CompatibilityTestStage.CANCELLED,
            CompatibilityTestStage.ACTION_REQUIRED,
        } and CompatibilityTestDirective.DISABLE_TEMP_DIAGNOSTICS not in self.directives:
            raise ValueError("stopped compatibility session must disable diagnostics")


@dataclass(frozen=True, slots=True)
class CompatibilityReviewResult:
    session: CompatibilityTestSession
    evidence: CompatibilityEvidence


def start_compatibility_test(
    *,
    session_id: str,
    options: CompatibilityTestOptions,
    evidence_kind: CompatibilityEvidenceKind,
    game_catalog_id: str,
    host_profile_id: str,
    egpu_profile_id: str,
    regear_version: str,
    steamos_version: str,
    user_confirmed: bool,
    hardware_test_authorized: bool = False,
    now_ms: int = 0,
    ttl_ms: int = MAX_SESSION_TTL_MS,
) -> CompatibilityTestSession:
    if not user_confirmed:
        raise ValueError("compatibility test requires explicit user confirmation")
    if (
        evidence_kind is CompatibilityEvidenceKind.HARDWARE_TEST
        and not hardware_test_authorized
    ):
        raise ValueError("hardware compatibility test requires trusted-runner authorization")
    if now_ms < 0 or ttl_ms <= 0 or ttl_ms > MAX_SESSION_TTL_MS:
        raise ValueError("compatibility test timing is invalid")
    return CompatibilityTestSession(
        session_id=session_id,
        stage=CompatibilityTestStage.AWAITING_BASELINE,
        directives=(
            CompatibilityTestDirective.ENABLE_TEMP_DIAGNOSTICS,
            CompatibilityTestDirective.CAPTURE_BASELINE,
        ),
        options=options,
        evidence_kind=evidence_kind,
        game_catalog_id=game_catalog_id,
        host_profile_id=host_profile_id,
        egpu_profile_id=egpu_profile_id,
        regear_version=regear_version,
        steamos_version=steamos_version,
        started_at_ms=now_ms,
        expires_at_ms=now_ms + ttl_ms,
    )


def record_compatibility_baseline(
    session: CompatibilityTestSession,
    baseline: CompatibilityBaseline,
    *,
    now_ms: int,
) -> CompatibilityTestSession:
    expired = _expired(session, now_ms)
    if expired is not None:
        return expired
    if session.stage is not CompatibilityTestStage.AWAITING_BASELINE:
        return _action_required(session, "compatibility.baseline_out_of_order")
    if baseline.placement in {PlacementState.UNKNOWN, PlacementState.DEGRADED}:
        return _action_required(session, "compatibility.baseline_unverified")
    if baseline.game_state is GameState.UNKNOWN:
        return _action_required(session, "compatibility.game_state_unknown")
    directives = []
    if session.options.test_egpu_handoff:
        directives.append(CompatibilityTestDirective.OBSERVE_EGPU_HANDOFF)
    if session.options.test_save_exit:
        directives.append(CompatibilityTestDirective.OBSERVE_SAVE_EXIT)
    return replace(
        session,
        stage=CompatibilityTestStage.ACTIVE,
        directives=tuple(directives),
        baseline=baseline,
        observation_generations=(baseline.generation,),
        reason_code="compatibility.baseline_recorded",
    )


def record_egpu_handoff_result(
    session: CompatibilityTestSession,
    *,
    status: EgpuHandoffStatus,
    observed_render_gpu: ObservedRenderGpu,
    observation_generation: str,
    now_ms: int,
) -> CompatibilityTestSession:
    expired = _expired(session, now_ms)
    if expired is not None:
        return expired
    if session.stage is not CompatibilityTestStage.ACTIVE or not session.options.test_egpu_handoff:
        return _action_required(session, "compatibility.handoff_out_of_order")
    if session.egpu_handoff is not EgpuHandoffStatus.UNTESTED:
        return _action_required(session, "compatibility.handoff_already_recorded")
    if not _fresh_generation(session, observation_generation):
        return _action_required(session, "compatibility.handoff_observation_stale")
    if status in {EgpuHandoffStatus.VERIFIED, EgpuHandoffStatus.VERIFIED_WITH_WORKAROUND}:
        if observed_render_gpu is not ObservedRenderGpu.EXTERNAL:
            return _action_required(session, "compatibility.external_render_unverified")
    if status is EgpuHandoffStatus.FALLS_BACK_TO_IGPU:
        if observed_render_gpu is not ObservedRenderGpu.INTERNAL:
            return _action_required(session, "compatibility.internal_render_unverified")
    if status is EgpuHandoffStatus.UNTESTED:
        return _action_required(session, "compatibility.handoff_result_missing")
    return replace(
        session,
        egpu_handoff=status,
        observed_render_gpu=observed_render_gpu,
        observation_generations=(*session.observation_generations, observation_generation),
        reason_code="compatibility.handoff_recorded",
    )


def record_save_result(
    session: CompatibilityTestSession,
    *,
    outcome: SaveTestOutcome,
    observation_generation: str,
    now_ms: int,
) -> CompatibilityTestSession:
    expired = _expired(session, now_ms)
    if expired is not None:
        return expired
    if session.stage is not CompatibilityTestStage.ACTIVE or not session.options.test_save_exit:
        return _action_required(session, "compatibility.save_out_of_order")
    if session.save_outcome is not SaveTestOutcome.NOT_TESTED:
        return _action_required(session, "compatibility.save_already_recorded")
    if outcome is SaveTestOutcome.NOT_TESTED:
        return _action_required(session, "compatibility.save_result_missing")
    if not _fresh_generation(session, observation_generation):
        return _action_required(session, "compatibility.save_observation_stale")
    return replace(
        session,
        save_outcome=outcome,
        observation_generations=(*session.observation_generations, observation_generation),
        reason_code="compatibility.save_recorded",
    )


def finish_compatibility_test(
    session: CompatibilityTestSession,
    *,
    now_ms: int,
) -> CompatibilityTestSession:
    expired = _expired(session, now_ms)
    if expired is not None:
        return expired
    if session.stage is not CompatibilityTestStage.ACTIVE:
        return _action_required(session, "compatibility.finish_out_of_order")
    missing = []
    if session.options.test_egpu_handoff and session.egpu_handoff is EgpuHandoffStatus.UNTESTED:
        missing.append("compatibility.handoff_result_missing")
    if session.options.test_save_exit and session.save_outcome is SaveTestOutcome.NOT_TESTED:
        missing.append("compatibility.save_result_missing")
    if missing:
        return _action_required(session, missing[0])
    return replace(
        session,
        stage=CompatibilityTestStage.AWAITING_REVIEW,
        directives=(
            CompatibilityTestDirective.DISABLE_TEMP_DIAGNOSTICS,
            CompatibilityTestDirective.REVIEW_RESULTS,
        ),
        reason_code="compatibility.review_required",
    )


def review_compatibility_test(
    session: CompatibilityTestSession,
    *,
    evidence_id: str,
    tested_at: str,
    reviewer_confirmed: bool,
    now_ms: int,
) -> CompatibilityReviewResult:
    expired = _expired(session, now_ms)
    if expired is not None:
        raise ValueError("expired compatibility test cannot be reviewed")
    if session.stage is not CompatibilityTestStage.AWAITING_REVIEW:
        raise ValueError("compatibility test is not awaiting review")
    if not reviewer_confirmed:
        raise ValueError("compatibility result requires explicit review")
    completed = replace(
        session,
        stage=CompatibilityTestStage.COMPLETED,
        directives=(CompatibilityTestDirective.DISABLE_TEMP_DIAGNOSTICS,),
        reason_code="compatibility.review_completed",
    )
    return CompatibilityReviewResult(
        completed,
        CompatibilityEvidence(
            evidence_id=evidence_id,
            game_catalog_id=session.game_catalog_id,
            steam_app_id=session.baseline.steam_app_id,
            kind=session.evidence_kind,
            intentional_test=True,
            reviewed=True,
            host_profile_id=session.host_profile_id,
            egpu_profile_id=session.egpu_profile_id,
            regear_version=session.regear_version,
            steamos_version=session.steamos_version,
            tested_at=tested_at,
            observed_render_gpu=session.observed_render_gpu,
            save_outcome=session.save_outcome,
        ),
    )


def cancel_compatibility_test(
    session: CompatibilityTestSession,
    reason_code: str = "compatibility.cancelled",
) -> CompatibilityTestSession:
    return replace(
        session,
        stage=CompatibilityTestStage.CANCELLED,
        directives=(CompatibilityTestDirective.DISABLE_TEMP_DIAGNOSTICS,),
        reason_code=reason_code,
    )


def reconcile_compatibility_expiry(
    session: CompatibilityTestSession, *, now_ms: int
) -> CompatibilityTestSession:
    """Expire only a live test; terminal outcomes retain their exact reason."""
    if now_ms < 0:
        raise ValueError("compatibility test clock is invalid")
    if session.stage in {
        CompatibilityTestStage.AWAITING_REVIEW,
        CompatibilityTestStage.COMPLETED,
        CompatibilityTestStage.CANCELLED,
        CompatibilityTestStage.ACTION_REQUIRED,
    }:
        return session
    return (
        cancel_compatibility_test(session, "compatibility.expired")
        if now_ms >= session.expires_at_ms
        else session
    )


def require_compatibility_action(
    session: CompatibilityTestSession,
    reason_code: str,
    *,
    now_ms: int,
) -> CompatibilityTestSession:
    """Stop a live test on categorical application evidence failure."""
    expired = _expired(session, now_ms)
    if expired is not None:
        return expired
    if session.stage not in {
        CompatibilityTestStage.AWAITING_BASELINE,
        CompatibilityTestStage.ACTIVE,
    }:
        return _action_required(session, "compatibility.action_out_of_order")
    if not re.fullmatch(r"compatibility\.[a-z0-9_.-]{1,80}", reason_code):
        raise ValueError("compatibility action reason must be categorical")
    return _action_required(session, reason_code)


def _fresh_generation(session: CompatibilityTestSession, generation: str) -> bool:
    return bool(generation and generation not in session.observation_generations)


def _expired(
    session: CompatibilityTestSession, now_ms: int
) -> CompatibilityTestSession | None:
    if now_ms < 0:
        raise ValueError("compatibility test clock is invalid")
    if now_ms < session.expires_at_ms:
        return None
    return cancel_compatibility_test(session, "compatibility.expired")


def _action_required(
    session: CompatibilityTestSession, reason_code: str
) -> CompatibilityTestSession:
    return replace(
        session,
        stage=CompatibilityTestStage.ACTION_REQUIRED,
        directives=(
            CompatibilityTestDirective.DISABLE_TEMP_DIAGNOSTICS,
            CompatibilityTestDirective.ACTION_REQUIRED,
        ),
        reason_code=reason_code,
    )
