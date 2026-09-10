from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.peripheral_handoff_runner import (  # noqa: E402
    PeripheralExecutionOutcome,
    PeripheralHandoffRunner,
    PeripheralMechanismResult,
    PeripheralStepVerification,
)
from regear.domain.control_plane import (  # noqa: E402
    CapabilitySupport,
    EgpuCapabilities,
    HostCapabilities,
    compose_capabilities,
)
from regear.domain.peripheral_handoff import (  # noqa: E402
    HandoffDirection,
    PeripheralHandoffPlan,
    PeripheralPlanStatus,
    PeripheralPlanStep,
    PeripheralStepKind,
)


CAPABILITIES = compose_capabilities(
    HostCapabilities(profile_id="host", audio_handoff=CapabilitySupport.VERIFIED),
    EgpuCapabilities(profile_id="egpu", audio_output=CapabilitySupport.VERIFIED),
)


def plan(*, steps=None, status=PeripheralPlanStatus.READY, sample="sample-a"):
    return PeripheralHandoffPlan(
        status,
        HandoffDirection.UNDOCK,
        "generation-a",
        sample,
        steps
        if steps is not None
        else (
            PeripheralPlanStep(
                PeripheralStepKind.RESTORE_BUILTIN_CONTROLLER,
                "builtin-binding",
                "external-binding",
            ),
            PeripheralPlanStep(
                PeripheralStepKind.RESTORE_PORTABLE_AUDIO,
                "portable-audio",
                "external-audio",
            ),
        ),
        () if status is PeripheralPlanStatus.READY else ("peripheral.not_ready",),
    )


class Revalidation:
    def __init__(self, values):
        self.values = list(values)
        self.calls = []

    def revalidate(self, direction, capabilities, *, expected_generation, previous_sample_id, policy):
        self.calls.append((direction, expected_generation, previous_sample_id))
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class Mechanism:
    def __init__(self, *, apply=None, rollback=None):
        self.apply_values = list(apply or [])
        self.rollback_values = list(rollback or [])
        self.calls = []

    def apply(self, step):
        self.calls.append(("apply", step.kind))
        value = self.apply_values.pop(0)
        return value

    def rollback(self, step):
        self.calls.append(("rollback", step.kind))
        value = self.rollback_values.pop(0)
        return value


class Verification:
    def __init__(self, *, applied=None, rollback=None):
        self.applied = list(applied or [])
        self.rollback = list(rollback or [])
        self.calls = []

    def verify_applied(self, step):
        self.calls.append(("apply", step.kind))
        return self.applied.pop(0)

    def verify_rollback(self, step):
        self.calls.append(("rollback", step.kind))
        return self.rollback.pop(0)


def accepted(code="peripheral.applied"):
    return PeripheralMechanismResult(True, code)


def rejected(code="peripheral.rejected"):
    return PeripheralMechanismResult(False, code)


def verified(sample):
    return PeripheralStepVerification(True, "generation-a", sample, "peripheral.verified")


class PeripheralHandoffRunnerTests(unittest.TestCase):
    def test_executes_only_after_fresh_exact_revalidation_and_verification(self):
        original = plan()
        revalidation = Revalidation((plan(sample="sample-b"), plan(sample="sample-d")))
        mechanism = Mechanism(apply=(accepted(), accepted()))
        verification = Verification(applied=(verified("sample-c"), verified("sample-e")))

        result = PeripheralHandoffRunner(
            revalidation=revalidation, mechanism=mechanism, verification=verification
        ).run(original, CAPABILITIES)

        self.assertEqual(result.outcome, PeripheralExecutionOutcome.COMPLETED)
        self.assertEqual(result.applied_steps, (
            PeripheralStepKind.RESTORE_BUILTIN_CONTROLLER,
            PeripheralStepKind.RESTORE_PORTABLE_AUDIO,
        ))
        self.assertEqual([call[0] for call in mechanism.calls], ["apply", "apply"])

    def test_apply_failure_rolls_back_only_prior_verified_steps_in_reverse_order(self):
        original = plan()
        revalidation = Revalidation((
            plan(sample="sample-b"), plan(sample="sample-d"), plan(sample="sample-e"),
        ))
        mechanism = Mechanism(
            apply=(accepted(), rejected("peripheral.audio_apply_failed")),
            rollback=(accepted("peripheral.rollback_accepted"),),
        )
        verification = Verification(
            applied=(verified("sample-c"),), rollback=(verified("sample-f"),)
        )

        result = PeripheralHandoffRunner(
            revalidation=revalidation, mechanism=mechanism, verification=verification
        ).run(original, CAPABILITIES)

        self.assertEqual(result.outcome, PeripheralExecutionOutcome.RECOVERED)
        self.assertEqual(result.code, "peripheral.audio_apply_failed")
        self.assertEqual(result.recovered_steps, (PeripheralStepKind.RESTORE_BUILTIN_CONTROLLER,))
        self.assertEqual(mechanism.calls, [
            ("apply", PeripheralStepKind.RESTORE_BUILTIN_CONTROLLER),
            ("apply", PeripheralStepKind.RESTORE_PORTABLE_AUDIO),
            ("rollback", PeripheralStepKind.RESTORE_BUILTIN_CONTROLLER),
        ])

    def test_changed_plan_or_stale_verification_fails_closed_and_recovers(self):
        original = plan()
        changed = dataclasses.replace(plan(sample="sample-b"), steps=plan().steps[:1])
        result = PeripheralHandoffRunner(
            revalidation=Revalidation((changed,)),
            mechanism=Mechanism(),
            verification=Verification(),
        ).run(original, CAPABILITIES)
        self.assertEqual(result.outcome, PeripheralExecutionOutcome.ACTION_REQUIRED)
        self.assertEqual(result.code, "peripheral.plan_changed")

        revalidation = Revalidation((plan(sample="sample-b"), plan(sample="sample-c")))
        mechanism = Mechanism(apply=(accepted(),), rollback=(accepted(),))
        verification = Verification(
            applied=(verified("sample-b"),), rollback=(verified("sample-d"),)
        )
        stale = PeripheralHandoffRunner(
            revalidation=revalidation, mechanism=mechanism, verification=verification
        ).run(original, CAPABILITIES)
        self.assertEqual(stale.outcome, PeripheralExecutionOutcome.RECOVERED)
        self.assertEqual(stale.code, "peripheral.apply_unverified")

    def test_non_ready_plan_never_calls_any_port(self):
        blocked = plan(status=PeripheralPlanStatus.ACTION_REQUIRED, steps=())
        revalidation = Revalidation(())
        mechanism = Mechanism()
        verification = Verification()

        result = PeripheralHandoffRunner(
            revalidation=revalidation, mechanism=mechanism, verification=verification
        ).run(blocked, CAPABILITIES)

        self.assertEqual(result.outcome, PeripheralExecutionOutcome.ACTION_REQUIRED)
        self.assertEqual(result.code, "peripheral.plan_not_ready")
        self.assertEqual(revalidation.calls, [])
        self.assertEqual(mechanism.calls, [])
        self.assertEqual(verification.calls, [])


if __name__ == "__main__":
    unittest.main()
