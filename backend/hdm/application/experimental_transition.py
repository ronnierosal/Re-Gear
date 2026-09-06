"""Short-lived backend approval for one experimental transition plan."""

from __future__ import annotations

import re
import secrets
import threading
import time
from collections.abc import Callable

from ..domain.control_plane import (
    ExperimentalTransitionPermit,
    PlacementState,
)


TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,96}$")


class ExperimentalTransitionApprovalStore:
    def __init__(
        self,
        *,
        ttl_seconds: float = 120,
        monotonic: Callable[[], float] = time.monotonic,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        if ttl_seconds <= 0 or ttl_seconds > 120:
            raise ValueError("experimental approval TTL must be between 0 and 120 seconds")
        self._ttl_seconds = ttl_seconds
        self._monotonic = monotonic
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(18))
        self._approval: tuple[str, float, ExperimentalTransitionPermit] | None = None
        self._lock = threading.Lock()

    def issue(
        self,
        *,
        plan_id: str,
        observed_generation: str,
        target_placement: PlacementState,
        host_profile_id: str,
        egpu_profile_id: str,
        egpu_stable_id: str,
        user_confirmed: bool,
        portable_vulkan_trial: bool = False,
    ) -> str:
        if not user_confirmed:
            raise ValueError("experimental transition requires explicit consent")
        token = self._token_factory()
        if not TOKEN_RE.fullmatch(token):
            raise ValueError("experimental approval token is invalid")
        permit = ExperimentalTransitionPermit(
            permit_id=token,
            plan_id=plan_id,
            observed_generation=observed_generation,
            target_placement=target_placement,
            host_profile_id=host_profile_id,
            egpu_profile_id=egpu_profile_id,
            egpu_stable_id=egpu_stable_id,
            portable_vulkan_trial=portable_vulkan_trial,
        )
        with self._lock:
            self._approval = (token, self._monotonic(), permit)
        return token

    def consume(self, token: str) -> ExperimentalTransitionPermit:
        if not TOKEN_RE.fullmatch(token):
            raise ValueError("experimental approval token is invalid")
        with self._lock:
            approval = self._approval
            if approval is None or approval[0] != token:
                raise ValueError("experimental approval is absent or already used")
            self._approval = None
        _, created, permit = approval
        if self._monotonic() - created >= self._ttl_seconds:
            raise ValueError("experimental approval expired")
        return permit
