from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.control_plane import (  # noqa: E402
    CapabilitySupport,
    EgpuCapabilities,
    ExperimentalTransitionPermit,
    HostCapabilities,
    PlacementState,
    compose_capabilities,
)
from regear.domain.manual_transition import (  # noqa: E402
    ManualTransitionEvidence,
    plan_manual_transition,
)
from regear.domain.models import GameState  # noqa: E402
from regear.profiles.ally_x import CAPABILITIES as ALLY_X  # noqa: E402
from regear.profiles.gpd_g1 import CAPABILITIES as GPD_G1  # noqa: E402


def verified_capabilities():
    return compose_capabilities(
        HostCapabilities(
            profile_id="test-host",
            egpu_support=CapabilitySupport.VERIFIED,
            display_handoff=CapabilitySupport.VERIFIED,
        ),
        EgpuCapabilities(
            profile_id="test-egpu",
            display_output=CapabilitySupport.VERIFIED,
        ),
    )


def evidence(**changes):
    value = ManualTransitionEvidence(
        observed_generation="generation-1",
        host_profile_id="test-host",
        egpu_profile_id="test-egpu",
        egpu_stable_id="egpu-1",
        internal_gpu_stable_id="internal-gpu",
        external_gpu_stable_id="egpu-1",
        internal_display_stable_id="internal-panel",
        external_display_stable_id="external-display",
        external_display_ready_verified=True,
        egpu_render_ready_verified=True,
        internal_display_ready_verified=True,
        source_recovery_ready_verified=True,
        game_state=GameState.IDLE,
    )
    return dataclasses.replace(value, **changes)


def decide(
    *,
    current=PlacementState.PORTABLE,
    target=PlacementState.DOCKED_EGPU,
    capabilities=None,
    facts=None,
    experimental_permit=None,
):
    return plan_manual_transition(
        plan_id="operation-1",
        request_id="request-1",
        current=current,
        target=target,
        capabilities=capabilities or verified_capabilities(),
        evidence=facts or evidence(),
        experimental_permit=experimental_permit,
    )


class ManualTransitionPlanningTests(unittest.TestCase):
    def test_verified_portable_to_docked_plan_has_one_typed_bounded_step(self):
        decision = decide()
        self.assertEqual(decision.blockers, ())
        self.assertEqual(len(decision.plan.steps), 1)
        self.assertEqual(
            decision.plan.steps[0].code,
            "presentation.apply_docked_egpu",
        )
        self.assertEqual(
            decision.plan.steps[0].expected_placement,
            PlacementState.DOCKED_EGPU,
        )

    def test_real_ally_g1_capability_remains_blocked_as_experimental(self):
        capabilities = compose_capabilities(ALLY_X, GPD_G1)
        decision = decide(
            capabilities=capabilities,
            facts=dataclasses.replace(
                evidence(),
                host_profile_id=capabilities.host_profile_id,
                egpu_profile_id=capabilities.egpu_profile_id,
            ),
        )
        self.assertIsNone(decision.plan)
        self.assertIn(
            "capability.display_handoff_unverified",
            decision.blockers,
        )

    def test_game_running_or_unknown_blocks_any_mutating_path(self):
        for game_state in (GameState.RUNNING, GameState.UNKNOWN):
            with self.subTest(game_state=game_state):
                decision = decide(facts=evidence(game_state=game_state))
                self.assertIsNone(decision.plan)
                self.assertTrue(any(code.startswith("game.") for code in decision.blockers))

    def test_dock_requires_identity_display_render_and_recovery_evidence(self):
        decision = decide(
            facts=evidence(
                host_profile_id="",
                egpu_profile_id="",
                egpu_stable_id="",
                external_display_ready_verified=False,
                egpu_render_ready_verified=False,
                source_recovery_ready_verified=False,
            )
        )
        self.assertIsNone(decision.plan)
        self.assertIn("identity.host_unverified", decision.blockers)
        # Host identity fails before a plan can use any subordinate evidence.
        self.assertNotIn("identity.egpu_unverified", decision.blockers)

        subordinate = decide(
            facts=evidence(
                egpu_profile_id="",
                egpu_stable_id="",
                external_display_ready_verified=False,
                egpu_render_ready_verified=False,
                source_recovery_ready_verified=False,
            )
        )
        self.assertEqual(
            subordinate.blockers,
            (
                "recovery.source_unverified",
                "identity.egpu_unverified",
                "display.external_unready",
                "render.egpu_unready",
                "identity.transition_binding_incomplete",
            ),
        )

    def test_restore_portable_requires_internal_display_and_recovery(self):
        decision = decide(
            current=PlacementState.DOCKED_EGPU,
            target=PlacementState.PORTABLE,
            facts=evidence(
                internal_display_ready_verified=False,
                source_recovery_ready_verified=False,
            ),
        )
        self.assertEqual(
            decision.blockers,
            (
                "recovery.source_unverified",
                "display.internal_unready",
            ),
        )

    def test_unknown_or_research_placement_has_no_manual_path(self):
        for current in (
            PlacementState.UNKNOWN,
            PlacementState.DEGRADED,
            PlacementState.BOOSTED_HANDHELD,
        ):
            with self.subTest(current=current):
                self.assertIsNone(decide(current=current).plan)

    def test_idle_docked_igpu_can_promote_through_the_same_durable_path(self):
        decision = decide(current=PlacementState.DOCKED_IGPU)

        self.assertIsNotNone(decision.plan)
        self.assertEqual(
            decision.plan.from_placement, PlacementState.DOCKED_IGPU
        )
        self.assertEqual(
            decision.plan.target_placement, PlacementState.DOCKED_EGPU
        )
        self.assertEqual(
            decision.plan.steps[0].code,
            "presentation.apply_docked_egpu",
        )

    def test_verified_no_op_has_no_step_or_mechanism_preconditions(self):
        decision = decide(
            target=PlacementState.PORTABLE,
            capabilities=compose_capabilities(ALLY_X, GPD_G1),
            facts=evidence(
                host_profile_id=ALLY_X.profile_id,
                egpu_profile_id="",
                egpu_stable_id="",
                external_display_ready_verified=False,
                egpu_render_ready_verified=False,
                internal_display_ready_verified=False,
                source_recovery_ready_verified=False,
                game_state=GameState.UNKNOWN,
            ),
        )
        self.assertIsNotNone(decision.plan)
        self.assertEqual(decision.plan.steps, ())

    def test_exact_permit_can_plan_experimental_ally_g1_path(self):
        capabilities = compose_capabilities(ALLY_X, GPD_G1)
        facts = dataclasses.replace(
            evidence(),
            host_profile_id=capabilities.host_profile_id,
            egpu_profile_id=capabilities.egpu_profile_id,
        )
        permit = ExperimentalTransitionPermit(
            permit_id="permit-1",
            plan_id="operation-1",
            observed_generation=facts.observed_generation,
            target_placement=PlacementState.DOCKED_EGPU,
            host_profile_id=capabilities.host_profile_id,
            egpu_profile_id=capabilities.egpu_profile_id,
            egpu_stable_id=facts.egpu_stable_id,
        )
        decision = decide(
            capabilities=capabilities,
            facts=facts,
            experimental_permit=permit,
        )
        self.assertIsNotNone(decision.plan)
        self.assertTrue(decision.plan.experimental)


if __name__ == "__main__":
    unittest.main()
