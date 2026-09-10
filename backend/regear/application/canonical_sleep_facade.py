"""Backend-owned request and consent facade for canonical sleep delivery."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import datetime, timezone

from ..domain.control_plane import (
    RequestIntent,
    RequestSource,
    TransitionRequest,
)
from ..domain.sleep_workflow import REQUEST_ID_RE, SleepFlowEvent, SleepFlowStage
from ..ports.sleep_workflow import SleepWorkflowObservationPort
from .canonical_sleep import (
    CanonicalSleepResult,
    CanonicalSleepStatus,
    CanonicalSleepWorkflowService,
)


_DELIVERY_SOURCES = frozenset(
    {RequestSource.STEAM_MENU, RequestSource.PHYSICAL_BUTTON}
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CanonicalSleepRequestFacade:
    """Keep generation and request identity behind the backend boundary."""

    def __init__(
        self,
        *,
        sleep: CanonicalSleepWorkflowService,
        observations: SleepWorkflowObservationPort,
        request_id_factory: Callable[[], str] | None = None,
        requested_at: Callable[[], str] = _utc_now,
    ) -> None:
        self._sleep = sleep
        self._observations = observations
        self._request_id_factory = request_id_factory or (
            lambda: f"sleep-request-{secrets.token_hex(8)}"
        )
        self._requested_at = requested_at

    def request(self, source: RequestSource) -> CanonicalSleepResult:
        if source not in _DELIVERY_SOURCES:
            return CanonicalSleepResult(False, "sleep.source_unsupported")
        try:
            observed = self._observations.observe()
        except Exception:
            return CanonicalSleepResult(
                False, "sleep.observation_unavailable", action_required=True
            )
        request_id = self._request_id_factory()
        if not REQUEST_ID_RE.fullmatch(request_id):
            return CanonicalSleepResult(
                False, "sleep.request_identity_invalid", action_required=True
            )
        return self._sleep.start(
            TransitionRequest(
                request_id,
                RequestIntent.SLEEP,
                source,
                self._requested_at(),
                observed.generation,
            )
        )

    def respond_to_game_consent(
        self, operation_id: str, *, granted: bool
    ) -> CanonicalSleepResult:
        status = self._sleep.status()
        if (
            status.operation_id != operation_id
            or not status.request_id
            or status.stage is not SleepFlowStage.AWAITING_GAME_CONSENT
            or status.acknowledgement_required
        ):
            return CanonicalSleepResult(
                False, "sleep.operation_changed", action_required=True
            )
        return self._sleep.advance(
            status.request_id,
            (
                SleepFlowEvent.GAME_CONSENT_GRANTED
                if granted
                else SleepFlowEvent.GAME_CONSENT_DENIED
            ),
        )

    def cancel(self, operation_id: str) -> CanonicalSleepResult:
        status = self._sleep.status()
        if (
            status.operation_id != operation_id
            or not status.request_id
            or status.acknowledgement_required
        ):
            return CanonicalSleepResult(
                False, "sleep.operation_changed", action_required=True
            )
        return self._sleep.advance(status.request_id, SleepFlowEvent.CANCEL)

    def status(self) -> CanonicalSleepStatus:
        return self._sleep.status()

    def recover_interrupted(self) -> CanonicalSleepResult:
        return self._sleep.recover_interrupted()

    def acknowledge(self, operation_id: str) -> bool:
        return self._sleep.acknowledge(operation_id)
