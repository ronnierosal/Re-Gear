"""Host admission narrows effects without granting any lifecycle capability."""

from enum import StrEnum


class RuntimeAdmission(StrEnum):
    OBSERVATION_ONLY = "observation-only"
    PROFILE_GATED = "profile-gated"


PASSIVE_RPCS = frozenset({"get_snapshot", "classify_offline_details", "get_peripheral_status"})


def runtime_admission(*, exact_host: object, observation_only: object) -> RuntimeAdmission:
    """Only literal, complete admission evidence reaches existing profile guards."""
    if exact_host is True and observation_only is False:
        return RuntimeAdmission.PROFILE_GATED
    return RuntimeAdmission.OBSERVATION_ONLY


def passive_rpc_allowed(method: str) -> bool:
    return method in PASSIVE_RPCS
