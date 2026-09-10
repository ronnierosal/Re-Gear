"""Pure composition of a supervised eGPU software-removal plan.

`removal_safety` decides whether a device *may* be detached. Nothing decided
what detaching it consists of. This module composes that plan: which PCI
functions to remove, in what order, and what recovery is defined if a step does
not complete.

This module performs no removal: it composes a plan, and producing one
authorises nothing. The write that detaches a device lives behind
`regear.ports.device_removal`, implemented by the single adapter
`scripts/check_architecture.py` permits to write. Composing a plan and executing
one are deliberately separate, so the decision to remove stays reviewable apart
from the capability to remove.

Grounded in a supervised run on an Ally X with a GPD G1, holders already
cleared:

- Removing `0000:08:00.1` then `0000:08:00.0` took about two seconds each. The
  kernel logged `amdgpu: finishing device` and `[drm] amdgpu: ttm finalized`,
  the session stayed active, and a bus rescan restored both functions in about
  three seconds with their drivers rebound.
- The eGPU is a multi-function device. A plan that removes only the GPU
  function leaves the audio function attached, so both are required and a plan
  covering one is refused rather than executed partially.

The order is recorded, not derived: the audio function was removed first in the
run that succeeded, and nothing here establishes that the reverse also works.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .removal_safety import RemovalSafety, RemovalSafetyState


#: Same shape the PCI adapter validates, kept local so the domain stays pure.
PCI_ADDRESS = re.compile(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]")


class RemovalFunctionKind(StrEnum):
    GPU = "gpu"
    AUDIO = "audio"


class RemovalPlanState(StrEnum):
    COMPOSED = "composed"
    NOT_READY = "not_ready"
    EVIDENCE_INCOMPLETE = "evidence_incomplete"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class RemovalFunction:
    """One PCI function of the eGPU that a removal must detach."""

    kind: RemovalFunctionKind
    address: str

    def __post_init__(self) -> None:
        if not PCI_ADDRESS.fullmatch(self.address):
            raise ValueError("removal function address is invalid")


@dataclass(frozen=True, slots=True)
class RemovalPlan:
    """An ordered removal plan bound to its authorising observation, or why
    there is not one.

    `attachment_binding` and `generation` identify the device the plan was
    composed for. `sample_id` records which observation authorised it, for
    audit rather than for staleness checking.
    """

    state: RemovalPlanState
    code: str
    functions: tuple[RemovalFunction, ...] = ()
    attachment_binding: str = ""
    generation: str = ""
    sample_id: str = ""

    def __post_init__(self) -> None:
        if self.state is RemovalPlanState.COMPOSED:
            if not self.functions:
                raise ValueError("a composed removal plan needs functions")
            if not all(
                (self.attachment_binding, self.generation, self.sample_id)
            ):
                raise ValueError("a composed removal plan needs observation identity")
        elif self.functions:
            raise ValueError("only a composed removal plan exposes functions")

    @property
    def usable(self) -> bool:
        return self.state is RemovalPlanState.COMPOSED

    @property
    def addresses(self) -> tuple[str, ...]:
        return tuple(function.address for function in self.functions)


def compose_removal_plan(
    readiness: RemovalSafety,
    functions: tuple[RemovalFunction, ...],
) -> RemovalPlan:
    """Compose the removal plan for an eGPU whose holders are already clear.

    The plan is bound to the observation that authorised it. Readiness
    established at compose time says nothing about the state at execute time,
    so an executor must do two separate things immediately before acting:
    confirm the device is the same one with `plan_is_current`, and re-run the
    readiness assessment against fresh evidence. The first catches a plan
    pointed at a different device; only the second establishes that removing
    it is still safe. The sample id recorded here identifies the authorising
    observation for audit and is deliberately not a staleness signal -- see
    `plan_is_current`.
    """
    if type(readiness) is not RemovalSafety or type(functions) is not tuple:
        return RemovalPlan(RemovalPlanState.INVALID, "device_removal.input_invalid")
    if any(type(function) is not RemovalFunction for function in functions):
        return RemovalPlan(RemovalPlanState.INVALID, "device_removal.input_invalid")

    if readiness.state is not RemovalSafetyState.READY_FOR_SUPERVISED_REMOVAL:
        # Anything short of ready is reported as not ready rather than
        # translated, so the readiness code stays the one a reader can act on.
        return RemovalPlan(RemovalPlanState.NOT_READY, readiness.code)
    if readiness.revalidation is None:
        return RemovalPlan(
            RemovalPlanState.EVIDENCE_INCOMPLETE, "device_removal.revalidation_missing"
        )

    kinds = {function.kind for function in functions}
    missing = tuple(
        sorted(
            kind.value
            for kind in (RemovalFunctionKind.GPU, RemovalFunctionKind.AUDIO)
            if kind not in kinds
        )
    )
    if missing:
        # A multi-function device left half-attached is not a smaller removal,
        # it is an incomplete one; the remaining function stays bound.
        return RemovalPlan(
            RemovalPlanState.EVIDENCE_INCOMPLETE,
            "device_removal.missing_" + "_and_".join(missing),
        )
    if len(functions) != len(kinds):
        return RemovalPlan(
            RemovalPlanState.INVALID, "device_removal.duplicate_function_kind"
        )
    if len({function.address.lower() for function in functions}) != len(functions):
        return RemovalPlan(
            RemovalPlanState.INVALID, "device_removal.duplicate_address"
        )

    # Audio first, then GPU: the order the successful supervised run used.
    ordered = tuple(
        function
        for kind in (RemovalFunctionKind.AUDIO, RemovalFunctionKind.GPU)
        for function in functions
        if function.kind is kind
    )
    revalidation = readiness.revalidation
    return RemovalPlan(
        RemovalPlanState.COMPOSED,
        "device_removal.composed",
        ordered,
        revalidation.attachment_binding,
        revalidation.observed_generation,
        revalidation.observed_sample_id,
    )


def plan_is_current(
    plan: RemovalPlan,
    *,
    attachment_binding: str,
    generation: str,
) -> bool:
    """Return whether `plan` still describes the same device as a fresh reading.

    This answers **identity**, not state: is the thing in front of the executor
    the thing the plan was composed for. A changed attachment binding is a
    different device; a changed generation is a different observed device set.
    Either means the plan must be recomposed rather than executed.

    It used to compare the sample id as well, which made it unsatisfiable. Sample
    ids are minted per observation -- a counter in the peripheral adapter, and a
    fresh one again in a new process -- so no genuinely fresh observation could
    ever match a composed plan. The only call that passed was one replaying the
    composing observation's own values, which checks nothing. The sample id is
    still carried on the plan, because it records which observation authorised
    it and that is worth auditing; it is simply not a staleness signal.

    Identity is necessary and **not sufficient**, and the caller carries the
    rest. `generation` is derived from the peripheral inventory alone, so
    neither it nor the attachment binding moves when display or GPU state
    changes underneath. An executor must therefore also re-run the readiness
    assessment against fresh evidence and refuse on anything short of ready.
    This predicate exists to catch a plan pointed at the wrong device, not to
    certify that removing it is still safe.
    """
    if not plan.usable:
        return False
    return (
        plan.attachment_binding == attachment_binding
        and plan.generation == generation
    )
