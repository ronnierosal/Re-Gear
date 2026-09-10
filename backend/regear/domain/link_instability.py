"""Pure, bounded eGPU link-episode assessment.

It classifies two supplied observations only.  It does not collect link data,
diagnose a cable, infer performance, or authorize recovery/removal actions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import Confidence, EgpuLinkState


class LinkInstabilityStatus(StrEnum):
    STABLE_OBSERVED = "stable_observed"
    INSTABILITY_OBSERVED = "instability_observed"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"


@dataclass(frozen=True, slots=True)
class LinkHealthSample:
    attachment_binding: str
    generation: str
    sample_id: str
    applicable: bool
    state: EgpuLinkState
    confidence: Confidence

    def __post_init__(self) -> None:
        if not all((self.attachment_binding, self.generation, self.sample_id)):
            raise ValueError("link health sample requires opaque identity")


@dataclass(frozen=True, slots=True)
class LinkInstabilityAssessment:
    status: LinkInstabilityStatus
    code: str
    current_state: EgpuLinkState | None = None

    def __post_init__(self) -> None:
        if self.status is LinkInstabilityStatus.EVIDENCE_INSUFFICIENT:
            if self.current_state is not None:
                raise ValueError("insufficient link evidence cannot expose a state")
        elif self.current_state is None:
            raise ValueError("observed link evidence requires current state")

    @property
    def authorizes_action(self) -> bool:
        """A link episode never authorizes a transition, removal, or tuning."""
        return False


def assess_link_instability(
    previous: LinkHealthSample,
    current: LinkHealthSample,
    *,
    expected_attachment_binding: str,
) -> LinkInstabilityAssessment:
    """Assess one fresh pair from the same opaque-bound eGPU attachment."""

    if not expected_attachment_binding:
        return _insufficient("link_instability.expected_binding_invalid")
    if (
        previous.attachment_binding != expected_attachment_binding
        or current.attachment_binding != expected_attachment_binding
    ):
        return _insufficient("link_instability.attachment_changed")
    if (
        previous.generation == current.generation
        or previous.sample_id == current.sample_id
    ):
        return _insufficient("link_instability.observation_not_fresh")
    if not _observed(previous) or not _observed(current):
        return _insufficient("link_instability.link_unverified")
    if previous.state is not current.state:
        return LinkInstabilityAssessment(
            LinkInstabilityStatus.INSTABILITY_OBSERVED,
            "link_instability.state_changed",
            current.state,
        )
    return LinkInstabilityAssessment(
        LinkInstabilityStatus.STABLE_OBSERVED,
        "link_instability.state_stable",
        current.state,
    )


def link_instability_to_public_dict(
    assessment: LinkInstabilityAssessment,
) -> dict[str, object]:
    """Expose categorical status only; omit attachment and sample identities."""

    return {
        "schema_version": 1,
        "status": assessment.status.value,
        "code": assessment.code,
        "current_state": assessment.current_state.value if assessment.current_state else None,
    }


def _observed(sample: LinkHealthSample) -> bool:
    return (
        sample.applicable
        and sample.confidence is Confidence.OBSERVED
        and sample.state is not EgpuLinkState.UNKNOWN
    )


def _insufficient(code: str) -> LinkInstabilityAssessment:
    return LinkInstabilityAssessment(LinkInstabilityStatus.EVIDENCE_INSUFFICIENT, code)
