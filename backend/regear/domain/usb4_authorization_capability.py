"""Private, inert USB4 test-planning contract; no runtime consumer or authority.

Facts must come from a future reviewed, fresh platform evidence producer. These
fixtures do not certify any installed service or device. Even eligible results
cannot authorize commands, mint grants, or relax existing runtime admission.
"""

from dataclasses import dataclass, fields, field
from enum import StrEnum


class Fact(StrEnum):
    VERIFIED = "verified"
    REFUTED = "refuted"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
    STALE = "stale"
    AMBIGUOUS = "ambiguous"


class Readiness(StrEnum):
    OBSERVABLE = "observable"
    READ_ONLY = "read-only"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"
    ELIGIBLE_FOR_SUPERVISED_TEST = "eligible-for-supervised-test"


@dataclass(frozen=True, slots=True)
class CapabilityEvidence:
    # Positive predicates, never model names, raw IDs or public RPC inputs.
    attachment_observation: Fact = Fact.UNKNOWN
    fresh: Fact = Fact.UNKNOWN
    attachment_binding: Fact = Fact.UNKNOWN
    interface_available: Fact = Fact.UNKNOWN
    interface_qualified: Fact = Fact.UNKNOWN
    service_owner: Fact = Fact.UNKNOWN
    security_contract: Fact = Fact.UNKNOWN
    authorization_permission: Fact = Fact.UNKNOWN
    authorization_readback: Fact = Fact.UNKNOWN
    unauthorized: Fact = Fact.UNKNOWN
    unenrolled: Fact = Fact.UNKNOWN
    enrollment_interface: Fact = Fact.UNKNOWN
    policy_ownership: Fact = Fact.UNKNOWN
    persistent_policy: Fact = Fact.UNKNOWN
    enrollment_readback: Fact = Fact.UNKNOWN

    def __post_init__(self):
        if any(type(getattr(self, item.name)) is not Fact for item in fields(CapabilityEvidence)):
            raise ValueError("capability evidence requires exact categorical facts")


@dataclass(frozen=True, slots=True)
class StageAssessment:
    state: Readiness
    reasons: tuple[str, ...]
    dispatch_allowed: bool = field(default=False, init=False)
    mutation_allowed: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class CapabilityAssessment:
    observation: StageAssessment
    authorization: StageAssessment
    enrollment: StageAssessment


_OBSERVATION = ("attachment_observation", "fresh", "attachment_binding")
_AUTHORIZATION = _OBSERVATION + (
    "interface_available", "interface_qualified", "service_owner",
    "security_contract", "authorization_permission", "authorization_readback",
    "unauthorized", "unenrolled",
)
_ENROLLMENT = _AUTHORIZATION + (
    "enrollment_interface", "policy_ownership", "persistent_policy", "enrollment_readback",
)


def _stage(evidence, requirements, qualified_state):
    missing = tuple((name, getattr(evidence, name)) for name in requirements
                    if getattr(evidence, name) is not Fact.VERIFIED)
    if not missing:
        return StageAssessment(qualified_state, ())
    # Report every deficiency; a known block takes precedence over uncertainty.
    values = tuple(value for _, value in missing)
    if Fact.REFUTED in values:
        state = Readiness.BLOCKED
    elif Fact.UNAVAILABLE in values:
        state = Readiness.UNAVAILABLE
    elif any(value in (Fact.ERROR, Fact.STALE, Fact.AMBIGUOUS) for value in values):
        state = Readiness.READ_ONLY
    else:
        state = Readiness.UNKNOWN
    return StageAssessment(state, tuple(name + "." + value.value for name, value in missing))


def assess_capability(evidence: object) -> CapabilityAssessment:
    """Assess fixtures only. Neither input nor output is a mutation capability."""
    valid = type(evidence) is CapabilityEvidence
    if valid:
        try:
            valid = all(type(getattr(evidence, item.name)) is Fact
                        for item in fields(CapabilityEvidence))
        except AttributeError:
            valid = False
    if not valid:
        denied = StageAssessment(Readiness.READ_ONLY, ("evidence.malformed",))
        return CapabilityAssessment(denied, denied, denied)
    return CapabilityAssessment(
        _stage(evidence, _OBSERVATION, Readiness.OBSERVABLE),
        _stage(evidence, _AUTHORIZATION, Readiness.ELIGIBLE_FOR_SUPERVISED_TEST),
        _stage(evidence, _ENROLLMENT, Readiness.ELIGIBLE_FOR_SUPERVISED_TEST),
    )
