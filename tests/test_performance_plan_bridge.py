"""Hardware-free contract tests: target -> resolver -> engine preview + launch."""
from __future__ import annotations

import dataclasses
import unittest

import performance_fixtures as fx
from regear.application.performance_launch_plan import OriginalLaunch
from regear.application.performance_plan_bridge import preview_performance
from regear.domain.frame_generation_provider import LsfgVkProvider, ProviderConfiguration
from regear.domain.models import GameState, OperatingMode
from regear.domain.performance_target_resolver import (
    EvidenceStatus, InjectionEligibility, Outcome, PerformanceIntent, ProviderKind,
    ProviderState, ScalingLocation, UpscalingChoice, VrrState,
)
from regear.domain.semantic_profiles import Resolution, SemanticProfile, UpscalingMode


ORIGINAL = OriginalLaunch(' wrapper "quoted value" %command% --dx12 ', {"PLAYER": "untouched"})


def preview(records=None, **overrides):
    values = dict(
        intent=PerformanceIntent(60), context=fx.context(), game_state=GameState.IDLE,
        adapter=fx.adapter(), records=tuple(records if records is not None else
                                          (fx.native(), fx.frame_generation())),
        states=fx.providers(), original=ORIGINAL,
        providers={fx.LSFG_VK_PROVIDER_ID: LsfgVkProvider(fx.FIXTURE_DLL)},
        game_upscaler_bindings={fx.binding(fx.ExperienceTarget.BALANCED): "fixture-fsr"},
    )
    values.update(overrides)
    return preview_performance(**values)


class BrokenProvider:
    provider_id = fx.LSFG_VK_PROVIDER_ID
    revision = fx.LSFG_VK_REVISION

    def plan(self, decision, environment):
        raise RuntimeError("simulated preparation/initialization failure before launch")


class BridgeTests(unittest.TestCase):
    def test_native_target_no_frame_generation(self):
        result = preview([fx.native(fps=60)])
        self.assertEqual(result.game_plan.base_fps_target, 60)
        self.assertIsNone(result.game_plan.frame_generation)
        self.assertFalse(result.launch.changes_anything)

    def test_upscaling_reaches_target_without_fg(self):
        result = preview([fx.native(fps=48), fx.upscaled()])
        self.assertIs(result.game_plan.upscaling, UpscalingMode.QUALITY)
        self.assertIsNone(result.game_plan.frame_generation)

    def test_frame_generation_composes_base_cap_into_existing_engine_contract(self):
        result = preview()
        plan = result.game_plan
        self.assertEqual((plan.base_fps_target, plan.target_display_fps), (30, 60))
        semantic = plan.apply_to(SemanticProfile(frame_limit=60, upscaling=UpscalingMode.AUTO))
        self.assertEqual((semantic.frame_limit, semantic.target_fps), (30, 60))
        self.assertEqual(result.launch.environment_overlay["LSFGVK_MULTIPLIER"], "2")
        self.assertFalse(result.execution_allowed)

    def test_insufficient_base_does_not_become_generated_60(self):
        result = preview([fx.native(fps=30), fx.frame_generation(base=15, multiplier=4,
                                                                  minimum_base_fps=30)])
        self.assertEqual(result.game_plan.target_display_fps, 30)
        self.assertIsNone(result.game_plan.frame_generation)

    def test_unstable_base_is_rejected(self):
        self.assertIsNone(preview([fx.frame_generation(stable=False)]).game_plan)

    def test_latency_artifact_failure_rejected(self):
        self.assertIsNone(preview([fx.frame_generation(quality_acceptable=False)]).game_plan)

    def test_provider_unavailable(self):
        result = preview(states=fx.providers(available=False))
        self.assertEqual(result.game_plan.target_display_fps, 30)

    def test_provider_unsupported_experimental_and_theoretical(self):
        for status in (EvidenceStatus.UNSUPPORTED, EvidenceStatus.EXPERIMENTAL,
                       EvidenceStatus.THEORETICAL):
            with self.subTest(status=status):
                self.assertIsNone(preview([fx.frame_generation(status=status)]).game_plan)

    def test_validated_provider_selects_only_inert_plan(self):
        self.assertEqual(preview().game_plan.frame_generation.provider_id, "lsfg-vk")
        self.assertFalse(preview().launch.execution_allowed)

    def test_refresh_below_requested_target_caps_native_and_reports_shortfall(self):
        result = preview([fx.native(fps=60, refresh_hz=45)], context=fx.context(refresh_hz=45))
        self.assertEqual(result.game_plan.target_display_fps, 45)
        self.assertEqual(result.game_plan.base_fps_target, 45)
        self.assertIs(result.decision.outcome, Outcome.LOWER_TARGET)

    def test_refresh_shortfall_respects_no_lower_target_policy(self):
        result = preview([fx.native(fps=60, refresh_hz=45)], context=fx.context(refresh_hz=45),
                         intent=PerformanceIntent(60, allow_lower_target=False))
        self.assertIsNone(result.game_plan)

    def test_4k_output_does_not_force_4k_rendering(self):
        result = preview()
        self.assertEqual(result.output_resolution, Resolution(3840, 2160))
        self.assertEqual(result.game_plan.resolution, Resolution(1920, 1080))

    def test_portable_900p_is_declared_not_inferred_from_display(self):
        result = preview([fx.native(fps=45, mode=OperatingMode.PORTABLE,
                                    render_resolution=Resolution(1600, 900))],
                         context=fx.context(mode=OperatingMode.PORTABLE),
                         intent=PerformanceIntent(45))
        self.assertEqual(result.game_plan.resolution, Resolution(1600, 900))

    def test_boosted_handheld_internal_output_independent_of_render_gpu(self):
        result = preview([fx.native(fps=60, mode=OperatingMode.BOOSTED_HANDHELD,
                                    display_owner="internal")],
                         context=fx.context(mode=OperatingMode.BOOSTED_HANDHELD,
                                            display_owner="internal"))
        self.assertIsNotNone(result.game_plan)

    def test_native_fg_priority_is_configurable_and_not_subject_to_injection_policy(self):
        native = fx.frame_generation("native-fg", provider_id="native", provider_revision="1",
                                     provider_kind=ProviderKind.NATIVE_GAME,
                                     injection=InjectionEligibility.UNKNOWN)
        states = fx.providers()
        states["native"] = ProviderState("native", "1", True, supported_multipliers=(2,),
                                         kind=ProviderKind.NATIVE_GAME,
                                         requires_refresh_match=False)
        for first in ("native", "lsfg-vk"):
            result = preview([native, fx.frame_generation()], states=states,
                             intent=PerformanceIntent(60, provider_priority=(first,)))
            self.assertEqual(result.game_plan.frame_generation.provider_id, first)
            if first == "native":
                self.assertFalse(result.launch.changes_anything)
                self.assertTrue(any("native_game_fg_mapping" in r for r in result.reasons))

    def test_native_fg_can_use_validated_pacing_below_refresh(self):
        record = fx.frame_generation(provider_id="native", provider_revision="1", refresh_hz=120,
                                     provider_kind=ProviderKind.NATIVE_GAME)
        states = {"native": ProviderState("native", "1", True, supported_multipliers=(2,),
                                          kind=ProviderKind.NATIVE_GAME,
                                          requires_refresh_match=False)}
        self.assertIsNotNone(preview([record], context=fx.context(refresh_hz=120),
                                     states=states).game_plan)

    def test_no_compatible_fg_provider_returns_original(self):
        result = preview([fx.frame_generation()], states={})
        self.assertIsNone(result.game_plan)
        self.assertEqual(result.launch.original, ORIGINAL)

    def test_mode_change_during_game_queues_intent_not_stale_plan(self):
        for state in (GameState.RUNNING, GameState.UNKNOWN):
            result = preview(game_state=state, context=fx.context(mode=OperatingMode.PORTABLE))
            self.assertTrue(result.decision.next_launch)
            self.assertIsNone(result.game_plan)
            self.assertFalse(result.launch.changes_anything)

    def test_provider_preparation_failure_discards_game_cap_too(self):
        result = preview(providers={fx.LSFG_VK_PROVIDER_ID: BrokenProvider()})
        self.assertIsNone(result.game_plan)
        self.assertEqual(result.launch.proposed_environment, ORIGINAL.environment)
        self.assertEqual(result.launch.launch_options, ORIGINAL.launch_options)

    def test_unknown_game_ff7_is_advisor_not_support_claim(self):
        result = preview(context=fx.context(steam_app_id=fx.FF7_REMAKE_APP_ID))
        self.assertIsNone(result.game_plan)
        self.assertIs(result.decision.outcome, Outcome.ADVISOR)

    def test_conflicting_scaling_technologies_are_not_combined(self):
        record = fx.upscaled(upscalers=(UpscalingChoice("fsr", UpscalingMode.QUALITY),
                                       UpscalingChoice("nis", UpscalingMode.QUALITY,
                                                       ScalingLocation.COMPOSITOR)))
        self.assertIsNone(preview([record]).game_plan)

    def test_unimplemented_compositor_seam_keeps_original_settings(self):
        record = fx.upscaled(upscalers=(UpscalingChoice("gamescope", UpscalingMode.QUALITY,
                                                       ScalingLocation.COMPOSITOR),))
        self.assertIsNone(preview([record]).game_plan)

    def test_upscaler_identity_cannot_be_lost_in_engine_quality_mode(self):
        self.assertIsNone(preview([fx.upscaled()], game_upscaler_bindings={}).game_plan)
        for provider_id in ("fsr", "dlss", "xess"):
            record = fx.upscaled(upscalers=(UpscalingChoice(provider_id, UpscalingMode.QUALITY),))
            self.assertIsNone(preview([record]).game_plan)

    def test_disable_removes_both_provider_and_game_proposals(self):
        result = preview().disable()
        self.assertIsNone(result.game_plan)
        self.assertEqual(result.launch.proposed_environment, ORIGINAL.environment)
        self.assertEqual(result.launch.launch_options, ORIGINAL.launch_options)

    def test_provider_state_identity_mismatch_rejected(self):
        self.assertIsNone(preview([fx.frame_generation()],
                                  states=fx.providers(provider_id="wrong")).game_plan)

    def test_bad_provider_configuration_identity_rejected(self):
        class Wrong(BrokenProvider):
            def plan(self, decision, environment):
                return ProviderConfiguration("wrong", "wrong", {"WRONG": "1"})
        self.assertIsNone(preview(providers={fx.LSFG_VK_PROVIDER_ID: Wrong()}).game_plan)

    def test_provider_cannot_erase_unresolved_decision_requirements(self):
        class OmitsRequirements(BrokenProvider):
            def plan(self, decision, environment):
                return ProviderConfiguration(self.provider_id, self.revision, {"FIXTURE": "1"})
        result = preview(providers={fx.LSFG_VK_PROVIDER_ID: OmitsRequirements()})
        self.assertTrue(any("base_limiter" in r for r in result.launch.unresolved))

    def test_vrr_evidence_applies_to_native_too(self):
        self.assertIsNone(preview([fx.native(fps=60, requires_vrr=VrrState.ON)]).game_plan)

    def test_output_display_stack_and_capability_changes_invalidate_evidence(self):
        changes = (
            {"output_resolution": Resolution(1920, 1080)},
            {"display_owner": "another-display"},
            {"presentation_stack": "new-mangohud-order"},
        )
        for change in changes:
            with self.subTest(change=change):
                self.assertIsNone(preview([fx.native(fps=60)],
                                          context=fx.context(**change)).game_plan)
        self.assertIsNone(preview([fx.native(fps=60,
                                            required_capabilities=frozenset({"missing"}))]).game_plan)

    def test_any_player_lsfg_tuning_is_preserved(self):
        original = OriginalLaunch("%command%", {"LSFGVK_FLOW_SCALE": "0.5"})
        self.assertIsNone(preview(original=original).game_plan)

    def test_headroom_is_not_mistaken_for_selected_base_cap(self):
        result = preview([fx.native(fps=90)])
        self.assertEqual(result.game_plan.base_fps_target, 60)

    def test_boolean_multiplier_cannot_become_a_frame_rate(self):
        with self.assertRaises(ValueError):
            fx.native(multiplier=True)

    def test_engine_translation_receives_base30_and_1080p_not_output4k(self):
        import game_profile_engine_fixtures as engine_fx
        from regear.domain.semantic_profiles import translate
        result = preview()
        translated = translate(result.game_plan.apply_to(engine_fx.TV_BALANCED), engine_fx.mapping())
        self.assertTrue(translated.complete)
        self.assertEqual(translated.settings[engine_fx.FRAME_LIMIT], "30")
        self.assertEqual(translated.settings[engine_fx.WIDTH], "1920")
        self.assertEqual(translated.settings[engine_fx.HEIGHT], "1080")

    def test_duplicate_evidence_is_ambiguous_not_input_order_dependent(self):
        a, b = fx.native(fps=60), fx.native(fps=45)
        for records in ([a, b], [b, a]):
            self.assertIsNone(preview(records).game_plan)

    def test_selected_native_cap_respects_player_floor(self):
        self.assertIsNone(preview([fx.native(fps=90)],
                                  intent=PerformanceIntent(60, minimum_base_fps=75)).game_plan)

    def test_vrr_range_does_not_imply_unmeasured_low_framerate_compensation(self):
        result = preview([fx.native(fps=30, requires_vrr=VrrState.ON)],
                         context=fx.context(vrr=VrrState.ON, vrr_range=(48, 60)),
                         intent=PerformanceIntent(30))
        self.assertIsNone(result.game_plan)

    def test_preview_cannot_be_promoted_to_execution(self):
        with self.assertRaises(ValueError):
            dataclasses.replace(preview(), execution_allowed=True)


if __name__ == "__main__":
    unittest.main()
