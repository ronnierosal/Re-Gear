"""Approval-gated preparation of HDM's reversible Gamescope integration."""

from __future__ import annotations

import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable

from ..ports.presentation_activation import (
    GamescopeIntegrationPort,
    GamescopeUserResolution,
    UserServiceCommandPort,
    UserServiceOperation,
)
from ..ports.presentation_activation import GamescopeUserContext
from ..domain.inference import infer_placement
from ..domain.control_plane import PlacementState
from ..domain.models import Confidence, GameState
from ..domain.models import GpuRole
from ..ports.transition import TransitionObservationPort


TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,96}$")
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class PresentationActivationPermit:
    token: str
    generation: str
    user: GamescopeUserContext
    fingerprint: str


class PresentationActivationApprovalStore:
    def __init__(
        self,
        *,
        ttl_seconds: float = 120,
        monotonic: Callable[[], float] = time.monotonic,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        if ttl_seconds <= 0 or ttl_seconds > 120:
            raise ValueError("presentation activation TTL must be between 0 and 120")
        self._ttl_seconds = ttl_seconds
        self._monotonic = monotonic
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(18))
        self._approval: tuple[PresentationActivationPermit, float] | None = None
        self._lock = threading.Lock()

    def issue(
        self,
        *,
        generation: str,
        user: GamescopeUserContext,
        fingerprint: str,
        user_confirmed: bool,
    ) -> str:
        if not user_confirmed:
            raise ValueError("presentation activation requires explicit consent")
        token = self._token_factory()
        if (
            not TOKEN_RE.fullmatch(token)
            or not generation
            or not FINGERPRINT_RE.fullmatch(fingerprint)
        ):
            raise ValueError("presentation activation approval is invalid")
        permit = PresentationActivationPermit(token, generation, user, fingerprint)
        with self._lock:
            self._approval = (permit, self._monotonic())
        return token

    def consume(self, token: str) -> PresentationActivationPermit:
        if not TOKEN_RE.fullmatch(token):
            raise ValueError("presentation activation token is invalid")
        with self._lock:
            approval = self._approval
            if approval is None or approval[0].token != token:
                raise ValueError("presentation activation approval is absent or used")
            self._approval = None
        permit, created = approval
        if self._monotonic() - created >= self._ttl_seconds:
            raise ValueError("presentation activation approval expired")
        return permit


@dataclass(frozen=True, slots=True)
class PresentationActivationPreview:
    token: str
    generation: str
    already_ready: bool
    blockers: tuple[str, ...] = ()

    @property
    def approved(self) -> bool:
        return bool(self.token) and not self.blockers


@dataclass(frozen=True, slots=True)
class PresentationActivationOutcome:
    prepared: bool
    changed: bool
    code: str
    rollback_attempted: bool = False
    rollback_succeeded: bool = False


class PresentationActivationService:
    def __init__(
        self,
        *,
        observations: TransitionObservationPort,
        integration: GamescopeIntegrationPort,
        commands: UserServiceCommandPort,
        resolve_user: Callable[[], GamescopeUserResolution],
        approvals: PresentationActivationApprovalStore | None = None,
        verify_prepared: Callable[[], bool] | None = None,
    ) -> None:
        self._observations = observations
        self._integration = integration
        self._commands = commands
        self._resolve_user = resolve_user
        self._approvals = approvals or PresentationActivationApprovalStore()
        self._verify_prepared = verify_prepared
        self._lock = threading.Lock()

    def preview(self, *, user_confirmed: bool) -> PresentationActivationPreview:
        observed = self._observe()
        if observed is None:
            return PresentationActivationPreview("", "", False, ("observation.unavailable",))
        user, fingerprint, status, blockers = self._preflight(observed.snapshot)
        if blockers or user is None or not fingerprint:
            return PresentationActivationPreview(
                "", observed.generation, status.ready, blockers
            )
        token = ""
        if user_confirmed:
            token = self._approvals.issue(
                generation=observed.generation,
                user=user,
                fingerprint=fingerprint,
                user_confirmed=True,
            )
        return PresentationActivationPreview(
            token, observed.generation, status.ready
        )

    def execute(self, token: str) -> PresentationActivationOutcome:
        if not self._lock.acquire(blocking=False):
            return PresentationActivationOutcome(
                False, False, "activation.concurrent_request"
            )
        try:
            return self._execute_locked(token)
        finally:
            self._lock.release()

    def _execute_locked(self, token: str) -> PresentationActivationOutcome:
        try:
            permit = self._approvals.consume(token)
        except ValueError:
            return PresentationActivationOutcome(False, False, "activation.approval_invalid")
        observed = self._observe()
        if observed is None:
            return PresentationActivationOutcome(False, False, "activation.observation_unavailable")
        user, fingerprint, _, blockers = self._preflight(observed.snapshot)
        if (
            blockers
            or observed.generation != permit.generation
            or user != permit.user
            or fingerprint != permit.fingerprint
        ):
            return PresentationActivationOutcome(False, False, "activation.evidence_changed")
        result = self._integration.activate()
        if not result.ok:
            return PresentationActivationOutcome(False, result.changed, "activation.install_failed")
        try:
            installed_fingerprint = self._integration.activation_fingerprint()
            current_user = self._resolve_user()
        except Exception:
            installed_fingerprint = ""
            current_user = GamescopeUserResolution(None, "gamescope_user_unresolved")
        if (
            installed_fingerprint != permit.fingerprint
            or not current_user.ok
            or current_user.context != permit.user
        ):
            if result.changed:
                removed = self._integration.deactivate()
                return PresentationActivationOutcome(
                    False,
                    True,
                    (
                        "activation.evidence_changed"
                        if removed.changed
                        else "activation.rollback_failed"
                    ),
                    True,
                    removed.changed,
                )
            return PresentationActivationOutcome(
                False, False, "activation.evidence_changed"
            )
        if not self._run(UserServiceOperation.DAEMON_RELOAD, user):
            return self._rollback(result.changed, "activation.daemon_reload_failed", user)
        if not self._run(UserServiceOperation.VERIFY_GAMESCOPE_UNIT, user):
            return self._rollback(result.changed, "activation.unit_unavailable", user)
        if self._verify_prepared is not None:
            try:
                verified = self._verify_prepared() is True
            except Exception:
                verified = False
            if not verified:
                return self._rollback(result.changed, 'activation.unit_mismatch', user)
        return PresentationActivationOutcome(True, result.changed, "activation.prepared")

    def _preflight(self, snapshot):
        blockers: list[str] = []
        if infer_placement(snapshot) is not PlacementState.PORTABLE:
            blockers.append("placement.portable_required")
        if any(gpu.role is GpuRole.EXTERNAL and gpu.present for gpu in snapshot.gpus):
            blockers.append("egpu.disconnected_required")
        if snapshot.game_state is not GameState.IDLE:
            blockers.append(
                "game.state_unknown"
                if snapshot.game_state is GameState.UNKNOWN
                else "game.running"
            )
        if snapshot.gamescope.running is not True or snapshot.gamescope.confidence is not Confidence.VERIFIED:
            blockers.append("gamescope.unverified")
        status = self._integration.status()
        if status.error_code:
            blockers.append(f"integration.{status.error_code}")
        if not status.shim_ready:
            blockers.append("integration.shim_unavailable")
        try:
            resolution = self._resolve_user()
        except Exception:
            resolution = GamescopeUserResolution(None, "gamescope_user_unresolved")
        user = resolution.context if resolution.ok else None
        if user is None:
            blockers.append("gamescope.user_unavailable")
        elif user != self._integration.user:
            blockers.append("gamescope.user_changed")
        try:
            fingerprint = self._integration.activation_fingerprint()
        except (OSError, ValueError):
            fingerprint = ""
            blockers.append("integration.fingerprint_unavailable")
        return user, fingerprint, status, tuple(dict.fromkeys(blockers))

    def _rollback(self, changed: bool, code: str, user) -> PresentationActivationOutcome:
        if not changed:
            return PresentationActivationOutcome(False, False, code)
        removed = self._integration.deactivate()
        reloaded = removed.changed and self._run(UserServiceOperation.DAEMON_RELOAD, user)
        rollback_succeeded = bool(removed.changed and reloaded)
        return PresentationActivationOutcome(
            False,
            changed,
            code if rollback_succeeded else "activation.rollback_failed",
            True,
            rollback_succeeded,
        )

    def _run(self, operation, user) -> bool:
        try:
            return self._commands.run(
                operation, uid=user.uid, username=user.username
            ).ok
        except Exception:
            return False

    def _observe(self):
        try:
            return self._observations.observe()
        except Exception:
            return None
