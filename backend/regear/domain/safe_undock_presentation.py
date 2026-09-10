"""Human-facing presentation of revalidated Safe Undock evidence.

This module is deliberately a pure interpretation of the Stage 1.5 result.  It
does not issue a physical action, remember an acknowledgement, or assert that
an eGPU may be unplugged.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .safe_undock_readiness import (
    SafeUndockReadiness,
    SafeUndockReadinessState,
    SafeUndockRevalidation,
)


class SafeUndockPresentationCategory(StrEnum):
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    NOT_READY = "not_ready"
    REVALIDATE_REQUIRED = "revalidate_required"
    ELIGIBLE_FOR_SUPERVISED_PHYSICAL_VALIDATION = (
        "eligible_for_supervised_physical_validation"
    )


@dataclass(frozen=True, slots=True)
class SafeUndockPresentation:
    """A non-authorizing result for a human-controlled Safe Undock flow."""

    category: SafeUndockPresentationCategory
    code: str
    revalidation: SafeUndockRevalidation | None = None


def present_safe_undock_result(
    readiness: SafeUndockReadiness,
    *,
    current_revalidation: SafeUndockRevalidation | None,
    acknowledged: bool,
) -> SafeUndockPresentation:
    """Present a Stage 1.5 result without broadening its authority.

    ``current_revalidation`` must be captured again immediately before any
    later supervised physical-validation step.  A missing or changed binding,
    generation, or sample invalidates the presentation and requires another
    Stage 1.5 assessment.
    """

    if readiness.state is SafeUndockReadinessState.EVIDENCE_INSUFFICIENT:
        return SafeUndockPresentation(
            SafeUndockPresentationCategory.EVIDENCE_INSUFFICIENT,
            readiness.code,
        )

    if readiness.state is SafeUndockReadinessState.NOT_READY:
        return SafeUndockPresentation(
            SafeUndockPresentationCategory.NOT_READY,
            readiness.code,
        )

    if readiness.state is not SafeUndockReadinessState.READY_FOR_REVALIDATION:
        return SafeUndockPresentation(
            SafeUndockPresentationCategory.REVALIDATE_REQUIRED,
            "safe_undock_presentation.revalidation_required",
        )

    revalidation = readiness.revalidation
    if revalidation is None or current_revalidation != revalidation:
        return SafeUndockPresentation(
            SafeUndockPresentationCategory.REVALIDATE_REQUIRED,
            "safe_undock_presentation.revalidation_stale_or_changed",
        )

    if not acknowledged:
        return SafeUndockPresentation(
            SafeUndockPresentationCategory.REVALIDATE_REQUIRED,
            "safe_undock_presentation.acknowledgement_required",
        )

    return SafeUndockPresentation(
        SafeUndockPresentationCategory.ELIGIBLE_FOR_SUPERVISED_PHYSICAL_VALIDATION,
        "safe_undock_presentation.supervised_physical_validation_eligible",
        revalidation,
    )
