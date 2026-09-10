from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.peripheral_handoff import (  # noqa: E402
    PeripheralHandoffPlanningService,
    plan_peripheral_handoff,
)
from regear.domain.control_plane import (  # noqa: E402
    CapabilitySupport,
    EgpuCapabilities,
    HostCapabilities,
    compose_capabilities,
)
from regear.domain.peripheral_handoff import (  # noqa: E402
    AudioOutput,
    AudioPeripheralState,
    ControllerHandoffPolicy,
    ControllerPeripheralState,
    HandoffDirection,
    PeripheralObservation,
    PeripheralPlanStatus,
    PeripheralStepKind,
)
from regear.profiles.ally_x import CAPABILITIES as ALLY_X  # noqa: E402
from regear.profiles.gpd_g1 import CAPABILITIES as GPD_G1  # noqa: E402


def capabilities(**host_changes):
    host = HostCapabilities(
        profile_id="test-host",
        audio_handoff=CapabilitySupport.VERIFIED,
        external_controller_promotion=CapabilitySupport.VERIFIED,
        internal_controller_suppression=CapabilitySupport.VERIFIED,
        external_controller_disconnect=CapabilitySupport.VERIFIED,
        external_controller_power_off=CapabilitySupport.VERIFIED,
    )
    return compose_capabilities(
        dataclasses.replace(host, **host_changes),
        EgpuCapabilities(
            profile_id="test-egpu",
            audio_output=CapabilitySupport.VERIFIED,
        ),
    )


def observed(**changes):
    value = PeripheralObservation(
        schema_version=1,
        generation="peripheral-generation-a",
        sample_id="peripheral-sample-a",
        controller=ControllerPeripheralState(
            complete=True,
            exact=True,
            failure_code="",
            builtin_binding="controller-builtin-private",
            builtin_available=True,
            builtin_input_verified=True,
            builtin_restore_verified=True,
            external_binding="controller-external-private",
            external_connected=True,
            external_input_verified=True,
        ),
        audio=AudioPeripheralState(
            complete=True,
            exact=True,
            failure_code="",
            current_output=AudioOutput.INTERNAL,
            current_output_binding="audio-current-private",
            current_output_usable_verified=True,
            external_output_binding="audio-external-private",
            external_output_available=True,
            external_output_verified=True,
            portable_output_binding="audio-portable-private",
            portable_output_available=True,
            portable_output_verified=True,
            rollback_output_verified=True,
        ),
    )
    return dataclasses.replace(value, **changes)


class QueueObservations:
    def __init__(self, *values):
        self.values = list(values)

    def observe(self):
        return self.values.pop(0)


class PeripheralHandoffOrchestrationTests(unittest.TestCase):
    def test_dock_orders_promotion_audio_then_optional_suppression(self):
        plan = plan_peripheral_handoff(
            HandoffDirection.DOCK,
            observed(),
            capabilities(),
            ControllerHandoffPolicy(suppress_builtin_when_docked=True),
        )
        self.assertEqual(plan.status, PeripheralPlanStatus.READY)
        self.assertEqual(
            tuple(step.kind for step in plan.steps),
            (
                PeripheralStepKind.PROMOTE_EXTERNAL_CONTROLLER,
                PeripheralStepKind.SELECT_EXTERNAL_AUDIO,
                PeripheralStepKind.SUPPRESS_BUILTIN_CONTROLLER,
            ),
        )
        self.assertTrue(all(step.verify_after for step in plan.steps))

    def test_suppression_is_omitted_without_verified_recovery(self):
        state = observed()
        state = dataclasses.replace(
            state,
            controller=dataclasses.replace(
                state.controller, builtin_restore_verified=False
            ),
        )
        plan = plan_peripheral_handoff(
            HandoffDirection.DOCK,
            state,
            capabilities(),
            ControllerHandoffPolicy(suppress_builtin_when_docked=True),
        )
        self.assertNotIn(
            PeripheralStepKind.SUPPRESS_BUILTIN_CONTROLLER,
            tuple(step.kind for step in plan.steps),
        )
        self.assertIn("controller.suppression_recovery_unverified", plan.blockers)

    def test_controller_loss_restores_builtin_before_any_other_work(self):
        plan = plan_peripheral_handoff(
            HandoffDirection.EXTERNAL_CONTROLLER_LOST,
            observed(),
            capabilities(),
        )
        self.assertEqual(
            tuple(step.kind for step in plan.steps),
            (
                PeripheralStepKind.RESTORE_BUILTIN_CONTROLLER,
                PeripheralStepKind.PROMOTE_BUILTIN_CONTROLLER,
            ),
        )

    def test_undock_places_external_power_action_last(self):
        plan = plan_peripheral_handoff(
            HandoffDirection.UNDOCK,
            observed(),
            capabilities(),
            ControllerHandoffPolicy(
                disconnect_external_when_undocked=True,
                power_off_external_when_undocked=True,
            ),
        )
        kinds = tuple(step.kind for step in plan.steps)
        self.assertEqual(kinds[:2], (
            PeripheralStepKind.RESTORE_BUILTIN_CONTROLLER,
            PeripheralStepKind.PROMOTE_BUILTIN_CONTROLLER,
        ))
        self.assertEqual(kinds[-1], PeripheralStepKind.POWER_OFF_EXTERNAL_CONTROLLER)

    def test_unknown_external_presence_makes_requested_cleanup_partial(self):
        state = observed()
        state = dataclasses.replace(
            state,
            controller=dataclasses.replace(
                state.controller, external_connected=None
            ),
        )
        plan = plan_peripheral_handoff(
            HandoffDirection.UNDOCK,
            state,
            capabilities(),
            ControllerHandoffPolicy(disconnect_external_when_undocked=True),
        )
        self.assertEqual(plan.status, PeripheralPlanStatus.PARTIAL)
        self.assertIn("controller.external_presence_unknown", plan.blockers)
        self.assertNotIn(
            PeripheralStepKind.DISCONNECT_EXTERNAL_CONTROLLER,
            tuple(step.kind for step in plan.steps),
        )

    def test_power_off_falls_back_only_to_verified_disconnect(self):
        policy = ControllerHandoffPolicy(
            disconnect_external_when_undocked=True,
            power_off_external_when_undocked=True,
        )
        plan = plan_peripheral_handoff(
            HandoffDirection.UNDOCK,
            observed(),
            capabilities(
                external_controller_power_off=CapabilitySupport.UNKNOWN
            ),
            policy,
        )
        self.assertEqual(
            plan.steps[-1].kind,
            PeripheralStepKind.DISCONNECT_EXTERNAL_CONTROLLER,
        )
        unavailable = plan_peripheral_handoff(
            HandoffDirection.UNDOCK,
            observed(),
            capabilities(
                external_controller_power_off=CapabilitySupport.UNKNOWN,
                external_controller_disconnect=CapabilitySupport.UNKNOWN,
            ),
            policy,
        )
        self.assertNotIn(
            PeripheralStepKind.DISCONNECT_EXTERNAL_CONTROLLER,
            tuple(step.kind for step in unavailable.steps),
        )
        self.assertEqual(unavailable.status, PeripheralPlanStatus.PARTIAL)
        self.assertIn(
            "capability.external_controller_power_off_unverified",
            unavailable.blockers,
        )
        self.assertIn(
            "capability.external_controller_disconnect_unverified",
            unavailable.blockers,
        )

    def test_audio_unavailable_preserves_current_output(self):
        state = observed()
        state = dataclasses.replace(
            state,
            audio=dataclasses.replace(
                state.audio,
                external_output_available=False,
                external_output_verified=False,
            ),
        )
        plan = plan_peripheral_handoff(
            HandoffDirection.DOCK, state, capabilities()
        )
        self.assertNotIn(
            PeripheralStepKind.SELECT_EXTERNAL_AUDIO,
            tuple(step.kind for step in plan.steps),
        )
        self.assertIn("audio.external_unavailable_or_unverified", plan.blockers)

    def test_audio_restore_uses_exact_private_target_and_rollback(self):
        plan = plan_peripheral_handoff(
            HandoffDirection.UNDOCK, observed(), capabilities()
        )
        step = next(
            step
            for step in plan.steps
            if step.kind is PeripheralStepKind.RESTORE_PORTABLE_AUDIO
        )
        self.assertEqual(step.target_binding, "audio-portable-private")
        self.assertEqual(step.rollback_binding, "audio-current-private")

    def test_incomplete_changed_or_repeated_evidence_fails_closed(self):
        base = observed()
        incomplete = dataclasses.replace(
            base,
            controller=dataclasses.replace(
                base.controller,
                complete=False,
                exact=False,
                failure_code="controller.scan_failed",
            ),
            audio=dataclasses.replace(
                base.audio,
                complete=False,
                exact=False,
                failure_code="audio.scan_failed",
            ),
        )
        cases = (
            plan_peripheral_handoff(
                HandoffDirection.DOCK, incomplete, capabilities()
            ),
            plan_peripheral_handoff(
                HandoffDirection.DOCK,
                observed(),
                capabilities(),
                expected_generation="different-generation",
            ),
            plan_peripheral_handoff(
                HandoffDirection.DOCK,
                observed(),
                capabilities(),
                previous_sample_id="peripheral-sample-a",
            ),
        )
        for plan in cases:
            with self.subTest(blockers=plan.blockers):
                self.assertEqual(plan.status, PeripheralPlanStatus.ACTION_REQUIRED)
                self.assertEqual(plan.steps, ())

    def test_fresh_revalidation_requires_same_semantics_and_new_sample(self):
        first = observed()
        second = dataclasses.replace(first, sample_id="peripheral-sample-b")
        service = PeripheralHandoffPlanningService(QueueObservations(first, second))
        preview = service.preview(HandoffDirection.DOCK, capabilities())
        verified = service.revalidate(
            HandoffDirection.DOCK,
            capabilities(),
            expected_generation=preview.observed_generation,
            previous_sample_id=preview.observed_sample_id,
        )
        self.assertEqual(verified.status, PeripheralPlanStatus.READY)
        self.assertNotEqual(verified.observed_sample_id, preview.observed_sample_id)

    def test_revalidation_rejects_missing_or_invalid_identity_gates(self):
        service = PeripheralHandoffPlanningService(QueueObservations(observed()))
        for generation, sample in (
            ("", "peripheral-sample-a"),
            ("peripheral-generation-a", ""),
            ("contains spaces", "peripheral-sample-a"),
            ("peripheral-generation-a", "contains/slash"),
        ):
            with self.subTest(generation=generation, sample=sample):
                with self.assertRaises(ValueError):
                    service.revalidate(
                        HandoffDirection.DOCK,
                        capabilities(),
                        expected_generation=generation,
                        previous_sample_id=sample,
                    )

    def test_missing_controller_binding_does_not_erase_safe_audio_plan(self):
        state = observed()
        state = dataclasses.replace(
            state,
            controller=dataclasses.replace(state.controller, external_binding=""),
        )
        plan = plan_peripheral_handoff(
            HandoffDirection.DOCK, state, capabilities()
        )
        self.assertEqual(
            tuple(step.kind for step in plan.steps),
            (PeripheralStepKind.SELECT_EXTERNAL_AUDIO,),
        )
        self.assertEqual(plan.status, PeripheralPlanStatus.PARTIAL)
        self.assertIn("controller.external_binding_missing", plan.blockers)

    def test_missing_external_binding_cannot_leave_suppression_step(self):
        state = observed()
        state = dataclasses.replace(
            state,
            controller=dataclasses.replace(state.controller, external_binding=""),
        )
        plan = plan_peripheral_handoff(
            HandoffDirection.DOCK,
            state,
            capabilities(),
            ControllerHandoffPolicy(suppress_builtin_when_docked=True),
        )
        kinds = tuple(step.kind for step in plan.steps)
        self.assertNotIn(PeripheralStepKind.PROMOTE_EXTERNAL_CONTROLLER, kinds)
        self.assertNotIn(PeripheralStepKind.SUPPRESS_BUILTIN_CONTROLLER, kinds)
        self.assertIn(
            "controller.suppression_requires_promotion_step", plan.blockers
        )

    def test_incomplete_controller_scan_does_not_erase_exact_audio_plan(self):
        state = observed()
        state = dataclasses.replace(
            state,
            controller=dataclasses.replace(
                state.controller,
                complete=False,
                exact=False,
                failure_code="controller.scan_failed",
            ),
        )
        plan = plan_peripheral_handoff(
            HandoffDirection.DOCK, state, capabilities()
        )
        self.assertEqual(plan.status, PeripheralPlanStatus.PARTIAL)
        self.assertEqual(
            tuple(step.kind for step in plan.steps),
            (PeripheralStepKind.SELECT_EXTERNAL_AUDIO,),
        )
        self.assertIn("controller.scan_failed", plan.blockers)

    def test_audio_failure_never_suppresses_or_disconnects_last_input(self):
        state = observed()
        state = dataclasses.replace(
            state,
            controller=dataclasses.replace(
                state.controller,
                builtin_available=None,
                builtin_input_verified=False,
                builtin_restore_verified=False,
            ),
            audio=dataclasses.replace(state.audio, portable_output_binding=""),
        )
        plan = plan_peripheral_handoff(
            HandoffDirection.UNDOCK,
            state,
            capabilities(),
            ControllerHandoffPolicy(disconnect_external_when_undocked=True),
        )
        self.assertEqual(plan.steps, ())
        self.assertEqual(plan.status, PeripheralPlanStatus.ACTION_REQUIRED)

    def test_real_profile_authorizes_no_controller_or_audio_mutation(self):
        plan = plan_peripheral_handoff(
            HandoffDirection.DOCK,
            observed(),
            compose_capabilities(ALLY_X, GPD_G1),
            ControllerHandoffPolicy(suppress_builtin_when_docked=True),
        )
        self.assertEqual(plan.steps, ())
        self.assertEqual(plan.status, PeripheralPlanStatus.ACTION_REQUIRED)

    def test_public_trace_omits_private_bindings_and_observation_ids(self):
        plan = plan_peripheral_handoff(
            HandoffDirection.DOCK, observed(), capabilities()
        )
        encoded = repr(plan.public_trace())
        for private in (
            "controller-builtin-private",
            "controller-external-private",
            "audio-current-private",
            "audio-external-private",
            "peripheral-generation-a",
            "peripheral-sample-a",
        ):
            self.assertNotIn(private, encoded)


if __name__ == "__main__":
    unittest.main()
