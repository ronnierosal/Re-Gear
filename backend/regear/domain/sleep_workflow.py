"""Pure canonical sleep/disconnect workflow policy.

This reducer never calls sleep, closes a game, signals a process, mutates a
display, or authorizes physical removal. It only emits typed directives whose
future mechanisms must independently verify their effects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from .control_plane import (
    EffectiveCapabilities,
    PlacementState,
    RemovalBehavior,
    SleepBehavior,
)
from .game_compatibility import GameSaveCapability, save_warning_required
from .models import (
    DisconnectReadinessObservation,
    EgpuClientKind,
    EgpuPresence,
    GameState,
)


REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{8,96}$")


class SleepFlowStage(StrEnum):
    NORMAL_SLEEP_ALLOWED = "normal_sleep_allowed"
    AWAITING_GAME_CONSENT = "awaiting_game_consent"
    CLOSING_GAME = "closing_game"
    RELEASING_CLIENTS = "releasing_clients"
    AWAITING_DISCONNECT = "awaiting_disconnect"
    SHUTDOWN_REQUIRED = "shutdown_required"
    RESTORING_PORTABLE = "restoring_portable"
    READY_TO_CONTINUE_SLEEP = "ready_to_continue_sleep"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ACTION_REQUIRED = "action_required"


class SleepFlowEvent(StrEnum):
    GAME_CONSENT_GRANTED = "game_consent_granted"
    GAME_CONSENT_DENIED = "game_consent_denied"
    GAME_EXIT_VERIFIED = "game_exit_verified"
    SOFTWARE_CLIENTS_RELEASED = "software_clients_released"
    EGPU_REMOVAL_VERIFIED = "egpu_removal_verified"
    PORTABLE_RECOVERY_VERIFIED = "portable_recovery_verified"
    ORIGINAL_SLEEP_CONTINUED = "original_sleep_continued"
    CANCEL = "cancel"


class SleepDirective(StrEnum):
    ALLOW_NORMAL_SLEEP = "allow_normal_sleep"
    KEEP_AWAKE = "keep_awake"
    PROMPT_CLOSE_GAME = "prompt_close_game"
    WARN_SAVE_UNVERIFIED = "warn_save_unverified"
    ATTEMPT_VERIFIED_SAVE = "attempt_verified_save"
    CLOSE_GAME_GRACEFULLY = "close_game_gracefully"
    PREVIEW_PROCESS_RELEASE = "preview_process_release"
    SHOW_SAFE_TO_DISCONNECT = "show_safe_to_disconnect"
    WAIT_FOR_REMOVAL = "wait_for_removal"
    SHUTDOWN_BEFORE_DISCONNECT = "shutdown_before_disconnect"
    RESTORE_PORTABLE = "restore_portable"
    CONTINUE_ORIGINAL_SLEEP = "continue_original_sleep"
    ACTION_REQUIRED = "action_required"


@dataclass(frozen=True, slots=True)
class SleepWorkflowContext:
    egpu_presence: EgpuPresence
    exact_egpu_identity_verified: bool
    capabilities: EffectiveCapabilities
    game_state: GameState
    save_capability: GameSaveCapability
    disconnect_readiness: DisconnectReadinessObservation
    placement: PlacementState
    removal_readiness_verified: bool = False


@dataclass(frozen=True, slots=True)
class SleepFlow:
    request_id: str
    stage: SleepFlowStage
    directives: tuple[SleepDirective, ...]
    original_request_pending: bool
    reason_code: str
    requested_at_ms: int
    expires_at_ms: int
    history: tuple[SleepFlowStage, ...] = field(default_factory=tuple)
    save_capability: GameSaveCapability = GameSaveCapability.UNTESTED

    def __post_init__(self) -> None:
        if not REQUEST_ID_RE.fullmatch(self.request_id):
            raise ValueError("sleep request ID is invalid")
        if len(self.history) > 32:
            raise ValueError("sleep workflow history exceeds its bound")
        if self.requested_at_ms < 0 or self.expires_at_ms <= self.requested_at_ms:
            raise ValueError("sleep request deadline is invalid")


def start_sleep_flow(
    request_id: str,
    context: SleepWorkflowContext,
    *,
    now_ms: int = 0,
    request_ttl_ms: int = 15 * 60 * 1000,
) -> SleepFlow:
    if not REQUEST_ID_RE.fullmatch(request_id):
        raise ValueError("sleep request ID is invalid")
    if now_ms < 0 or request_ttl_ms <= 0 or request_ttl_ms > 60 * 60 * 1000:
        raise ValueError("sleep request timing is invalid")
    deadline = (now_ms, now_ms + request_ttl_ms)
    if context.egpu_presence is EgpuPresence.ABSENT:
        return _flow(
            request_id,
            SleepFlowStage.NORMAL_SLEEP_ALLOWED,
            (SleepDirective.ALLOW_NORMAL_SLEEP,),
            True,
            "egpu.absent",
            timing=deadline,
        )
    if context.egpu_presence is EgpuPresence.UNKNOWN:
        return _action_required(request_id, "egpu.presence_unknown", timing=deadline)
    if not context.exact_egpu_identity_verified:
        return _action_required(request_id, "egpu.identity_unverified", timing=deadline)
    if context.capabilities.sleep_behavior is SleepBehavior.SLEEP_SAFE_VERIFIED:
        return _flow(
            request_id,
            SleepFlowStage.NORMAL_SLEEP_ALLOWED,
            (SleepDirective.ALLOW_NORMAL_SLEEP,),
            True,
            "egpu.sleep_safe_verified",
            timing=deadline,
        )
    if context.game_state is GameState.UNKNOWN:
        return _action_required(request_id, "game.state_unknown", timing=deadline)
    if context.game_state is GameState.RUNNING:
        directives = [SleepDirective.KEEP_AWAKE, SleepDirective.PROMPT_CLOSE_GAME]
        if save_warning_required(context.save_capability):
            directives.append(SleepDirective.WARN_SAVE_UNVERIFIED)
        return _flow(
            request_id,
            SleepFlowStage.AWAITING_GAME_CONSENT,
            tuple(directives),
            True,
            "game.consent_required",
            timing=deadline,
            save_capability=context.save_capability,
        )
    return _disconnect_step(request_id, context, (), deadline)


def advance_sleep_flow(
    flow: SleepFlow,
    event: SleepFlowEvent,
    context: SleepWorkflowContext,
    *,
    now_ms: int = 0,
) -> SleepFlow:
    history = (*flow.history, flow.stage)
    timing = (flow.requested_at_ms, flow.expires_at_ms)
    if flow.original_request_pending and now_ms >= flow.expires_at_ms:
        return _flow(
            flow.request_id,
            SleepFlowStage.CANCELLED,
            (SleepDirective.KEEP_AWAKE,),
            False,
            "sleep.request_expired",
            history,
            timing,
        )
    if event is SleepFlowEvent.CANCEL:
        return _flow(
            flow.request_id,
            SleepFlowStage.CANCELLED,
            (SleepDirective.KEEP_AWAKE,),
            False,
            "sleep.cancelled",
            history,
            timing,
        )
    if (
        flow.stage is SleepFlowStage.AWAITING_GAME_CONSENT
        and event is SleepFlowEvent.GAME_CONSENT_DENIED
    ):
        return _flow(
            flow.request_id,
            SleepFlowStage.CANCELLED,
            (SleepDirective.KEEP_AWAKE,),
            False,
            "game.consent_denied",
            history,
            timing,
        )
    if (
        flow.stage is SleepFlowStage.AWAITING_GAME_CONSENT
        and event is SleepFlowEvent.GAME_CONSENT_GRANTED
    ):
        directives = [SleepDirective.KEEP_AWAKE]
        if (
            flow.save_capability
            is GameSaveCapability.VERIFIED_TRIGGERABLE_AUTOSAVE
        ):
            directives.append(SleepDirective.ATTEMPT_VERIFIED_SAVE)
        directives.append(SleepDirective.CLOSE_GAME_GRACEFULLY)
        return _flow(
            flow.request_id,
            SleepFlowStage.CLOSING_GAME,
            tuple(directives),
            True,
            "game.close_requested",
            history,
            timing,
            flow.save_capability,
        )
    if (
        flow.stage is SleepFlowStage.CLOSING_GAME
        and event is SleepFlowEvent.GAME_EXIT_VERIFIED
    ):
        if context.game_state is not GameState.IDLE:
            return _action_required(
                flow.request_id, "game.exit_unverified", history, timing
            )
        return _disconnect_step(flow.request_id, context, history, timing)
    if (
        flow.stage is SleepFlowStage.RELEASING_CLIENTS
        and event is SleepFlowEvent.SOFTWARE_CLIENTS_RELEASED
    ):
        return _disconnect_step(flow.request_id, context, history, timing)
    if (
        flow.stage is SleepFlowStage.AWAITING_DISCONNECT
        and event is SleepFlowEvent.EGPU_REMOVAL_VERIFIED
    ):
        if (
            context.capabilities.removal_behavior
            is not RemovalBehavior.LIVE_REMOVAL_VERIFIED
            or context.egpu_presence is not EgpuPresence.ABSENT
        ):
            return _action_required(
                flow.request_id, "egpu.removal_unverified", history, timing
            )
        return _flow(
            flow.request_id,
            SleepFlowStage.RESTORING_PORTABLE,
            (SleepDirective.KEEP_AWAKE, SleepDirective.RESTORE_PORTABLE),
            True,
            "egpu.removed_restore_portable",
            history,
            timing,
        )
    if (
        flow.stage is SleepFlowStage.RESTORING_PORTABLE
        and event is SleepFlowEvent.PORTABLE_RECOVERY_VERIFIED
    ):
        if context.placement is not PlacementState.PORTABLE:
            return _action_required(
                flow.request_id, "portable.recovery_unverified", history, timing
            )
        return _flow(
            flow.request_id,
            SleepFlowStage.READY_TO_CONTINUE_SLEEP,
            (SleepDirective.CONTINUE_ORIGINAL_SLEEP,),
            True,
            "portable.recovery_verified",
            history,
            timing,
        )
    if (
        flow.stage is SleepFlowStage.READY_TO_CONTINUE_SLEEP
        and event is SleepFlowEvent.ORIGINAL_SLEEP_CONTINUED
    ):
        return _flow(
            flow.request_id,
            SleepFlowStage.COMPLETED,
            (),
            False,
            "sleep.original_request_continued",
            history,
            timing,
        )
    return _action_required(
        flow.request_id,
        "sleep.event_invalid",
        history,
        timing,
        original_request_pending=flow.original_request_pending,
    )


def _disconnect_step(
    request_id: str,
    context: SleepWorkflowContext,
    history: tuple[SleepFlowStage, ...],
    timing: tuple[int, int],
) -> SleepFlow:
    if context.game_state is GameState.UNKNOWN:
        return _action_required(request_id, "game.state_unknown", history, timing)
    if context.game_state is GameState.RUNNING:
        return _action_required(
            request_id,
            "game.started_during_disconnect",
            history,
            timing,
        )
    readiness = context.disconnect_readiness
    if not readiness.applicable or not readiness.scan_complete:
        return _action_required(request_id, "disconnect.scan_incomplete", history, timing)
    if readiness.storage_in_use:
        return _action_required(request_id, "disconnect.storage_in_use", history, timing)
    if any(client.kind is EgpuClientKind.GAME for client in readiness.clients):
        return _action_required(request_id, "disconnect.game_client_present", history, timing)
    eligible = tuple(client for client in readiness.clients if client.close_eligible)
    protected = tuple(client for client in readiness.clients if not client.close_eligible)
    if protected:
        return _action_required(request_id, "disconnect.protected_client", history, timing)
    if eligible:
        return _flow(
            request_id,
            SleepFlowStage.RELEASING_CLIENTS,
            (SleepDirective.KEEP_AWAKE, SleepDirective.PREVIEW_PROCESS_RELEASE),
            True,
            "disconnect.release_clients",
            history,
            timing,
        )
    if context.capabilities.removal_behavior is RemovalBehavior.LIVE_REMOVAL_VERIFIED:
        if not context.removal_readiness_verified:
            return _action_required(
                request_id,
                "disconnect.removal_readiness_unverified",
                history,
                timing,
            )
        return _flow(
            request_id,
            SleepFlowStage.AWAITING_DISCONNECT,
            (
                SleepDirective.KEEP_AWAKE,
                SleepDirective.SHOW_SAFE_TO_DISCONNECT,
                SleepDirective.WAIT_FOR_REMOVAL,
            ),
            True,
            "disconnect.live_removal_verified",
            history,
            timing,
        )
    if (
        context.capabilities.removal_behavior
        is RemovalBehavior.SHUTDOWN_BEFORE_DISCONNECT
    ):
        return _flow(
            request_id,
            SleepFlowStage.SHUTDOWN_REQUIRED,
            (
                SleepDirective.KEEP_AWAKE,
                SleepDirective.SHUTDOWN_BEFORE_DISCONNECT,
            ),
            False,
            "disconnect.shutdown_required",
            history,
            timing,
        )
    return _action_required(
        request_id, "disconnect.removal_capability_unknown", history, timing
    )


def _action_required(
    request_id: str,
    reason_code: str,
    history: tuple[SleepFlowStage, ...] = (),
    timing: tuple[int, int] = (0, 15 * 60 * 1000),
    *,
    original_request_pending: bool = True,
) -> SleepFlow:
    return _flow(
        request_id,
        SleepFlowStage.ACTION_REQUIRED,
        (SleepDirective.KEEP_AWAKE, SleepDirective.ACTION_REQUIRED),
        original_request_pending,
        reason_code,
        history,
        timing,
    )


def _flow(
    request_id: str,
    stage: SleepFlowStage,
    directives: tuple[SleepDirective, ...],
    original_request_pending: bool,
    reason_code: str,
    history: tuple[SleepFlowStage, ...] = (),
    timing: tuple[int, int] = (0, 15 * 60 * 1000),
    save_capability: GameSaveCapability = GameSaveCapability.UNTESTED,
) -> SleepFlow:
    return SleepFlow(
        request_id=request_id,
        stage=stage,
        directives=directives,
        original_request_pending=original_request_pending,
        reason_code=reason_code,
        requested_at_ms=timing[0],
        expires_at_ms=timing[1],
        history=history,
        save_capability=save_capability,
    )
