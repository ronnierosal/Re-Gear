"""One explicit offline check over an admitted, bounded local-memory reader.

No production reader is constructed here. The composition owner must verify
the reader's source, cost, and timestamps; this service never refreshes a cache
timestamp or interprets a request itself as proof of fresh Steam evidence.
"""

from dataclasses import dataclass
from typing import Callable

from ..domain.models import GameState
from ..domain.offline_readiness import (
    OfflineEvidenceAdmissionKind,
    OfflineEvidenceCollectionContract,
    OfflineEvidenceSourceDeclaration,
    OfflineReadinessAssessment,
    OfflineReadinessObservation,
    OfflineReadinessStatus,
    admit_reviewed_offline_evidence_source,
    classify_fresh_offline_readiness,
    offline_readiness_to_public_dict,
)


@dataclass(frozen=True, slots=True)
class OfflineCheckContext:
    """Private counters; change on every selection/session/game-state transition.

    A generation must never be reused after switching away and back. The owner
    keeps game/account identity outside this record and outside public delivery.
    """

    generation: int
    game_state: GameState

    def __post_init__(self) -> None:
        if type(self.generation) is not int or not 0 <= self.generation < 2**63:
            raise ValueError("invalid offline check generation")
        if not isinstance(self.game_state, GameState):
            raise ValueError("invalid offline check game state")


@dataclass(frozen=True, slots=True)
class OfflineCheckSample:
    context: OfflineCheckContext
    observation: OfflineReadinessObservation


class OfflineReadinessService:
    """Read once after admission, revalidate, and serialize only public guidance.

    ``read_local`` must perform bounded in-memory work only, with no blocking
    I/O, callbacks, subscriptions, or background tasks. Actual elapsed-time
    rejection below is not preemption of a misbehaving reader. A future I/O
    adapter requires its own cancellation/timeout lifecycle before admission.
    """

    def __init__(
        self,
        *,
        declaration: OfflineEvidenceSourceDeclaration,
        contract: OfflineEvidenceCollectionContract,
        current_context: Callable[[], OfflineCheckContext | None],
        read_local: Callable[[OfflineCheckContext], OfflineCheckSample],
        monotonic_ms: Callable[[], int],
    ) -> None:
        self._declaration = declaration
        self._contract = contract
        self._current_context = current_context
        self._read_local = read_local
        self._clock = monotonic_ms

    def check(self) -> dict[str, object]:
        """For the currently selected game only; caller discards on navigation."""
        try:
            context = self._current_context()
            if not isinstance(context, OfflineCheckContext):
                return self._unknown("offline_evidence_context_changed")
            admission = admit_reviewed_offline_evidence_source(
                self._declaration, self._contract, context.game_state
            )
            if admission.kind is not OfflineEvidenceAdmissionKind.ADMIT:
                return self._unknown(admission.reason_code)
            started = self._clock()
            sample = self._read_local(context)
            current = self._current_context()
            finished = self._clock()
            if current != context:
                return self._unknown("offline_evidence_context_changed")
            if not isinstance(sample, OfflineCheckSample):
                return self._unknown("offline_evidence_unavailable")
            if sample.context != context:
                return self._unknown("offline_evidence_context_changed")
            if type(started) is not int or type(finished) is not int or started < 0:
                return self._unknown("offline_evidence_unavailable")
            if finished < started:
                return self._unknown("offline_evidence_stale")
            # The declared measurement is a per-read ceiling, not permission to
            # spend the whole interval budget on a slower-than-reviewed reader.
            if finished - started > self._contract.measured_collection_cost_ms:
                return self._unknown("offline_evidence_cost_exceeds_budget")
            if not isinstance(sample.observation, OfflineReadinessObservation):
                return self._unknown("offline_evidence_unavailable")
            observed_at = sample.observation.observed_at_monotonic_ms
            if type(observed_at) is not int or observed_at > finished:
                return self._unknown("offline_evidence_stale")
            result = classify_fresh_offline_readiness(
                sample.observation, self._contract, now_monotonic_ms=finished
            )
            return offline_readiness_to_public_dict(result)
        except Exception:
            # Source errors may contain account identifiers, titles, or paths.
            # Never log or expose their exception text in this delivery path.
            return self._unknown("offline_evidence_unavailable")

    @staticmethod
    def _unknown(reason: str) -> dict[str, object]:
        return offline_readiness_to_public_dict(
            OfflineReadinessAssessment(OfflineReadinessStatus.UNKNOWN, (reason,))
        )
