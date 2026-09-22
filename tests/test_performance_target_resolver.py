from __future__ import annotations

import dataclasses
import itertools
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

import performance_fixtures as fx  # noqa: E402
from regear.domain.mode_profiles import ExperienceTarget  # noqa: E402
from regear.domain.models import GameState, OperatingMode  # noqa: E402
from regear.domain.performance_target_resolver import (  # noqa: E402
    EvidenceStatus,
    FrameGenerationPolicy,
    InjectionEligibility,
    Outcome,
    PerformanceIntent,
    RenderMethod,
    VrrState,
    resolve,
)


def run(records, intent=None, context=None, state=GameState.IDLE, providers=None, adapter="default"):
    return resolve(
        intent or PerformanceIntent(60),
        context or fx.context(),
        state,
        fx.adapter() if adapter == "default" else adapter,
        tuple(records),
        fx.providers() if providers is None else providers,
    )


def reasons_for(decision, record_id):
    return [reason for rid, reason in decision.rejected if rid == record_id]


class PrecedenceTests(unittest.TestCase):
    def test_native_beats_upscaled_and_frame_generation_when_all_reach_the_target(self):
        decision = run(
            [fx.frame_generation(), fx.upscaled(), fx.native("native-quality", 60)]
        )
        self.assertIs(decision.outcome, Outcome.NATIVE)
        self.assertEqual(decision.record.record_id, "native-quality")

    def test_upscaled_beats_frame_generation(self):
        decision = run([fx.frame_generation(), fx.upscaled(), fx.native()])
        self.assertIs(decision.outcome, Outcome.UPSCALED)
        self.assertEqual(decision.record.record_id, "upscaled-balanced")

    def test_frame_generation_is_chosen_only_when_nothing_simpler_reaches(self):
        decision = run([fx.native(), fx.frame_generation()])
        self.assertIs(decision.outcome, Outcome.FRAME_GENERATION)
        self.assertEqual(decision.required_stable_base_fps, 30)
        self.assertEqual(decision.multiplier, 2)
        self.assertEqual(decision.achievable_fps, 60)

    def test_the_decision_composes_with_the_existing_adapter_profile(self):
        decision = run([fx.native(), fx.frame_generation()])
        self.assertIsNotNone(decision.profile)
        self.assertEqual(decision.profile.steam_app_id, fx.FIXTURE_APP_ID)
        self.assertIs(decision.profile.mode, OperatingMode.TV_DOCKED)
        self.assertEqual(decision.profile.schema_id, "ue-gameusersettings")

    def test_selection_is_independent_of_record_order(self):
        records = [fx.native(), fx.frame_generation(), fx.upscaled("upscaled-a", 45),
                   fx.native("native-b", 40)]
        first = run(records)
        for order in itertools.permutations(records):
            with self.subTest(order=[r.record_id for r in order]):
                decision = run(order)
                self.assertEqual(decision, first)

    def test_equal_candidates_break_ties_by_record_id(self):
        decision = run([fx.native("native-z", 60), fx.native("native-a", 60)])
        self.assertEqual(decision.record.record_id, "native-a")


class NoInventedNumbersTests(unittest.TestCase):
    def test_no_evidence_means_advisor_and_no_default_base_rate(self):
        decision = run([])
        self.assertIs(decision.outcome, Outcome.ADVISOR)
        self.assertIsNone(decision.required_stable_base_fps)
        self.assertIsNone(decision.achievable_fps)

    def test_the_future_validation_candidate_is_not_supported_without_evidence(self):
        # Final Fantasy VII Remake Intergrade is the first future supervised
        # candidate. With no adapter and no evidence it gets no automatic change.
        decision = run([], context=fx.context(steam_app_id=fx.FF7_REMAKE_APP_ID))
        self.assertIs(decision.outcome, Outcome.ADVISOR)
        self.assertIsNone(decision.record)

    def test_intent_rejects_nonsense_rates(self):
        for value in (0, -30, 5000, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                PerformanceIntent(value)


class BaseRateTests(unittest.TestCase):
    def test_a_base_below_the_players_floor_is_rejected(self):
        decision = run([fx.native(), fx.frame_generation()], PerformanceIntent(60, minimum_base_fps=40))
        self.assertIsNot(decision.outcome, Outcome.FRAME_GENERATION)
        self.assertTrue(any("below the floor" in r for r in reasons_for(decision, "fg-quality-2x")))

    def test_a_base_below_the_evidence_floor_is_rejected(self):
        decision = run([fx.native(), fx.frame_generation(minimum_base_fps=45)])
        self.assertIsNot(decision.outcome, Outcome.FRAME_GENERATION)

    def test_near_target_native_does_not_hand_over_without_a_declared_comparison(self):
        # 55 native falls short of 60. FG was never compared against it, so the
        # simpler option is kept and the shortfall stated -- a transient dip is
        # not a reason to switch to generated frames.
        decision = run(
            [fx.native("native-quality", 55),
             fx.frame_generation(compared_against=("some-other-record",))]
        )
        self.assertIs(decision.outcome, Outcome.LOWER_TARGET)
        self.assertEqual(decision.achievable_fps, 55)
        self.assertTrue(any("declared comparison" in r for r in reasons_for(decision, "fg-quality-2x")))

    def test_a_declared_comparison_admits_frame_generation(self):
        decision = run([fx.native("native-quality", 55), fx.frame_generation()])
        self.assertIs(decision.outcome, Outcome.FRAME_GENERATION)

    def test_frame_generation_output_must_equal_the_target(self):
        # 30 x 3 = 90 on a 90 Hz display passes every other gate, so the only
        # remaining reason is that 90 is not the 60 that was asked for.
        decision = run([fx.frame_generation("fg-3x", base=30, multiplier=3,
                                            refresh_hz=90, compared_against=())],
                       context=fx.context(refresh_hz=90),
                       providers=fx.providers(supported_multipliers=(2, 3)))
        self.assertIs(decision.outcome, Outcome.ADVISOR)
        self.assertIn("frame-generation output does not equal the target",
                      reasons_for(decision, "fg-3x"))


class StaleEvidenceTests(unittest.TestCase):
    def assert_rejected(self, record, fragment, context=None):
        decision = run([record], context=context)
        self.assertIs(decision.outcome, Outcome.ADVISOR)
        self.assertTrue(any(fragment in r for r in reasons_for(decision, record.record_id)),
                        decision.rejected)

    def test_another_game_build(self):
        self.assert_rejected(fx.native(fps=60, game_build="fixture-build-0"), "another game build")

    def test_another_runtime_or_driver(self):
        self.assert_rejected(fx.native(fps=60, runtime="other-proton"), "another runtime")

    def test_another_rendering_gpu(self):
        self.assert_rejected(fx.native(fps=60, render_gpu="other-gpu"), "another rendering GPU")

    def test_another_placement(self):
        self.assert_rejected(fx.native(fps=60, mode=OperatingMode.PORTABLE), "another placement")

    def test_another_refresh_rate(self):
        self.assert_rejected(fx.native(fps=60, refresh_hz=120), "another refresh rate")

    def test_another_profile_version(self):
        stale = dataclasses.replace(fx.binding(), profile_version=2)
        self.assert_rejected(fx.native(fps=60, profile=stale), "another profile or schema")

    def test_another_schema(self):
        stale = dataclasses.replace(fx.binding(), schema_id="other-schema")
        self.assert_rejected(fx.native(fps=60, profile=stale), "another profile or schema")

    def test_another_adapter(self):
        stale = dataclasses.replace(fx.binding(), adapter_id="other-adapter")
        self.assert_rejected(fx.native(fps=60, profile=stale), "another game adapter")

    def test_a_profile_the_adapter_does_not_declare(self):
        missing = dataclasses.replace(fx.binding(), target=ExperienceTarget.BATTERY)
        self.assert_rejected(fx.native(fps=60, profile=missing), "declares no battery profile")

    def test_another_provider_revision(self):
        decision = run([fx.native(), fx.frame_generation(provider_revision="0" * 40)])
        self.assertIsNot(decision.outcome, Outcome.FRAME_GENERATION)
        self.assertTrue(any("another provider revision" in r
                            for r in reasons_for(decision, "fg-quality-2x")))

    def test_an_unknown_record_version(self):
        self.assert_rejected(fx.native(fps=60, record_version=99), "record version")

    def test_evidence_for_another_game(self):
        self.assert_rejected(fx.native(fps=60, steam_app_id="4000000002"), "another game")


class StatusAndEligibilityTests(unittest.TestCase):
    def fg_rejected(self, fragment, **overrides):
        decision = run([fx.native(), fx.frame_generation(**overrides)])
        self.assertIsNot(decision.outcome, Outcome.FRAME_GENERATION)
        self.assertTrue(any(fragment in r for r in reasons_for(decision, "fg-quality-2x")),
                        decision.rejected)
        return decision

    def test_experimental_is_never_automatic(self):
        self.fg_rejected("experimental", status=EvidenceStatus.EXPERIMENTAL)

    def test_unsupported_is_rejected(self):
        self.fg_rejected("unsupported", status=EvidenceStatus.UNSUPPORTED)

    def test_unknown_status_is_rejected(self):
        self.fg_rejected("unknown", status=EvidenceStatus.UNKNOWN)

    def test_anti_cheat_unknown_is_not_permission(self):
        self.fg_rejected("anti-cheat", injection=InjectionEligibility.UNKNOWN)

    def test_ineligible_for_injection(self):
        self.fg_rejected("ineligible", injection=InjectionEligibility.INELIGIBLE)

    def test_unsupported_multiplier(self):
        decision = run([fx.native(), fx.frame_generation()],
                       providers=fx.providers(supported_multipliers=(3,)))
        self.assertIsNot(decision.outcome, Outcome.FRAME_GENERATION)

    def test_unavailable_provider(self):
        decision = run([fx.native(), fx.frame_generation()],
                       providers=fx.providers(available=False, reason="not installed"))
        self.assertTrue(any("not installed" in r for r in reasons_for(decision, "fg-quality-2x")))

    def test_player_turned_frame_generation_off(self):
        decision = run([fx.native(), fx.frame_generation()],
                       PerformanceIntent(60, fg_policy=FrameGenerationPolicy.OFF))
        self.assertIsNot(decision.outcome, Outcome.FRAME_GENERATION)


class PresentationTests(unittest.TestCase):
    def test_sixty_output_on_a_120hz_display_is_not_admitted(self):
        decision = run([fx.native(refresh_hz=None), fx.frame_generation(refresh_hz=None)],
                       context=fx.context(refresh_hz=120))
        self.assertIsNot(decision.outcome, Outcome.FRAME_GENERATION)
        self.assertTrue(any("refresh is not changed" in r
                            for r in reasons_for(decision, "fg-quality-2x")))

    def test_unknown_refresh_blocks_only_frame_generation(self):
        decision = run([fx.native("native-quality", 60, refresh_hz=None),
                        fx.frame_generation(refresh_hz=None)],
                       context=fx.context(refresh_hz=None))
        self.assertIs(decision.outcome, Outcome.NATIVE)

    def test_unknown_vrr_excludes_a_vrr_dependent_option(self):
        decision = run([fx.native(), fx.frame_generation()],
                       context=fx.context(vrr=VrrState.UNKNOWN))
        self.assertIsNot(decision.outcome, Outcome.FRAME_GENERATION)

    def test_unknown_vrr_does_not_block_a_proven_native_profile(self):
        decision = run([fx.native("native-quality", 60)],
                       context=fx.context(vrr=VrrState.UNKNOWN))
        self.assertIs(decision.outcome, Outcome.NATIVE)


class PlacementAndStateTests(unittest.TestCase):
    def test_all_three_known_placements_can_resolve(self):
        for mode in (OperatingMode.PORTABLE, OperatingMode.BOOSTED_HANDHELD,
                     OperatingMode.TV_DOCKED):
            with self.subTest(mode=mode):
                decision = run([fx.native("native-quality", 60, mode=mode)],
                               context=fx.context(mode=mode))
                self.assertIs(decision.outcome, Outcome.NATIVE)

    def test_unknown_and_degraded_select_no_automatic_change(self):
        for mode in (OperatingMode.UNKNOWN, OperatingMode.DEGRADED):
            with self.subTest(mode=mode):
                decision = run([fx.native("native-quality", 60, mode=mode)],
                               context=fx.context(mode=mode))
                self.assertIs(decision.outcome, Outcome.ADVISOR)
                self.assertIsNone(decision.record)

    def test_unidentified_rendering_gpu_selects_nothing(self):
        decision = run([fx.native("native-quality", 60)], context=fx.context(render_gpu=None))
        self.assertIs(decision.outcome, Outcome.ADVISOR)

    def test_a_running_game_defers_to_next_launch_without_a_plan(self):
        for state in (GameState.RUNNING, GameState.UNKNOWN):
            with self.subTest(state=state):
                decision = run([fx.native(), fx.frame_generation()], state=state)
                self.assertIs(decision.outcome, Outcome.DEFERRED)
                self.assertTrue(decision.next_launch)
                self.assertIsNone(decision.record)
                self.assertIsNone(decision.profile)

    def test_missing_adapter_is_advisor(self):
        decision = run([fx.native("native-quality", 60)], adapter=None)
        self.assertIs(decision.outcome, Outcome.ADVISOR)


class LowerTargetTests(unittest.TestCase):
    def test_the_highest_validated_lower_target_is_chosen(self):
        decision = run([fx.native("native-a", 40), fx.upscaled("upscaled-b", 50)])
        self.assertIs(decision.outcome, Outcome.LOWER_TARGET)
        self.assertEqual(decision.achievable_fps, 50)
        self.assertEqual(decision.requested_fps, 60)

    def test_lower_target_is_refused_when_the_player_did_not_allow_it(self):
        decision = run([fx.native("native-a", 40)],
                       PerformanceIntent(60, allow_lower_target=False))
        self.assertIs(decision.outcome, Outcome.ADVISOR)


class UnresolvedRequirementTests(unittest.TestCase):
    def test_an_unresolved_limiter_is_carried_not_hidden(self):
        decision = run([fx.native(), fx.frame_generation()])
        self.assertTrue(any(item.startswith("base_limiter") for item in decision.unresolved))

    def test_in_process_failure_recovery_is_always_an_open_gate(self):
        decision = run([fx.native(), fx.frame_generation()])
        self.assertTrue(any(item.startswith("provider_initialization_failure")
                            for item in decision.unresolved))

    def test_simpler_methods_carry_no_frame_generation_requirements(self):
        decision = run([fx.native("native-quality", 60)])
        self.assertEqual(decision.unresolved, ())


class RecordValidationTests(unittest.TestCase):
    def test_frame_generation_output_must_be_exact_base_times_multiplier(self):
        with self.assertRaises(ValueError):
            fx.frame_generation(output_fps=59)

    def test_frame_generation_needs_a_provider_revision(self):
        with self.assertRaises(ValueError):
            fx.frame_generation(provider_revision=None)

    def test_native_has_no_multiplier_or_provider(self):
        with self.assertRaises(ValueError):
            fx.native(multiplier=2)
        with self.assertRaises(ValueError):
            fx.native(provider_id="lsfg-vk")


if __name__ == "__main__":
    unittest.main()
