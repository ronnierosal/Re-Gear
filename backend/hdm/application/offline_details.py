"""Classify a minimized Steam report; collection and freshness belong to its caller."""

from collections.abc import Callable

from ..domain.models import GameState
from ..domain.offline_readiness import (
    OfflineReadinessAssessment,
    OfflineReadinessEvidence,
    OfflineReadinessStatus,
    classify_offline_readiness,
    offline_readiness_to_public_dict,
)

_INTEGER_FIELDS = frozenset({"iInstallFolder", "eDisplayStatus", "eCloudStatus"})
_BOOLEAN_FIELDS = frozenset({
    "bCloudAvailable", "bCloudEnabledForAccount", "bCloudEnabledForApp",
    "bIsThirdPartyUpdater",
})


def classify_minimized_steam_details(
    details: object,
    *,
    game_state: GameState,
    project_details: Callable[[object], OfflineReadinessEvidence],
) -> dict[str, object]:
    """No source admission, entitlement, persistence, or offline-launch promise.

    Strictly accept only the seven bounded scalar fields inspected in the local
    Steam callback. The delivery caller must bind requests and expire results.
    Missing fields remain unknown; malformed or extra fields reject the report.
    """
    if game_state is not GameState.IDLE:
        return _unknown("offline_evidence_game_active" if game_state is GameState.RUNNING
                        else "offline_evidence_game_unknown")
    if type(details) is not dict or len(details) > 7:
        return _unknown("offline_evidence_unavailable")
    for key, value in details.items():
        if key in _INTEGER_FIELDS:
            if type(value) is not int or not -1 <= value <= 2**31 - 1:
                return _unknown("offline_evidence_unavailable")
        elif key in _BOOLEAN_FIELDS:
            if type(value) is not bool:
                return _unknown("offline_evidence_unavailable")
        else:
            return _unknown("offline_evidence_unavailable")
    return offline_readiness_to_public_dict(classify_offline_readiness(project_details(details)))


def _unknown(reason: str) -> dict[str, object]:
    return offline_readiness_to_public_dict(OfflineReadinessAssessment(
        OfflineReadinessStatus.UNKNOWN, (reason,),
    ))
