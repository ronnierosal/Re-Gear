"""Compose a live safe disconnect: release, re-observe, then decide.

The parts of a live disconnect all existed and nothing ordered them.
`regear.egpu_release` clears the holders. `regear.egpu_remove` classifies removal
safety and detaches. Neither knows about the other, and an operator bridged
them by eye.

Ordering them is not a convenience. Assessed before a release, removal safety
always declines -- holders are present and, on the tested hardware, the
external connector still has a committed mode no client holds -- so the tool
refuses and removal safety looks permanently unreachable. It is not. It is
being asked too early: **releasing is what changes the facts it reads.**

    release  ->  re-observe  ->  assess  ->  remove  ->  verify

This module is the decision in the middle. It performs no release, takes no
observation and removes nothing; it reads a release that has already finished
and a removal-safety verdict taken *after* it, and says what the sequence may
do next.

The distinction it exists to preserve is between two failures that look alike
and need opposite responses:

- The release did not reach a clear device. Nothing was learned about removal
  safety, and the next action is to find out why the release failed.
- The release succeeded and the device is still not safe to remove. This is
  the state observed on hardware: holders clear, but the eGPU still driving a
  display. That is not a failed release, and reporting it as one sends someone
  to fix the wrong thing.

Nothing here is a claim that any device is safe to unplug. A device safe to
remove in software is a different question, tracked separately, and safety
invariant 10 is untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .device_removal import (
    RemovalFunction,
    RemovalPlan,
    RemovalPlanState,
    compose_removal_plan,
)
from .removal_safety import RemovalSafety, RemovalSafetyState


class ReleaseOutcome(StrEnum):
    """How far the release got, as reported by whatever performed it."""

    #: Every holder released and the scan that said so was complete.
    CLEAR = "clear"
    #: The release ran and holders remain, or the scan could not finish.
    HOLDERS_REMAIN = "holders_remain"
    #: The release refused or failed before it could disturb anything.
    REFUSED = "refused"
    #: No release was attempted.
    NOT_ATTEMPTED = "not_attempted"


class DisconnectStage(StrEnum):
    #: A release must run first; assessing before one is the ordering error
    #: this module exists to prevent.
    RELEASE_REQUIRED = "release_required"
    #: The release refused or failed. Removal safety was not consulted,
    #: because a verdict taken before a release describes the wrong moment.
    RELEASE_REFUSED = "release_refused"
    #: The release ran and the device is still held.
    HOLDERS_REMAIN = "holders_remain"
    #: Released, and still not safe to remove. The specific blocker is in the
    #: code: a retained display resource looks exactly like this.
    NOT_SAFE_AFTER_RELEASE = "not_safe_after_release"
    #: Released, assessed after the release, and a plan composed.
    READY_TO_REMOVE = "ready_to_remove"
    #: The inputs do not describe a sequence.
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class DisconnectDecision:
    """What the sequence may do next, and why when the answer is nothing."""

    stage: DisconnectStage
    code: str
    plan: RemovalPlan | None = None

    def __post_init__(self) -> None:
        if self.stage is DisconnectStage.READY_TO_REMOVE:
            if self.plan is None or not self.plan.usable:
                raise ValueError("a ready decision needs a usable removal plan")
        elif self.plan is not None:
            raise ValueError("only a ready decision carries a plan")

    @property
    def may_remove(self) -> bool:
        """Whether the caller may detach the device now.

        One stage says yes. Every other outcome leaves the device attached and
        untouched, including the case where the release itself succeeded.
        """
        return self.stage is DisconnectStage.READY_TO_REMOVE

    @property
    def released(self) -> bool:
        """Whether the release reached a demonstrably clear device.

        True for the ready stage and for `not_safe_after_release`, which is the
        point: the release worked, and something else is blocking. A caller
        showing this to a player should not say the release failed.
        """
        return self.stage in (
            DisconnectStage.READY_TO_REMOVE,
            DisconnectStage.NOT_SAFE_AFTER_RELEASE,
        )


def decide_disconnect(
    release: ReleaseOutcome,
    readiness_after_release: RemovalSafety | None,
    functions: tuple[RemovalFunction, ...],
    *,
    released_attachment: str = "",
) -> DisconnectDecision:
    """Decide the next step of a live disconnect.

    `readiness_after_release` must be assessed from an observation taken
    **after** the release finished. Passing a verdict from before it reproduces
    the ordering bug this module was written to fix: the answer would describe
    a device that no longer exists, and would always decline.

    The release outcome is consulted first and on its own. A removal-safety
    verdict is not evidence that a release happened, and a device that was
    never released must not be removed however clean it looks.

    `released_attachment` is the attachment the release actually ran against.
    It must match the one the readiness evidence was taken over, because a
    release outcome carries no device identity of its own: without this, a
    release performed on one eGPU combined with ready evidence for another
    composed a plan and reported that removal could proceed. Callers that
    cannot supply it get a refusal rather than an unchecked pass.

    This decision stays advisory. It establishes that the same device was
    released and assessed; the application still has to hold enforcement
    across the removal and revalidate immediately before writing.
    """
    if type(release) is not ReleaseOutcome or type(functions) is not tuple:
        return DisconnectDecision(
            DisconnectStage.INVALID, "disconnect.input_invalid"
        )

    if release is ReleaseOutcome.NOT_ATTEMPTED:
        return DisconnectDecision(
            DisconnectStage.RELEASE_REQUIRED, "disconnect.release_required"
        )
    if release is ReleaseOutcome.REFUSED:
        return DisconnectDecision(
            DisconnectStage.RELEASE_REFUSED, "disconnect.release_refused"
        )
    if release is ReleaseOutcome.HOLDERS_REMAIN:
        return DisconnectDecision(
            DisconnectStage.HOLDERS_REMAIN, "disconnect.holders_remain"
        )

    # Released. Only now does removal safety describe the right moment.
    if type(readiness_after_release) is not RemovalSafety:
        return DisconnectDecision(
            DisconnectStage.INVALID, "disconnect.readiness_missing"
        )
    if (
        readiness_after_release.state
        is not RemovalSafetyState.READY_FOR_SUPERVISED_REMOVAL
    ):
        # The release worked and something else blocks. The readiness code is
        # passed through rather than translated, so the caller learns which
        # fact it was -- a retained display reads as
        # removal_safety.external_display_still_active here.
        return DisconnectDecision(
            DisconnectStage.NOT_SAFE_AFTER_RELEASE, readiness_after_release.code
        )

    revalidation = readiness_after_release.revalidation
    if revalidation is None:
        return DisconnectDecision(
            DisconnectStage.INVALID, "disconnect.revalidation_missing"
        )
    if not released_attachment or released_attachment != revalidation.attachment_binding:
        # The release and the evidence describe different devices, or the
        # caller could not say which device it released.
        return DisconnectDecision(
            DisconnectStage.INVALID, "disconnect.attachment_mismatch"
        )

    plan = compose_removal_plan(readiness_after_release, functions)
    if plan.state is not RemovalPlanState.COMPOSED:
        return DisconnectDecision(
            DisconnectStage.NOT_SAFE_AFTER_RELEASE, plan.code
        )
    return DisconnectDecision(
        DisconnectStage.READY_TO_REMOVE, "disconnect.ready_to_remove", plan
    )
