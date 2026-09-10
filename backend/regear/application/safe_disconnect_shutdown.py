"""Confirmed shutdown gate for hardware that cannot be removed while powered."""

from __future__ import annotations

import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from ..domain.control_plane import PlacementState
from ..domain.inference import infer_placement
from ..domain.models import GameState
from ..ports.system_power import SystemPowerPort
from ..ports.transition import TransitionObservationPort
from ..profiles.registry import resolve_runtime_profiles


TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,96}$")


@dataclass(frozen=True, slots=True)
class SafeDisconnectShutdownPreview:
    ready: bool
    blockers: tuple[str, ...] = ()
    approval_token: str = ""


@dataclass(frozen=True, slots=True)
class SafeDisconnectShutdownExecution:
    accepted: bool
    code: str


@dataclass(frozen=True, slots=True)
class _ShutdownPermit:
    token: str
    generation: str
    created_at: float


class SafeDisconnectShutdownApprovalStore:
    def __init__(
        self,
        *,
        ttl_seconds: float = 30,
        monotonic: Callable[[], float] = time.monotonic,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        if ttl_seconds <= 0 or ttl_seconds > 60:
            raise ValueError("safe disconnect approval TTL is invalid")
        self._ttl_seconds = ttl_seconds
        self._monotonic = monotonic
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(18))
        self._permit: _ShutdownPermit | None = None
        self._lock = threading.Lock()

    def issue(self, generation: str) -> str:
        token = self._token_factory()
        if not generation or not TOKEN_RE.fullmatch(token):
            raise ValueError("safe disconnect approval is invalid")
        with self._lock:
            self._permit = _ShutdownPermit(token, generation, self._monotonic())
        return token

    def consume(self, token: str) -> _ShutdownPermit:
        if not TOKEN_RE.fullmatch(token):
            raise ValueError("safe disconnect approval is invalid")
        with self._lock:
            permit = self._permit
            if permit is None or permit.token != token:
                raise ValueError("safe disconnect approval is absent or already used")
            self._permit = None
        if self._monotonic() - permit.created_at >= self._ttl_seconds:
            raise ValueError("safe disconnect approval expired")
        return permit


class SafeDisconnectShutdownService:
    """Power off only from a freshly verified, idle Portable observation.

    This service never authorizes physical removal while the host is powered.
    The player must still wait for fans and power LEDs to turn fully off.
    """

    def __init__(
        self,
        *,
        observations: TransitionObservationPort,
        power: SystemPowerPort,
        approvals: SafeDisconnectShutdownApprovalStore | None = None,
    ) -> None:
        self._observations = observations
        self._power = power
        self._approvals = approvals or SafeDisconnectShutdownApprovalStore()
        self._lock = threading.Lock()

    def preview(self, *, user_confirmed: bool) -> SafeDisconnectShutdownPreview:
        observed = self._observations.observe()
        if observed is None:
            return SafeDisconnectShutdownPreview(
                False, ("safe_disconnect.observation_unavailable",)
            )
        blockers = self._blockers(observed)
        if blockers:
            return SafeDisconnectShutdownPreview(False, blockers)
        token = self._approvals.issue(observed.generation) if user_confirmed else ""
        return SafeDisconnectShutdownPreview(True, approval_token=token)

    def execute(self, approval_token: str) -> SafeDisconnectShutdownExecution:
        if not self._lock.acquire(blocking=False):
            return SafeDisconnectShutdownExecution(
                False, "safe_disconnect.concurrent_request"
            )
        try:
            try:
                permit = self._approvals.consume(approval_token)
            except ValueError:
                return SafeDisconnectShutdownExecution(
                    False, "safe_disconnect.approval_invalid"
                )
            observed = self._observations.observe()
            if observed is None:
                return SafeDisconnectShutdownExecution(
                    False, "safe_disconnect.observation_unavailable"
                )
            if observed.generation != permit.generation:
                return SafeDisconnectShutdownExecution(
                    False, "safe_disconnect.evidence_changed"
                )
            blockers = self._blockers(observed)
            if blockers:
                return SafeDisconnectShutdownExecution(False, blockers[0])
            result = self._power.request_poweroff()
            return SafeDisconnectShutdownExecution(result.requested, result.code)
        finally:
            self._lock.release()

    @staticmethod
    def _blockers(observed) -> tuple[str, ...]:
        snapshot = observed.snapshot
        profiles = resolve_runtime_profiles(snapshot)
        blockers: list[str] = []
        if not profiles.exact_host:
            blockers.append("safe_disconnect.host_unverified")
        if not snapshot.disconnect_readiness.applicable:
            blockers.append("safe_disconnect.egpu_not_observed")
        if snapshot.game_state is GameState.UNKNOWN:
            blockers.append("safe_disconnect.game_state_unknown")
        elif snapshot.game_state is GameState.RUNNING:
            blockers.append("safe_disconnect.game_running")
        if infer_placement(snapshot) is not PlacementState.PORTABLE:
            blockers.append("safe_disconnect.portable_unverified")
        return tuple(blockers)
