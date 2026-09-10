"""Guarded, dormant application coordinator for unexpected topology loss."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from enum import StrEnum

from ..domain.control_plane import (
    PlacementState,
    TransitionOutcomeKind,
    WorkflowState,
)
from ..domain.event_policy import (
    RecoveryDirective,
    TopologyEvent,
    decide_topology_event,
)
from ..domain.inference import infer_placement
from ..domain.models import (
    Confidence,
    DisplayKind,
    GameState,
    GpuRole,
    ObservedSnapshot,
)
from ..ports.runtime_transition import DeadlineWaitPort
from ..ports.transition import (
    MonotonicClockPort,
    TransitionObservationPort,
    VersionedObservation,
)
from ..ports.unexpected_undock import (
    UnexpectedUndockBinding,
    UnexpectedUndockRecoveryMechanismPort,
)
from ..profiles.registry import resolve_runtime_profiles


POLL_MS = 100
MAX_DEADLINE_MS = 60_000
SAFE_ID = re.compile(r"^[a-zA-Z0-9_.:-]{1,96}$")
UNKNOWN_INVENTORY_BLOCKERS = frozenset(
    {
        "drm_inventory_unavailable",
        "egpu_identity_unverified",
    }
)


class LossOrigin(StrEnum):
    UNSOLICITED = "unsolicited"
    CANONICAL_SLEEP_PENDING = "canonical_sleep_pending"


class RecoveryStage(StrEnum):
    DETECTED = "detected"
    VALIDATED = "validated"
    ATTEMPTED = "attempted"
    VERIFIED = "verified"
    FALLBACK_ATTEMPTED = "fallback_attempted"
    FALLBACK_VERIFIED = "fallback_verified"
    COMMITTED = "committed"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RecoveryTraceEvent:
    sequence: int
    stage: RecoveryStage
    code: str
    placement: PlacementState

    def __post_init__(self) -> None:
        if self.sequence <= 0:
            raise ValueError("recovery trace sequence must be positive")
        if not SAFE_ID.fullmatch(self.code):
            raise ValueError("recovery trace code must be categorical")


@dataclass(frozen=True, slots=True)
class UnexpectedUndockRequest:
    request_id: str
    event: TopologyEvent
    workflow: WorkflowState
    trigger_generation: str
    trigger_sample_id: str
    canonical_sleep_operation_id: str = ""
    verification_deadline_ms: int = 10_000
    fallback_deadline_ms: int = 10_000

    def __post_init__(self) -> None:
        if not SAFE_ID.fullmatch(self.request_id):
            raise ValueError("unexpected-undock request ID must be categorical")
        if not self.trigger_generation or not self.trigger_sample_id:
            raise ValueError("unexpected-undock trigger identity is required")
        if not 0 < self.verification_deadline_ms <= MAX_DEADLINE_MS:
            raise ValueError("unexpected-undock verification deadline is invalid")
        if not 0 < self.fallback_deadline_ms <= MAX_DEADLINE_MS:
            raise ValueError("unexpected-undock fallback deadline is invalid")
        if self.canonical_sleep_operation_id and not SAFE_ID.fullmatch(
            self.canonical_sleep_operation_id
        ):
            raise ValueError("canonical sleep operation ID must be categorical")


@dataclass(frozen=True, slots=True)
class UnexpectedUndockResult:
    kind: TransitionOutcomeKind
    origin: LossOrigin
    placement: PlacementState
    workflow_state: WorkflowState
    reason_code: str
    trace: tuple[RecoveryTraceEvent, ...]
    usable_path_preserved: bool = False
    canonical_sleep_recheck_required: bool = False

    @property
    def authorizes_sleep(self) -> bool:
        """A raw topology-event coordinator can never authorize sleep."""
        return False


class UnexpectedUndockRecoveryCoordinator:
    """Recover Portable without owning or advancing canonical sleep state."""

    def __init__(
        self,
        *,
        observations: TransitionObservationPort,
        mechanism: UnexpectedUndockRecoveryMechanismPort,
        clock: MonotonicClockPort,
        waiter: DeadlineWaitPort,
    ) -> None:
        self._observations = observations
        self._mechanism = mechanism
        self._clock = clock
        self._waiter = waiter
        self._lock = threading.Lock()

    def run(self, request: UnexpectedUndockRequest) -> UnexpectedUndockResult:
        origin = self._origin(request)
        if not self._lock.acquire(blocking=False):
            return self._result(
                TransitionOutcomeKind.BLOCKED,
                origin,
                PlacementState.UNKNOWN,
                WorkflowState.ACTION_REQUIRED,
                "recovery.concurrent_request",
                [
                    RecoveryTraceEvent(
                        1,
                        RecoveryStage.BLOCKED,
                        "recovery.concurrent_request",
                        PlacementState.UNKNOWN,
                    )
                ],
            )
        try:
            return self._run_locked(request, origin)
        finally:
            self._lock.release()

    def _run_locked(
        self, request: UnexpectedUndockRequest, origin: LossOrigin
    ) -> UnexpectedUndockResult:
        trace: list[RecoveryTraceEvent] = []
        transaction_blocker = self._transaction_blocker(request)
        if transaction_blocker:
            return self._blocked(
                origin, PlacementState.UNKNOWN, transaction_blocker, trace
            )
        if request.event not in {
            TopologyEvent.EGPU_REMOVED,
            TopologyEvent.EXTERNAL_DISPLAY_LOST,
        }:
            return self._blocked(
                origin, PlacementState.UNKNOWN, "event.not_recovery_loss", trace
            )

        trigger = self._observe()
        if trigger is None:
            return self._blocked(
                origin, PlacementState.UNKNOWN, "observation.unavailable", trace
            )
        trigger_placement = infer_placement(trigger.snapshot)
        self._append(trace, RecoveryStage.DETECTED, "recovery.loss_detected", trigger_placement)
        if (
            trigger.generation != request.trigger_generation
            or trigger.sample_id != request.trigger_sample_id
        ):
            return self._blocked(
                origin, trigger_placement, "observation.stale_trigger", trace
            )

        decision = decide_topology_event(
            event=request.event,
            placement=trigger_placement,
            workflow=request.workflow,
        )
        if decision.directives == (RecoveryDirective.OBSERVE_STABILITY,):
            return self._verify_no_op(request, origin, trigger, trace)
        if decision.directives != (RecoveryDirective.RECOVER_PORTABLE,):
            return self._blocked(origin, trigger_placement, decision.reason_code, trace)

        binding, blocker = self._binding(trigger.snapshot, request.event)
        if blocker:
            return self._blocked(origin, trigger_placement, blocker, trace)

        before = self._next_fresh(
            trigger.sample_id, request.verification_deadline_ms
        )
        if before is None:
            return self._blocked(
                origin, trigger_placement, "observation.fresh_sample_timeout", trace
            )
        if before.generation == trigger.generation:
            return self._blocked(
                origin,
                infer_placement(before.snapshot),
                "observation.loss_not_correlated",
                trace,
            )
        blocker = self._recovery_blocker(binding, before.snapshot)
        if blocker:
            return self._blocked(
                origin, infer_placement(before.snapshot), blocker, trace
            )
        self._append(
            trace,
            RecoveryStage.VALIDATED,
            "recovery.loss_validated",
            infer_placement(before.snapshot),
        )
        self._append(
            trace,
            RecoveryStage.ATTEMPTED,
            "recovery.portable_attempted",
            infer_placement(before.snapshot),
        )
        try:
            attempted = self._mechanism.restore_portable(
                binding, before.snapshot, request.verification_deadline_ms
            )
        except Exception:
            attempted = None
        if attempted is None:
            return self._fallback(
                request,
                origin,
                binding,
                before,
                "mechanism.exception",
                trace,
            )
        if not attempted.succeeded:
            return self._fallback(
                request, origin, binding, before, attempted.code, trace
            )

        verified, last = self._poll(
            prior_sample_id=before.sample_id,
            deadline_ms=request.verification_deadline_ms,
            predicate=lambda value: self._portable_verified(binding, value.snapshot),
        )
        if verified is None:
            return self._fallback(
                request,
                origin,
                binding,
                last or before,
                "recovery.portable_verification_timeout",
                trace,
            )
        self._append(
            trace,
            RecoveryStage.VERIFIED,
            "recovery.portable_verified",
            PlacementState.PORTABLE,
        )
        self._append(
            trace,
            RecoveryStage.COMMITTED,
            "recovery.portable_committed",
            PlacementState.PORTABLE,
        )
        return self._successful(
            TransitionOutcomeKind.SUCCEEDED,
            origin,
            "recovery.portable_committed",
            trace,
        )

    def _verify_no_op(self, request, origin, trigger, trace):
        verified, _last = self._poll(
            prior_sample_id=trigger.sample_id,
            deadline_ms=request.verification_deadline_ms,
            predicate=lambda value: infer_placement(value.snapshot)
            is PlacementState.PORTABLE,
        )
        if verified is None:
            return self._blocked(
                origin,
                PlacementState.PORTABLE,
                "recovery.portable_stability_timeout",
                trace,
            )
        self._append(
            trace,
            RecoveryStage.VALIDATED,
            "recovery.portable_stable",
            PlacementState.PORTABLE,
        )
        self._append(
            trace,
            RecoveryStage.VERIFIED,
            "recovery.portable_verified",
            PlacementState.PORTABLE,
        )
        self._append(
            trace,
            RecoveryStage.COMMITTED,
            "recovery.portable_no_op",
            PlacementState.PORTABLE,
        )
        return self._successful(
            TransitionOutcomeKind.NO_OP,
            origin,
            "recovery.portable_no_op",
            trace,
        )

    def _fallback(self, request, origin, binding, last, reason, trace):
        placement = infer_placement(last.snapshot) if last is not None else PlacementState.UNKNOWN
        self._append(
            trace,
            RecoveryStage.FALLBACK_ATTEMPTED,
            "recovery.usable_fallback_attempted",
            placement,
        )
        try:
            fallback = self._mechanism.preserve_portable_path(
                binding,
                last.snapshot if last is not None else None,
                request.fallback_deadline_ms,
            )
        except Exception:
            fallback = None
        if fallback is None or not fallback.succeeded:
            code = "recovery.fallback_exception" if fallback is None else fallback.code
            self._append(trace, RecoveryStage.FAILED, code, placement)
            return self._result(
                TransitionOutcomeKind.FAILED,
                origin,
                placement,
                WorkflowState.ACTION_REQUIRED,
                reason,
                trace,
            )

        verified, _last = self._poll(
            prior_sample_id=last.sample_id if last is not None else "",
            deadline_ms=request.fallback_deadline_ms,
            predicate=lambda value: self._portable_verified(binding, value.snapshot),
        )
        if verified is None:
            self._append(
                trace,
                RecoveryStage.FAILED,
                "recovery.fallback_verification_timeout",
                placement,
            )
            return self._result(
                TransitionOutcomeKind.FAILED,
                origin,
                placement,
                WorkflowState.ACTION_REQUIRED,
                reason,
                trace,
            )
        recovered = PlacementState.PORTABLE
        self._append(
            trace,
            RecoveryStage.FALLBACK_VERIFIED,
            "recovery.usable_fallback_verified",
            recovered,
        )
        self._append(
            trace,
            RecoveryStage.COMMITTED,
            "recovery.portable_recovered",
            recovered,
        )
        return self._successful(
            TransitionOutcomeKind.RECOVERED,
            origin,
            reason,
            trace,
            usable_path_preserved=True,
        )

    def _binding(self, snapshot, event):
        profiles = resolve_runtime_profiles(snapshot)
        if not profiles.exact_host:
            return None, "identity.host_unverified"
        if not profiles.exact_egpu:
            return None, "identity.egpu_unverified"
        if snapshot.game_state is not GameState.IDLE:
            return None, self._game_blocker(snapshot)
        if not self._gamescope_healthy(snapshot):
            return None, "gamescope.state_unverified"
        internal_gpus = tuple(
            gpu
            for gpu in snapshot.gpus
            if gpu.role is GpuRole.INTERNAL
            and gpu.present
            and gpu.confidence is Confidence.VERIFIED
        )
        internal_displays = tuple(
            display
            for display in snapshot.displays
            if display.kind is DisplayKind.INTERNAL
            and display.connected is True
            and display.confidence is Confidence.VERIFIED
        )
        if len(internal_gpus) != 1:
            return None, "identity.internal_gpu_unverified"
        if len(internal_displays) != 1:
            return None, "identity.internal_display_unverified"
        if event is TopologyEvent.EGPU_REMOVED:
            lost = tuple(
                gpu
                for gpu in snapshot.gpus
                if gpu.role is GpuRole.EXTERNAL
                and gpu.present
                and gpu.confidence is Confidence.VERIFIED
                and gpu.stable_id == profiles.egpu_stable_id
            )
        else:
            lost = tuple(
                display
                for display in snapshot.displays
                if display.kind is DisplayKind.EXTERNAL
                and display.connected is True
                and display.active is True
                and display.confidence is Confidence.VERIFIED
            )
        if len(lost) != 1:
            return None, "identity.lost_resource_unverified"
        return (
            UnexpectedUndockBinding(
                event=event,
                host_profile_id=profiles.capabilities.host_profile_id,
                egpu_profile_id=profiles.capabilities.egpu_profile_id,
                egpu_stable_id=profiles.egpu_stable_id,
                internal_gpu_stable_id=internal_gpus[0].stable_id,
                internal_display_stable_id=internal_displays[0].stable_id,
                lost_resource_stable_id=lost[0].stable_id,
            ),
            "",
        )

    def _recovery_blocker(self, binding, snapshot):
        if snapshot.host_profile != binding.host_profile_id:
            return "identity.host_changed"
        if snapshot.game_state is not GameState.IDLE:
            return self._game_blocker(snapshot)
        if not self._gamescope_healthy(snapshot):
            return "gamescope.state_unverified"
        if not self._exact_internal_path(binding, snapshot):
            return "recovery.internal_path_unverified"
        if not self._loss_verified(binding, snapshot):
            return "recovery.loss_unverified"
        if not self._egpu_identity_valid_for_event(binding, snapshot):
            return "identity.egpu_changed"
        return ""

    @staticmethod
    def _game_blocker(snapshot):
        return (
            "game.state_unknown"
            if snapshot.game_state is GameState.UNKNOWN
            else "game.running"
        )

    @staticmethod
    def _gamescope_healthy(snapshot):
        return bool(
            snapshot.gamescope.running is True
            and snapshot.gamescope.confidence is Confidence.VERIFIED
        )

    @staticmethod
    def _exact_internal_path(binding, snapshot):
        gpus = tuple(
            gpu
            for gpu in snapshot.gpus
            if gpu.stable_id == binding.internal_gpu_stable_id
            and gpu.role is GpuRole.INTERNAL
            and gpu.present
            and gpu.confidence is Confidence.VERIFIED
        )
        displays = tuple(
            display
            for display in snapshot.displays
            if display.stable_id == binding.internal_display_stable_id
            and display.kind is DisplayKind.INTERNAL
            and display.connected is True
            and display.confidence is Confidence.VERIFIED
        )
        return len(gpus) == 1 and len(displays) == 1

    @classmethod
    def _loss_verified(cls, binding, snapshot):
        if any(
            blocker.code in UNKNOWN_INVENTORY_BLOCKERS
            for blocker in snapshot.blockers
        ):
            return False
        if binding.event is TopologyEvent.EGPU_REMOVED:
            matches = tuple(
                gpu
                for gpu in snapshot.gpus
                if gpu.stable_id == binding.lost_resource_stable_id
            )
            if len(matches) > 1:
                return False
            if matches:
                return bool(
                    matches[0].role is GpuRole.EXTERNAL
                    and matches[0].present is False
                    and matches[0].confidence is Confidence.VERIFIED
                )
            return not any(
                gpu.role is GpuRole.EXTERNAL
                and (gpu.present or gpu.confidence is not Confidence.VERIFIED)
                for gpu in snapshot.gpus
            )
        matches = tuple(
            display
            for display in snapshot.displays
            if display.stable_id == binding.lost_resource_stable_id
        )
        if len(matches) > 1:
            return False
        if matches and not (
            matches[0].kind is DisplayKind.EXTERNAL
            and matches[0].connected is False
            and matches[0].confidence is Confidence.VERIFIED
        ):
            return False
        return not any(
            display.kind is DisplayKind.EXTERNAL
            and (
                display.active is True
                or display.connected is not False
                or display.confidence is not Confidence.VERIFIED
            )
            for display in snapshot.displays
        )

    @classmethod
    def _portable_verified(cls, binding, snapshot):
        return bool(
            snapshot.game_state is GameState.IDLE
            and snapshot.host_profile == binding.host_profile_id
            and cls._exact_internal_path(binding, snapshot)
            and cls._loss_verified(binding, snapshot)
            and cls._egpu_identity_valid_for_event(binding, snapshot)
            and infer_placement(snapshot) is PlacementState.PORTABLE
        )

    @staticmethod
    def _egpu_identity_valid_for_event(binding, snapshot):
        if binding.event is TopologyEvent.EGPU_REMOVED:
            return True
        profiles = resolve_runtime_profiles(snapshot)
        return bool(
            profiles.exact_egpu
            and profiles.capabilities.egpu_profile_id == binding.egpu_profile_id
            and profiles.egpu_stable_id == binding.egpu_stable_id
        )

    def _next_fresh(self, prior_sample_id, deadline_ms):
        matched, _last = self._poll(
            prior_sample_id=prior_sample_id,
            deadline_ms=deadline_ms,
            predicate=lambda _value: True,
        )
        return matched

    def _poll(self, *, prior_sample_id, deadline_ms, predicate):
        try:
            started = self._clock.now_ms()
        except Exception:
            return None, None
        seen = {prior_sample_id} if prior_sample_id else set()
        last = None
        while True:
            try:
                elapsed = self._clock.now_ms() - started
            except Exception:
                return None, last
            if elapsed < 0 or elapsed > deadline_ms:
                return None, last
            observed = self._observe()
            if observed is not None and observed.sample_id not in seen:
                seen.add(observed.sample_id)
                last = observed
                if predicate(observed):
                    return observed, last
            try:
                remaining = deadline_ms - (self._clock.now_ms() - started)
            except Exception:
                return None, last
            if remaining <= 0:
                return None, last
            try:
                self._waiter.wait_ms(min(POLL_MS, remaining))
            except Exception:
                return None, last

    def _observe(self) -> VersionedObservation | None:
        try:
            return self._observations.observe()
        except Exception:
            return None

    @staticmethod
    def _origin(request):
        return (
            LossOrigin.CANONICAL_SLEEP_PENDING
            if request.workflow is WorkflowState.SLEEP_PENDING_DISCONNECT
            else LossOrigin.UNSOLICITED
        )

    @staticmethod
    def _transaction_blocker(request):
        if (
            request.workflow is WorkflowState.SLEEP_PENDING_DISCONNECT
            and not request.canonical_sleep_operation_id
        ):
            return "sleep.transaction_identity_missing"
        if (
            request.workflow is not WorkflowState.SLEEP_PENDING_DISCONNECT
            and request.canonical_sleep_operation_id
        ):
            return "sleep.transaction_identity_unexpected"
        return ""

    @staticmethod
    def _workflow_after_success(origin):
        return (
            WorkflowState.SLEEP_PENDING_DISCONNECT
            if origin is LossOrigin.CANONICAL_SLEEP_PENDING
            else WorkflowState.IDLE
        )

    def _successful(
        self,
        kind,
        origin,
        reason,
        trace,
        *,
        usable_path_preserved=False,
    ):
        return self._result(
            kind,
            origin,
            PlacementState.PORTABLE,
            self._workflow_after_success(origin),
            reason,
            trace,
            usable_path_preserved=usable_path_preserved,
            canonical_sleep_recheck_required=(
                origin is LossOrigin.CANONICAL_SLEEP_PENDING
            ),
        )

    def _blocked(self, origin, placement, code, trace):
        self._append(trace, RecoveryStage.BLOCKED, code, placement)
        return self._result(
            TransitionOutcomeKind.BLOCKED,
            origin,
            placement,
            WorkflowState.ACTION_REQUIRED,
            code,
            trace,
        )

    @staticmethod
    def _append(trace, stage, code, placement):
        trace.append(RecoveryTraceEvent(len(trace) + 1, stage, code, placement))

    @staticmethod
    def _result(
        kind,
        origin,
        placement,
        workflow,
        reason,
        trace,
        *,
        usable_path_preserved=False,
        canonical_sleep_recheck_required=False,
    ):
        return UnexpectedUndockResult(
            kind=kind,
            origin=origin,
            placement=placement,
            workflow_state=workflow,
            reason_code=reason,
            trace=tuple(trace),
            usable_path_preserved=usable_path_preserved,
            canonical_sleep_recheck_required=canonical_sleep_recheck_required,
        )
