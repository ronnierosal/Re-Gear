"""Pure removal-safety classification; never a physical-removal claim.

Safe Undock readiness answers two different questions at once: whether the eGPU
can be detached without destabilising the system, and whether the player still
has sound and controls afterwards. They have different failure modes. Losing
audio is recoverable by reconnecting; detaching a device the kernel still
believes is in use is not.

This module classifies only the first question, over the same
`SafeUndockEvidence` and with the same evidence-identity rules. It adds nothing
and relaxes nothing: `assess_safe_undock_readiness` keeps its full nine-fact
contract for the player-facing flow, and this narrower verdict exists alongside
it for gating a supervised software-removal experiment.

Safety invariant 20 lists what a disconnect decision requires: a profile
verified for live removal, independent verified render and display readiness,
and complete client and storage evidence. It does not name audio or controller
state, so this subset is the one the invariant actually describes.

`ready_for_supervised_removal` is NOT clearance to unplug anything, and not
clearance to remove anything by itself. It states that one fresh observation is
complete and consistent enough to hand to a supervised removal step that must
independently revalidate before acting.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import GameState
from .safe_undock_readiness import (
    SafeUndockEvidence,
    SafeUndockRevalidation,
    invalidation_code,
)


class RemovalSafetyState(StrEnum):
    READY_FOR_SUPERVISED_REMOVAL = "ready_for_supervised_removal"
    NOT_READY = "not_ready"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    INVALIDATED = "invalidated"


#: The facts this verdict consults, in the order it consults them. Audio and
#: built-in controller are deliberately absent; they are player-recoverability
#: facts, and the removal-relevant part of audio ownership already appears here
#: through `clients_clear`, which counts any holder of the eGPU audio function.
REMOVAL_SAFETY_FACTS: tuple[str, ...] = (
    "exact_attachment",
    "topology_exact",
    "client_scan_complete",
    "clients_clear",
    "portable_display_active",
    "portable_render_gpu",
    "external_display_active",
)


@dataclass(frozen=True, slots=True)
class RemovalSafety:
    state: RemovalSafetyState
    code: str
    revalidation: SafeUndockRevalidation | None = None

    def __post_init__(self) -> None:
        if self.state is RemovalSafetyState.READY_FOR_SUPERVISED_REMOVAL:
            if self.revalidation is None:
                raise ValueError("removal safety readiness requires revalidation evidence")
        elif self.revalidation is not None:
            raise ValueError("only ready removal safety state exposes revalidation evidence")


def assess_removal_safety(
    evidence: SafeUndockEvidence,
    *,
    expected_attachment_binding: str,
    expected_generation: str,
    expected_sample_id: str,
) -> RemovalSafety:
    """Classify one fresh observation for removal safety only."""
    invalid = invalidation_code(
        evidence,
        expected_attachment_binding,
        expected_generation,
        expected_sample_id,
    )
    if invalid:
        return RemovalSafety(RemovalSafetyState.INVALIDATED, invalid)
    if evidence.game_state is GameState.RUNNING:
        return RemovalSafety(RemovalSafetyState.NOT_READY, "removal_safety.game_running")
    if evidence.game_state is GameState.UNKNOWN:
        return RemovalSafety(
            RemovalSafetyState.EVIDENCE_INSUFFICIENT,
            "removal_safety.game_state_unknown",
        )
    if (
        evidence.portable_display_active.verified
        and evidence.external_display_active.verified
        and evidence.portable_display_active.value is True
        and evidence.external_display_active.value is True
    ):
        return RemovalSafety(
            RemovalSafetyState.EVIDENCE_INSUFFICIENT,
            "removal_safety.display_contradictory",
        )
    for fact, state, code, expected in (
        (evidence.exact_attachment, RemovalSafetyState.EVIDENCE_INSUFFICIENT, "removal_safety.attachment_unverified", True),
        (evidence.topology_exact, RemovalSafetyState.EVIDENCE_INSUFFICIENT, "removal_safety.topology_unverified", True),
        (evidence.client_scan_complete, RemovalSafetyState.EVIDENCE_INSUFFICIENT, "removal_safety.client_scan_incomplete", True),
        (evidence.clients_clear, RemovalSafetyState.NOT_READY, "removal_safety.clients_active_or_protected", True),
        (evidence.portable_display_active, RemovalSafetyState.NOT_READY, "removal_safety.portable_display_unverified", True),
        (evidence.portable_render_gpu, RemovalSafetyState.NOT_READY, "removal_safety.portable_render_unverified", True),
        (evidence.external_display_active, RemovalSafetyState.NOT_READY, "removal_safety.external_display_still_active", False),
    ):
        if not fact.verified or fact.value is not expected:
            return RemovalSafety(state, code)
    return RemovalSafety(
        RemovalSafetyState.READY_FOR_SUPERVISED_REMOVAL,
        "removal_safety.ready_for_supervised_removal",
        SafeUndockRevalidation(
            evidence.attachment_binding, evidence.generation, evidence.sample_id
        ),
    )
