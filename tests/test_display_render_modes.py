from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.delivery.gamescope_wrapper import GamescopeLaunchConfig  # noqa: E402
from hdm.domain.control_plane import (  # noqa: E402
    CapabilitySupport,
    EgpuCapabilities,
    HostCapabilities,
    PlacementState,
    compose_capabilities,
)
from hdm.domain.display_render_modes import (  # noqa: E402
    COMBINATIONS,
    DisplayTarget,
    RenderGpu,
    RouteSupport,
    classify_change,
    combination_for,
)
from hdm.domain.inference import infer_operating_mode  # noqa: E402
from hdm.domain.manual_transition import (  # noqa: E402
    ManualTransitionEvidence,
    plan_manual_transition,
)
from hdm.domain.models import (  # noqa: E402
    Confidence,
    DisplayKind,
    DisplayObservation,
    GameState,
    GamescopeObservation,
    GpuObservation,
    GpuRole,
    ObservedSnapshot,
    OperatingMode,
    SupportTier,
)
from hdm.profiles.ally_x import CAPABILITIES as ALLY_X  # noqa: E402
from hdm.profiles.gpd_g1 import CAPABILITIES as GPD_G1  # noqa: E402


PLACEMENTS = (
    PlacementState.PORTABLE,
    PlacementState.BOOSTED_HANDHELD,
    PlacementState.DOCKED_IGPU,
    PlacementState.DOCKED_EGPU,
)


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


def snapshot_for(placement: PlacementState) -> ObservedSnapshot:
    """Build the exact verified snapshot that infers one placement."""
    combination = combination_for(placement)
    assert combination is not None
    internal_renders = combination.render is RenderGpu.INTERNAL
    internal_display = combination.display is DisplayTarget.INTERNAL_PANEL
    connector = "eDP-1" if internal_display else "DP-1"
    gpus = (
        GpuObservation(
            stable_id="internal-gpu",
            role=GpuRole.INTERNAL,
            vendor_device="1002:150e",
            present=True,
            selected_for_render=internal_renders,
            confidence=Confidence.VERIFIED,
        ),
        GpuObservation(
            stable_id="egpu-1",
            role=GpuRole.EXTERNAL,
            vendor_device="1002:7480",
            present=True,
            selected_for_render=not internal_renders,
            confidence=Confidence.VERIFIED,
        ),
    )
    displays = (
        DisplayObservation(
            stable_id="internal-panel",
            kind=DisplayKind.INTERNAL,
            connector="eDP-1",
            connected=True,
            active=internal_display,
            edid_ready=True,
            confidence=Confidence.VERIFIED,
        ),
        DisplayObservation(
            stable_id="external-display",
            kind=DisplayKind.EXTERNAL,
            connector="DP-1",
            connected=True,
            active=not internal_display,
            edid_ready=True,
            confidence=Confidence.VERIFIED,
        ),
    )
    return ObservedSnapshot(
        schema_version=1,
        observed_at="2026-09-10T00:00:00+00:00",
        host_profile="test-host",
        support_tier=SupportTier.CERTIFIED,
        gpus=gpus,
        displays=displays,
        gamescope=GamescopeObservation(
            running=True,
            pid=4242,
            output_order=(connector,),
            render_gpu_stable_id="internal-gpu" if internal_renders else "egpu-1",
            confidence=Confidence.VERIFIED,
        ),
        game_state=GameState.IDLE,
    )


class CombinationTableTests(unittest.TestCase):
    def test_every_observable_placement_is_described(self):
        self.assertEqual(set(COMBINATIONS), set(PLACEMENTS))

    def test_unknown_and_degraded_are_not_combinations(self):
        for placement in (PlacementState.UNKNOWN, PlacementState.DEGRADED):
            self.assertIsNone(combination_for(placement))

    def test_each_described_axis_pair_is_unique(self):
        pairs = {
            (item.display, item.render) for item in COMBINATIONS.values()
        }
        self.assertEqual(len(pairs), len(COMBINATIONS))

    def test_described_axes_match_placement_inference(self):
        """The table's display/render axes are the ones inference derives."""
        for placement in PLACEMENTS:
            from hdm.domain.inference import infer_placement

            self.assertIs(infer_placement(snapshot_for(placement)), placement)

    def test_described_public_mode_matches_inference(self):
        for placement, combination in COMBINATIONS.items():
            inferred = infer_operating_mode(snapshot_for(placement)).mode
            self.assertIs(inferred, combination.public_mode, placement)

    def test_docked_igpu_has_no_public_mode_today(self):
        """Recorded gap: a Docked-iGPU player is shown Unknown, not a mode."""
        self.assertIs(
            COMBINATIONS[PlacementState.DOCKED_IGPU].public_mode,
            OperatingMode.UNKNOWN,
        )

    def test_representable_targets_are_exactly_the_launch_config_targets(self):
        described = {
            item.launch_config_target
            for item in COMBINATIONS.values()
            if item.launch_config_target
        }
        self.assertEqual(described, {"portable", "docked_igpu", "docked_egpu"})
        for target in described:
            # Each described target must be a value the launch config accepts.
            GamescopeLaunchConfig(
                boot_id_sha256="a" * 64,
                target=target,
                internal_connector="eDP-1",
                external_connector="DP-1" if target != "portable" else "",
                vendor_device="1002:7480" if target != "portable" else "",
                egpu_binding_sha256="b" * 64 if target != "portable" else "",
            )

    def test_boosted_handheld_is_unrepresentable(self):
        combination = COMBINATIONS[PlacementState.BOOSTED_HANDHELD]
        self.assertIs(combination.support, RouteSupport.UNREPRESENTABLE)
        self.assertEqual(combination.launch_config_target, "")
        with self.assertRaises(ValueError):
            # There is no launch target that renders on the eGPU and scans out
            # to the internal panel, so the config cannot express it.
            GamescopeLaunchConfig(
                boot_id_sha256="a" * 64,
                target="portable",
                internal_connector="eDP-1",
                vendor_device="1002:7480",
            )

    def test_external_display_combinations_require_an_attached_egpu(self):
        for placement in (PlacementState.DOCKED_IGPU, PlacementState.DOCKED_EGPU):
            self.assertTrue(COMBINATIONS[placement].requires_attached_egpu)


class PlannerAgreementTests(unittest.TestCase):
    """Guard against this table drifting away from the real planner."""

    def plan(self, *, current, target):
        return plan_manual_transition(
            plan_id="plan-1",
            request_id="request-1",
            current=current,
            target=target,
            capabilities=verified_capabilities(),
            evidence=evidence(),
        )

    def test_planner_target_flag_matches_planner_refusal(self):
        for target in PLACEMENTS:
            described = COMBINATIONS[target].planner_target
            decision = self.plan(current=PlacementState.PORTABLE, target=target)
            refused = "placement.target_unsupported" in decision.blockers
            self.assertEqual(described, not refused, target)

    def test_classifier_reports_the_planner_target_refusal(self):
        change = classify_change(
            current=PlacementState.DOCKED_EGPU,
            target=PlacementState.DOCKED_IGPU,
        )
        self.assertIn("placement.target_unsupported", change.refusals)
        decision = self.plan(
            current=PlacementState.DOCKED_EGPU, target=PlacementState.DOCKED_IGPU
        )
        self.assertIsNone(decision.plan)
        self.assertIn("placement.target_unsupported", decision.blockers)

    def test_running_game_refusal_uses_the_planner_vocabulary(self):
        change = classify_change(
            current=PlacementState.PORTABLE,
            target=PlacementState.DOCKED_EGPU,
            game_state=GameState.RUNNING,
        )
        decision = self.plan(
            current=PlacementState.PORTABLE, target=PlacementState.DOCKED_EGPU
        )
        self.assertEqual(change.refusals, ("game.running",))
        self.assertIsNone(
            plan_manual_transition(
                plan_id="plan-1",
                request_id="request-1",
                current=PlacementState.PORTABLE,
                target=PlacementState.DOCKED_EGPU,
                capabilities=verified_capabilities(),
                evidence=evidence(game_state=GameState.RUNNING),
            ).plan
        )
        self.assertIsNotNone(decision.plan)

    def test_certified_profile_pair_keeps_display_handoff_experimental(self):
        composed = compose_capabilities(ALLY_X, GPD_G1)
        self.assertIs(composed.display_handoff, CapabilitySupport.EXPERIMENTAL)


class ChangeClassificationTests(unittest.TestCase):
    def test_no_op_needs_no_restart_and_no_game_close(self):
        change = classify_change(
            current=PlacementState.DOCKED_EGPU,
            target=PlacementState.DOCKED_EGPU,
            game_state=GameState.RUNNING,
        )
        self.assertTrue(change.is_no_op)
        self.assertFalse(change.gamescope_restart_required)
        self.assertFalse(change.game_close_required)
        self.assertEqual(change.refusals, ())

    def test_portable_to_docked_igpu_is_display_only_but_still_closes_the_game(self):
        change = classify_change(
            current=PlacementState.PORTABLE, target=PlacementState.DOCKED_IGPU
        )
        self.assertTrue(change.is_display_only)
        self.assertFalse(change.render_gpu_changes)
        self.assertTrue(change.gamescope_restart_required)
        self.assertTrue(change.game_close_required)
        self.assertFalse(change.relaunch_lands_on_a_different_gpu)

    def test_docked_egpu_to_boosted_handheld_is_display_only(self):
        change = classify_change(
            current=PlacementState.DOCKED_EGPU,
            target=PlacementState.BOOSTED_HANDHELD,
        )
        self.assertTrue(change.is_display_only)
        self.assertTrue(change.game_close_required)

    def test_docked_egpu_to_docked_igpu_changes_the_renderer(self):
        change = classify_change(
            current=PlacementState.DOCKED_EGPU, target=PlacementState.DOCKED_IGPU
        )
        self.assertFalse(change.display_changes)
        self.assertTrue(change.is_render_handoff)
        self.assertTrue(change.relaunch_lands_on_a_different_gpu)

    def test_portable_to_docked_egpu_changes_both_axes(self):
        change = classify_change(
            current=PlacementState.PORTABLE, target=PlacementState.DOCKED_EGPU
        )
        self.assertTrue(change.display_changes)
        self.assertTrue(change.render_gpu_changes)
        self.assertFalse(change.is_display_only)
        self.assertTrue(change.relaunch_lands_on_a_different_gpu)

    def test_every_real_change_requires_a_game_close(self):
        for current in PLACEMENTS:
            for target in PLACEMENTS:
                change = classify_change(current=current, target=target)
                self.assertEqual(
                    change.game_close_required,
                    current is not target,
                    (current, target),
                )
                self.assertEqual(
                    change.game_close_required,
                    change.gamescope_restart_required,
                    (current, target),
                )

    def test_unknown_and_degraded_sources_fail_closed(self):
        for current in (PlacementState.UNKNOWN, PlacementState.DEGRADED):
            change = classify_change(
                current=current, target=PlacementState.DOCKED_EGPU
            )
            self.assertIn("placement.current_unverified", change.refusals)
            self.assertFalse(change.gamescope_restart_required)
            self.assertFalse(change.display_changes)
            self.assertFalse(change.render_gpu_changes)

    def test_unknown_target_fails_closed(self):
        change = classify_change(
            current=PlacementState.PORTABLE, target=PlacementState.UNKNOWN
        )
        self.assertIn("placement.target_unsupported", change.refusals)
        self.assertFalse(change.gamescope_restart_required)

    def test_omitted_game_state_adds_no_game_refusal(self):
        change = classify_change(
            current=PlacementState.PORTABLE, target=PlacementState.DOCKED_EGPU
        )
        self.assertEqual(change.refusals, ())
        self.assertTrue(change.game_close_required)

    def test_unknown_game_state_fails_closed(self):
        change = classify_change(
            current=PlacementState.PORTABLE,
            target=PlacementState.DOCKED_EGPU,
            game_state=GameState.UNKNOWN,
        )
        self.assertIn("game.state_unknown", change.refusals)


if __name__ == "__main__":
    unittest.main()
