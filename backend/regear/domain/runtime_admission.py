"""Host admission narrows effects without granting any lifecycle capability."""

from enum import StrEnum


class RuntimeAdmission(StrEnum):
    OBSERVATION_ONLY = "observation-only"
    PROFILE_GATED = "profile-gated"
    EXPERIMENTAL_HANDOFF = "experimental-handoff"


PASSIVE_RPCS = frozenset({"get_snapshot", "classify_offline_details", "get_peripheral_status",
    "get_usb4_native_diagnostic"})  # Development-only; delivery refuses production before composition.


def runtime_admission(*, exact_host: object, observation_only: object,
                      exact_experimental_host: object = False, build_profile: object = None) -> RuntimeAdmission:
    """Only literal, complete admission evidence reaches existing profile guards."""
    if exact_host is True and observation_only is False:
        return RuntimeAdmission.PROFILE_GATED
    if (exact_experimental_host is True and observation_only is False
            and type(build_profile) is str and build_profile == "development"):
        return RuntimeAdmission.EXPERIMENTAL_HANDOFF
    return RuntimeAdmission.OBSERVATION_ONLY


def passive_rpc_allowed(method: str) -> bool:
    return method in PASSIVE_RPCS
