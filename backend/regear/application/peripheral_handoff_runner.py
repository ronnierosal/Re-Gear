"""Deterministic, mechanism-free runner for one fully verified peripheral plan.

The runner is a future transition child, not an independent dock/undock path.
It accepts no controller or audio identifiers from delivery, runs only a Ready
plan, and requires fresh same-generation revalidation before every mechanism
call. Any apply or verification failure reverses only already verified steps in
reverse order. There is no constructed SteamOS mechanism or RPC.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from ..domain.control_plane import EffectiveCapabilities
from ..domain.peripheral_handoff import (
    ControllerHandoffPolicy,
    HandoffDirection,
    PeripheralHandoffPlan,
    PeripheralPlanStatus,
    PeripheralPlanStep,
    PeripheralStepKind,
    is_peripheral_token,
)


CODE_RE = re.compile(r"^[a-z0-9_.-]{1,96}$")
MAX_PERIPHERAL_STEPS = 8


class PeripheralExecutionOutcome(StrEnum):
    COMPLETED = "completed"
    RECOVERED = "recovered"
    ACTION_REQUIRED = "action_required"


@dataclass(frozen=True, slots=True)
class PeripheralMechanismResult:
    accepted: bool
    code: str

    def __post_init__(self) -> None:
        if not CODE_RE.fullmatch(self.code):
            raise ValueError("peripheral mechanism result code is invalid")


@dataclass(frozen=True, slots=True)
class PeripheralStepVerification:
    verified: bool
    generation: str
    sample_id: str
    code: str

    def __post_init__(self) -> None:
        if (
            not is_peripheral_token(self.generation)
            or not is_peripheral_token(self.sample_id)
            or not CODE_RE.fullmatch(self.code)
        ):
            raise ValueError("peripheral step verification is invalid")


@dataclass(frozen=True, slots=True)
class PeripheralExecutionResult:
    outcome: PeripheralExecutionOutcome
    code: str
    applied_steps: tuple[PeripheralStepKind, ...] = ()
    recovered_steps: tuple[PeripheralStepKind, ...] = ()

    def __post_init__(self) -> None:
        if not CODE_RE.fullmatch(self.code):
            raise ValueError("peripheral execution result code is invalid")
        if len(self.applied_steps) > MAX_PERIPHERAL_STEPS or len(self.recovered_steps) > MAX_PERIPHERAL_STEPS:
            raise ValueError("peripheral execution step history exceeds its bound")
        if self.outcome is PeripheralExecutionOutcome.COMPLETED and not self.applied_steps:
            raise ValueError("completed peripheral execution requires applied steps")
        if self.outcome is PeripheralExecutionOutcome.RECOVERED and not self.recovered_steps:
            raise ValueError("recovered peripheral execution requires rollback evidence")
        if self.outcome is PeripheralExecutionOutcome.ACTION_REQUIRED and self.recovered_steps:
            raise ValueError("action-required peripheral execution cannot claim recovery")


class PeripheralPlanRevalidationPort(Protocol):
    def revalidate(
        self,
        direction: HandoffDirection,
        capabilities: EffectiveCapabilities,
        *,
        expected_generation: str,
        previous_sample_id: str,
        policy: ControllerHandoffPolicy = ControllerHandoffPolicy(),
    ) -> PeripheralHandoffPlan: ...


class PeripheralMechanismPort(Protocol):
    def apply(self, step: PeripheralPlanStep) -> PeripheralMechanismResult: ...

    def rollback(self, step: PeripheralPlanStep) -> PeripheralMechanismResult: ...


class PeripheralVerificationPort(Protocol):
    def verify_applied(
        self, step: PeripheralPlanStep
    ) -> PeripheralStepVerification: ...

    def verify_rollback(
        self, step: PeripheralPlanStep
    ) -> PeripheralStepVerification: ...


class PeripheralHandoffRunner:
    """Execute a planned child sequence with fresh evidence and bounded recovery."""

    def __init__(
        self,
        *,
        revalidation: PeripheralPlanRevalidationPort,
        mechanism: PeripheralMechanismPort,
        verification: PeripheralVerificationPort,
    ) -> None:
        self._revalidation = revalidation
        self._mechanism = mechanism
        self._verification = verification

    def run(
        self,
        plan: PeripheralHandoffPlan,
        capabilities: EffectiveCapabilities,
        policy: ControllerHandoffPolicy = ControllerHandoffPolicy(),
    ) -> PeripheralExecutionResult:
        if plan.status is not PeripheralPlanStatus.READY:
            return PeripheralExecutionResult(
                PeripheralExecutionOutcome.ACTION_REQUIRED,
                "peripheral.plan_not_ready",
            )
        if len(plan.steps) > MAX_PERIPHERAL_STEPS:
            return PeripheralExecutionResult(
                PeripheralExecutionOutcome.ACTION_REQUIRED,
                "peripheral.plan_exceeds_step_bound",
            )
        applied: list[PeripheralPlanStep] = []
        previous_sample = plan.observed_sample_id
        for step in plan.steps:
            revalidated = self._revalidate(plan, capabilities, policy, previous_sample)
            if revalidated is None:
                return self._recover(plan, capabilities, policy, applied, previous_sample, "peripheral.revalidation_unavailable")
            if not self._same_plan(plan, revalidated, previous_sample):
                return self._recover(plan, capabilities, policy, applied, previous_sample, "peripheral.plan_changed")
            previous_sample = revalidated.observed_sample_id
            result = self._apply(step)
            if result is None or not result.accepted:
                return self._recover(
                    plan, capabilities, policy, applied, previous_sample,
                    result.code if result is not None else "peripheral.mechanism_unavailable",
                )
            # An accepted apply may have changed the device even when its
            # subsequent observation fails. It is therefore rollback-required
            # before we attempt verification, not only after success.
            applied.append(step)
            verified = self._verify(
                step,
                plan.observed_generation,
                previous_sample,
                rollback=False,
            )
            if verified is None:
                return self._recover(plan, capabilities, policy, applied, previous_sample, "peripheral.apply_unverified")
            previous_sample = verified.sample_id
        return PeripheralExecutionResult(
            PeripheralExecutionOutcome.COMPLETED,
            "peripheral.completed",
            tuple(step.kind for step in applied),
        )

    def _recover(
        self,
        plan: PeripheralHandoffPlan,
        capabilities: EffectiveCapabilities,
        policy: ControllerHandoffPolicy,
        applied: list[PeripheralPlanStep],
        previous_sample: str,
        failure_code: str,
    ) -> PeripheralExecutionResult:
        recovered: list[PeripheralStepKind] = []
        for step in reversed(applied):
            revalidated = self._revalidate(plan, capabilities, policy, previous_sample)
            if revalidated is None or not self._same_plan(
                plan, revalidated, previous_sample
            ):
                return PeripheralExecutionResult(
                    PeripheralExecutionOutcome.ACTION_REQUIRED,
                    "peripheral.rollback_revalidation_failed",
                    tuple(item.kind for item in applied),
                )
            previous_sample = revalidated.observed_sample_id
            result = self._rollback(step)
            if result is None or not result.accepted:
                return PeripheralExecutionResult(
                    PeripheralExecutionOutcome.ACTION_REQUIRED,
                    result.code if result is not None else "peripheral.rollback_unavailable",
                    tuple(item.kind for item in applied),
                )
            verified = self._verify(
                step,
                plan.observed_generation,
                previous_sample,
                rollback=True,
            )
            if verified is None:
                return PeripheralExecutionResult(
                    PeripheralExecutionOutcome.ACTION_REQUIRED,
                    "peripheral.rollback_unverified",
                    tuple(item.kind for item in applied),
                )
            recovered.append(step.kind)
            previous_sample = verified.sample_id
        if recovered:
            return PeripheralExecutionResult(
                PeripheralExecutionOutcome.RECOVERED,
                failure_code,
                tuple(item.kind for item in applied),
                tuple(recovered),
            )
        return PeripheralExecutionResult(
            PeripheralExecutionOutcome.ACTION_REQUIRED, failure_code
        )

    def _revalidate(
        self, plan, capabilities, policy, previous_sample: str
    ) -> PeripheralHandoffPlan | None:
        try:
            return self._revalidation.revalidate(
                plan.direction,
                capabilities,
                expected_generation=plan.observed_generation,
                previous_sample_id=previous_sample,
                policy=policy,
            )
        except Exception:
            return None

    @staticmethod
    def _same_plan(
        expected: PeripheralHandoffPlan,
        observed: PeripheralHandoffPlan,
        previous_sample: str,
    ) -> bool:
        return (
            observed.status is PeripheralPlanStatus.READY
            and observed.direction is expected.direction
            and observed.observed_generation == expected.observed_generation
            and observed.observed_sample_id != previous_sample
            and observed.steps == expected.steps
            and not observed.blockers
        )

    def _apply(self, step: PeripheralPlanStep) -> PeripheralMechanismResult | None:
        try:
            return self._mechanism.apply(step)
        except Exception:
            return None

    def _rollback(self, step: PeripheralPlanStep) -> PeripheralMechanismResult | None:
        try:
            return self._mechanism.rollback(step)
        except Exception:
            return None

    def _verify(
        self,
        step: PeripheralPlanStep,
        expected_generation: str,
        previous_sample: str,
        *,
        rollback: bool,
    ) -> PeripheralStepVerification | None:
        try:
            result = (
                self._verification.verify_rollback(step)
                if rollback
                else self._verification.verify_applied(step)
            )
        except Exception:
            return None
        return (
            result
            if (
                result.verified
                and result.generation == expected_generation
                and result.sample_id != previous_sample
            )
            else None
        )
