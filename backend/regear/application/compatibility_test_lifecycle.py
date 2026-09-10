"""One-owner lifecycle for the dormant, non-mutating Compatibility Test Mode.

This coordinates pure session policy with temporary diagnostic logging. It has
no Decky RPC, catalog writer, game mechanism, or hardware-transition authority.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol

from ..domain.compatibility_test import (
    CompatibilityBaseline,
    CompatibilityTestOptions,
    CompatibilityTestSession,
    CompatibilityTestStage,
    cancel_compatibility_test,
    finish_compatibility_test,
    record_compatibility_baseline,
    record_egpu_handoff_result,
    record_save_result,
    reconcile_compatibility_expiry,
    require_compatibility_action,
    start_compatibility_test,
)
from ..domain.game_compatibility import (
    CompatibilityEvidenceKind,
    EgpuHandoffStatus,
    ObservedRenderGpu,
    SaveTestOutcome,
)
from ..ports.transition import MonotonicClockPort
from .diagnostic_logging import (
    DiagnosticLoggingController,
    DiagnosticLoggingDuration,
)
from .compatibility_baseline import CompatibilityBaselineCapture
from .compatibility_save_exit import (
    CompatibilitySaveExitCapture,
    CompatibilitySaveExitWatch,
)


class CompatibilityHardwareAuthorizationPort(Protocol):
    """Trusted-runner boundary; never represent this as a frontend boolean."""

    def hardware_test_authorized(self) -> bool: ...


class CompatibilitySessionIdPort(Protocol):
    def new_session_id(self) -> str: ...


class CompatibilityBaselinePort(Protocol):
    def capture(self, *, user_uid: int) -> CompatibilityBaselineCapture: ...


class CompatibilityUserContextPort(Protocol):
    def current_user_uid(self) -> int: ...


class CompatibilityExternalHandoffPort(Protocol):
    def capture_external_handoff(
        self,
        session: CompatibilityTestSession,
        *,
        user_uid: int,
        now_ms: int,
    ) -> CompatibilityTestSession: ...


class CompatibilitySaveExitPort(Protocol):
    """Read-only observer for a player-initiated game exit."""

    def arm(
        self, session: CompatibilityTestSession
    ) -> CompatibilitySaveExitWatch | None: ...

    def capture(
        self,
        session: CompatibilityTestSession,
        watch: CompatibilitySaveExitWatch,
    ) -> CompatibilitySaveExitCapture: ...


@dataclass(frozen=True, slots=True)
class CompatibilityTestStart:
    options: CompatibilityTestOptions
    evidence_kind: CompatibilityEvidenceKind
    game_catalog_id: str
    host_profile_id: str
    egpu_profile_id: str
    regear_version: str
    steamos_version: str


class CompatibilityTestLifecycle:
    """Serialize one ephemeral session and honor its logging directives exactly."""

    def __init__(
        self,
        *,
        diagnostics: DiagnosticLoggingController,
        clock: MonotonicClockPort,
        session_ids: CompatibilitySessionIdPort,
        hardware_authorization: CompatibilityHardwareAuthorizationPort,
        baseline_collector: CompatibilityBaselinePort | None = None,
        external_handoff_collector: CompatibilityExternalHandoffPort | None = None,
        save_exit_collector: CompatibilitySaveExitPort | None = None,
        user_context: CompatibilityUserContextPort | None = None,
    ) -> None:
        self._diagnostics = diagnostics
        self._clock = clock
        self._session_ids = session_ids
        self._hardware_authorization = hardware_authorization
        self._baseline_collector = baseline_collector
        self._external_handoff_collector = external_handoff_collector
        self._save_exit_collector = save_exit_collector
        self._user_context = user_context
        self._session: CompatibilityTestSession | None = None
        self._save_exit_watch: CompatibilitySaveExitWatch | None = None
        self._lock = threading.Lock()

    def status(self) -> CompatibilityTestSession | None:
        with self._lock:
            self._reconcile_locked()
            return self._session

    def start(
        self, request: CompatibilityTestStart, *, user_confirmed: bool
    ) -> CompatibilityTestSession:
        with self._lock:
            self._reconcile_locked()
            if self._is_live_locked():
                raise ValueError("compatibility test session is already active")
            authorized = self._hardware_authorized_locked(request.evidence_kind)
            self._session = start_compatibility_test(
                session_id=self._session_ids.new_session_id(),
                options=request.options,
                evidence_kind=request.evidence_kind,
                game_catalog_id=request.game_catalog_id,
                host_profile_id=request.host_profile_id,
                egpu_profile_id=request.egpu_profile_id,
                regear_version=request.regear_version,
                steamos_version=request.steamos_version,
                user_confirmed=user_confirmed,
                hardware_test_authorized=authorized,
                now_ms=self._now_locked(),
            )
            self._save_exit_watch = None
            self._apply_logging_directives_locked()
            return self._session

    def record_baseline(
        self, baseline: CompatibilityBaseline
    ) -> CompatibilityTestSession | None:
        return self._advance(lambda session, now: record_compatibility_baseline(
            session, baseline, now_ms=now
        ))

    def capture_observed_baseline(self) -> CompatibilityTestSession | None:
        """Capture through injected read-only ports; delivery never supplies identity."""
        with self._lock:
            self._reconcile_locked()
            if self._session is None:
                return None
            if self._session.stage is not CompatibilityTestStage.AWAITING_BASELINE:
                return self._session
            capture = self._capture_baseline_locked()
            now = self._now_locked()
            self._session = (
                record_compatibility_baseline(
                    self._session, capture.baseline, now_ms=now
                )
                if capture.accepted and capture.baseline is not None
                else require_compatibility_action(
                    self._session, capture.code, now_ms=now
                )
            )
            self._apply_logging_directives_locked()
            return self._session

    def record_egpu_handoff(
        self,
        *,
        status: EgpuHandoffStatus,
        observed_render_gpu: ObservedRenderGpu,
        observation_generation: str,
    ) -> CompatibilityTestSession | None:
        return self._advance(lambda session, now: record_egpu_handoff_result(
            session,
            status=status,
            observed_render_gpu=observed_render_gpu,
            observation_generation=observation_generation,
            now_ms=now,
        ))

    def capture_observed_egpu_handoff(self) -> CompatibilityTestSession | None:
        """Use injected read-only evidence; delivery cannot supply game identity."""
        with self._lock:
            self._reconcile_locked()
            if self._session is None:
                return None
            if (
                self._session.stage is not CompatibilityTestStage.ACTIVE
                or not self._session.options.test_egpu_handoff
            ):
                return self._session
            if self._external_handoff_collector is None or self._user_context is None:
                self._session = require_compatibility_action(
                    self._session,
                    "compatibility.external_observer_unavailable",
                    now_ms=self._now_locked(),
                )
            else:
                self._session = self._capture_external_handoff_locked()
            self._apply_logging_directives_locked()
            return self._session

    def record_save(
        self,
        *,
        outcome: SaveTestOutcome,
        observation_generation: str,
    ) -> CompatibilityTestSession | None:
        return self._advance(lambda session, now: record_save_result(
            session,
            outcome=outcome,
            observation_generation=observation_generation,
            now_ms=now,
        ))

    def arm_observed_save_exit(self) -> CompatibilityTestSession | None:
        """Arm a read-only watch; this method never signals or saves a game."""
        with self._lock:
            self._reconcile_locked()
            if self._session is None:
                return None
            if (
                self._session.stage is not CompatibilityTestStage.ACTIVE
                or not self._session.options.test_save_exit
            ):
                return self._session
            if self._save_exit_collector is None:
                self._session = require_compatibility_action(
                    self._session,
                    "compatibility.save_exit_observer_unavailable",
                    now_ms=self._now_locked(),
                )
            else:
                try:
                    self._save_exit_watch = self._save_exit_collector.arm(self._session)
                except Exception:
                    self._save_exit_watch = None
                if self._save_exit_watch is None:
                    self._session = require_compatibility_action(
                        self._session,
                        "compatibility.save_exit_arm_unverified",
                        now_ms=self._now_locked(),
                    )
            self._apply_logging_directives_locked()
            return self._session

    def capture_observed_save_exit(self) -> CompatibilityTestSession | None:
        """Record only a fresh observed idle result from a prior read-only watch."""
        with self._lock:
            self._reconcile_locked()
            if self._session is None:
                return None
            if (
                self._session.stage is not CompatibilityTestStage.ACTIVE
                or not self._session.options.test_save_exit
            ):
                return self._session
            if self._save_exit_collector is None or self._save_exit_watch is None:
                self._session = require_compatibility_action(
                    self._session,
                    "compatibility.save_exit_observer_unavailable",
                    now_ms=self._now_locked(),
                )
            else:
                try:
                    result = self._save_exit_collector.capture(
                        self._session, self._save_exit_watch
                    )
                except Exception:
                    result = None
                self._save_exit_watch = None
                self._session = (
                    record_save_result(
                        self._session,
                        outcome=result.outcome,
                        observation_generation=result.observation_generation,
                        now_ms=self._now_locked(),
                    )
                    if isinstance(result, CompatibilitySaveExitCapture) and result.accepted
                    else require_compatibility_action(
                        self._session,
                        (
                            result.code
                            if isinstance(result, CompatibilitySaveExitCapture)
                            else "compatibility.save_exit_observer_unavailable"
                        ),
                        now_ms=self._now_locked(),
                    )
                )
            self._apply_logging_directives_locked()
            return self._session

    def finish(self) -> CompatibilityTestSession | None:
        return self._advance(
            lambda session, now: finish_compatibility_test(session, now_ms=now)
        )

    def cancel(self) -> CompatibilityTestSession | None:
        with self._lock:
            self._reconcile_locked()
            if not self._is_live_locked():
                return self._session
            self._session = cancel_compatibility_test(self._session)
            self._apply_logging_directives_locked()
            return self._session

    def _advance(self, action) -> CompatibilityTestSession | None:
        with self._lock:
            self._reconcile_locked()
            if not self._is_live_locked():
                return self._session
            self._session = action(self._session, self._now_locked())
            self._apply_logging_directives_locked()
            return self._session

    def _reconcile_locked(self) -> None:
        if self._session is None:
            return
        self._session = reconcile_compatibility_expiry(
            self._session, now_ms=self._now_locked()
        )
        self._apply_logging_directives_locked()

    def _apply_logging_directives_locked(self) -> None:
        if self._session is None:
            return
        if self._session.stage is CompatibilityTestStage.AWAITING_BASELINE:
            if not self._diagnostics.status().enabled:
                self._diagnostics.enable(
                    DiagnosticLoggingDuration.HOURS_2, user_confirmed=True
                )
            return
        if self._session.stage in {
            CompatibilityTestStage.AWAITING_REVIEW,
            CompatibilityTestStage.COMPLETED,
            CompatibilityTestStage.CANCELLED,
            CompatibilityTestStage.ACTION_REQUIRED,
        }:
            self._diagnostics.disable()

    def _is_live_locked(self) -> bool:
        return self._session is not None and self._session.stage in {
            CompatibilityTestStage.AWAITING_BASELINE,
            CompatibilityTestStage.ACTIVE,
        }

    def _hardware_authorized_locked(self, kind: CompatibilityEvidenceKind) -> bool:
        if kind is not CompatibilityEvidenceKind.HARDWARE_TEST:
            return False
        try:
            return self._hardware_authorization.hardware_test_authorized() is True
        except Exception:
            return False

    def _capture_baseline_locked(self) -> CompatibilityBaselineCapture:
        if self._baseline_collector is None or self._user_context is None:
            return CompatibilityBaselineCapture(
                False, "compatibility.baseline_observer_unavailable"
            )
        try:
            user_uid = self._user_context.current_user_uid()
            result = self._baseline_collector.capture(user_uid=user_uid)
        except Exception:
            result = None
        if not isinstance(result, CompatibilityBaselineCapture):
            return CompatibilityBaselineCapture(
                False, "compatibility.baseline_observer_unavailable"
            )
        return result

    def _capture_external_handoff_locked(self) -> CompatibilityTestSession:
        assert self._session is not None
        try:
            user_uid = self._user_context.current_user_uid()
            result = self._external_handoff_collector.capture_external_handoff(
                self._session, user_uid=user_uid, now_ms=self._now_locked()
            )
        except Exception:
            result = None
        if not isinstance(result, CompatibilityTestSession):
            return require_compatibility_action(
                self._session,
                "compatibility.external_observer_unavailable",
                now_ms=self._now_locked(),
            )
        return result

    def _now_locked(self) -> int:
        value = self._clock.now_ms()
        if not isinstance(value, int) or value < 0:
            raise ValueError("compatibility test clock is invalid")
        return value
