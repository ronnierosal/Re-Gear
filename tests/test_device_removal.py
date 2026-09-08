from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.domain.device_removal import (  # noqa: E402
    RemovalFunction,
    RemovalFunctionKind,
    RemovalPlan,
    RemovalPlanState,
    compose_removal_plan,
    plan_is_current,
)
from hdm.domain.removal_safety import RemovalSafety, RemovalSafetyState  # noqa: E402
from hdm.domain.safe_undock_readiness import SafeUndockRevalidation  # noqa: E402


BINDING = "egpu-stable-id"
GENERATION = "peripheral-generation"
SAMPLE = "peripheral-sample"

#: The functions measured on the tested profile.
GPU = RemovalFunction(RemovalFunctionKind.GPU, "0000:08:00.0")
AUDIO = RemovalFunction(RemovalFunctionKind.AUDIO, "0000:08:00.1")


def ready() -> RemovalSafety:
    return RemovalSafety(
        RemovalSafetyState.READY_FOR_SUPERVISED_REMOVAL,
        "removal_safety.ready_for_supervised_removal",
        SafeUndockRevalidation(BINDING, GENERATION, SAMPLE),
    )


def blocked(code: str = "removal_safety.clients_active_or_protected") -> RemovalSafety:
    return RemovalSafety(RemovalSafetyState.NOT_READY, code)


class FunctionValidationTests(unittest.TestCase):
    def test_address_must_be_a_pci_address(self) -> None:
        with self.assertRaises(ValueError):
            RemovalFunction(RemovalFunctionKind.GPU, "08:00.0")

    def test_function_out_of_range_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            RemovalFunction(RemovalFunctionKind.GPU, "0000:08:00.9")


class ReadinessGateTests(unittest.TestCase):
    def test_blocked_readiness_blocks_the_plan(self) -> None:
        plan = compose_removal_plan(blocked(), (GPU, AUDIO))
        self.assertIs(plan.state, RemovalPlanState.NOT_READY)
        self.assertEqual(plan.functions, ())

    def test_readiness_code_is_preserved_not_translated(self) -> None:
        plan = compose_removal_plan(blocked("removal_safety.game_running"), (GPU, AUDIO))
        self.assertEqual(plan.code, "removal_safety.game_running")

    def test_insufficient_evidence_blocks_the_plan(self) -> None:
        readiness = RemovalSafety(
            RemovalSafetyState.EVIDENCE_INSUFFICIENT, "removal_safety.topology_unverified"
        )
        self.assertIs(
            compose_removal_plan(readiness, (GPU, AUDIO)).state,
            RemovalPlanState.NOT_READY,
        )

    def test_ready_without_revalidation_cannot_compose(self) -> None:
        """RemovalSafety forbids this shape, so guard it rather than assume."""
        readiness = RemovalSafety.__new__(RemovalSafety)
        object.__setattr__(readiness, "state", RemovalSafetyState.READY_FOR_SUPERVISED_REMOVAL)
        object.__setattr__(readiness, "code", "removal_safety.ready_for_supervised_removal")
        object.__setattr__(readiness, "revalidation", None)
        plan = compose_removal_plan(readiness, (GPU, AUDIO))
        self.assertIs(plan.state, RemovalPlanState.EVIDENCE_INCOMPLETE)
        self.assertEqual(plan.code, "device_removal.revalidation_missing")


class MultiFunctionTests(unittest.TestCase):
    """Removing one function of a multi-function device leaves the other bound."""

    def test_gpu_only_is_refused(self) -> None:
        plan = compose_removal_plan(ready(), (GPU,))
        self.assertIs(plan.state, RemovalPlanState.EVIDENCE_INCOMPLETE)
        self.assertEqual(plan.code, "device_removal.missing_audio")

    def test_audio_only_is_refused(self) -> None:
        plan = compose_removal_plan(ready(), (AUDIO,))
        self.assertIs(plan.state, RemovalPlanState.EVIDENCE_INCOMPLETE)
        self.assertEqual(plan.code, "device_removal.missing_gpu")

    def test_no_functions_is_refused(self) -> None:
        plan = compose_removal_plan(ready(), ())
        self.assertIs(plan.state, RemovalPlanState.EVIDENCE_INCOMPLETE)
        self.assertEqual(plan.code, "device_removal.missing_audio_and_gpu")

    def test_duplicate_kind_is_invalid(self) -> None:
        other = RemovalFunction(RemovalFunctionKind.GPU, "0000:08:00.2")
        plan = compose_removal_plan(ready(), (GPU, AUDIO, other))
        self.assertIs(plan.state, RemovalPlanState.INVALID)
        self.assertEqual(plan.code, "device_removal.duplicate_function_kind")

    def test_duplicate_address_is_invalid(self) -> None:
        clash = RemovalFunction(RemovalFunctionKind.AUDIO, "0000:08:00.0")
        plan = compose_removal_plan(ready(), (GPU, clash))
        self.assertIs(plan.state, RemovalPlanState.INVALID)
        self.assertEqual(plan.code, "device_removal.duplicate_address")


class OrderTests(unittest.TestCase):
    def test_audio_is_removed_before_the_gpu(self) -> None:
        """The order the successful supervised run used; nothing establishes
        that the reverse also works."""
        plan = compose_removal_plan(ready(), (GPU, AUDIO))
        self.assertEqual(plan.addresses, ("0000:08:00.1", "0000:08:00.0"))

    def test_order_is_independent_of_input_order(self) -> None:
        forward = compose_removal_plan(ready(), (GPU, AUDIO)).addresses
        backward = compose_removal_plan(ready(), (AUDIO, GPU)).addresses
        self.assertEqual(forward, backward)


class BindingTests(unittest.TestCase):
    def test_plan_carries_the_authorising_observation(self) -> None:
        plan = compose_removal_plan(ready(), (GPU, AUDIO))
        self.assertEqual(plan.attachment_binding, BINDING)
        self.assertEqual(plan.generation, GENERATION)
        self.assertEqual(plan.sample_id, SAMPLE)

    def test_matching_observation_is_current(self) -> None:
        plan = compose_removal_plan(ready(), (GPU, AUDIO))
        self.assertTrue(
            plan_is_current(
                plan,
                attachment_binding=BINDING,
                generation=GENERATION,
                sample_id=SAMPLE,
            )
        )

    def test_changed_attachment_is_not_current(self) -> None:
        plan = compose_removal_plan(ready(), (GPU, AUDIO))
        self.assertFalse(
            plan_is_current(
                plan,
                attachment_binding="a-different-egpu",
                generation=GENERATION,
                sample_id=SAMPLE,
            )
        )

    def test_newer_sample_is_not_current(self) -> None:
        plan = compose_removal_plan(ready(), (GPU, AUDIO))
        self.assertFalse(
            plan_is_current(
                plan,
                attachment_binding=BINDING,
                generation=GENERATION,
                sample_id="a-newer-sample",
            )
        )

    def test_an_unusable_plan_is_never_current(self) -> None:
        plan = compose_removal_plan(blocked(), (GPU, AUDIO))
        self.assertFalse(
            plan_is_current(
                plan, attachment_binding="", generation="", sample_id=""
            )
        )


class PlanInvariantTests(unittest.TestCase):
    def test_unusable_plan_cannot_carry_functions(self) -> None:
        with self.assertRaises(ValueError):
            RemovalPlan(RemovalPlanState.NOT_READY, "code", (GPU, AUDIO))

    def test_composed_plan_requires_functions(self) -> None:
        with self.assertRaises(ValueError):
            RemovalPlan(RemovalPlanState.COMPOSED, "code", ())

    def test_composed_plan_requires_observation_identity(self) -> None:
        with self.assertRaises(ValueError):
            RemovalPlan(RemovalPlanState.COMPOSED, "code", (AUDIO, GPU))

    def test_invalid_input_types_are_refused(self) -> None:
        self.assertIs(
            compose_removal_plan(ready(), [GPU, AUDIO]).state, RemovalPlanState.INVALID
        )
        self.assertIs(
            compose_removal_plan("not-readiness", (GPU, AUDIO)).state,
            RemovalPlanState.INVALID,
        )


if __name__ == "__main__":
    unittest.main()
