"""PerformancePlan v2: frame rates, three resolution domains, v1 migration. Pure."""

from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

import game_profile_engine_fixtures as fx  # noqa: E402
from regear.domain.performance_plan import (  # noqa: E402
    PLAN_VERSION,
    FrameGenerationRef,
    PerformancePlan,
)
from regear.domain.semantic_profiles import (  # noqa: E402
    InternalRender,
    Resolution,
    UpscalingMode,
)

FG2 = FrameGenerationRef("fixture-provider", 2)
P1080, P4K, P720 = Resolution(1920, 1080), Resolution(3840, 2160), Resolution(1280, 720)


def plan(**changes):
    values = dict(requested_display_fps=60, target_display_fps=60, base_fps_target=60)
    values.update(changes)
    return PerformancePlan(**values)


class FrameRateTests(unittest.TestCase):
    def test_request_90_served_by_validated_30x2_keeps_both_rates(self):
        fallback = plan(requested_display_fps=90, target_display_fps=60, base_fps_target=30,
                        frame_generation=FG2)
        self.assertTrue(fallback.is_fallback)
        self.assertEqual(fallback.requested_display_fps, 90)
        self.assertEqual(fallback.target_display_fps, 60)
        self.assertEqual(fallback.generated_fps, 30)
        self.assertEqual(fallback.explain()[:2],
                         ("Requested 90 FPS; planned 60 FPS", "30 rendered, 30 generated (x2)"))

    def test_selected_rate_never_exceeds_the_request(self):
        with self.assertRaisesRegex(ValueError, "more than the player requested"):
            plan(requested_display_fps=45, target_display_fps=60, base_fps_target=30,
                 frame_generation=FG2)

    def test_rendered_times_multiplier_must_equal_the_selected_rate(self):
        self.assertEqual(plan(base_fps_target=30, frame_generation=FG2).generated_fps, 30)
        for bad in (dict(base_fps_target=30),
                    dict(base_fps_target=25, frame_generation=FG2),
                    dict(base_fps_target=20, frame_generation=FrameGenerationRef("x", 2))):
            with self.subTest(bad), self.assertRaises(ValueError):
                plan(**bad)

    def test_native_plan_generates_nothing_and_is_not_a_fallback(self):
        native = plan()
        self.assertEqual(native.generated_fps, 0)
        self.assertFalse(native.is_fallback)
        self.assertEqual(native.explain(), ("Planned 60 FPS",))

    def test_rates_are_validated(self):
        for bad in (dict(requested_display_fps=0), dict(target_display_fps=True),
                    dict(base_fps_target=5000)):
            with self.subTest(bad), self.assertRaises(ValueError):
                plan(**bad)


class ResolutionDomainTests(unittest.TestCase):
    def test_game_output_1080p_on_a_4k_display_keeps_both(self):
        tv = plan(game_output_resolution=P1080, display_output_resolution=P4K)
        self.assertEqual(tv.game_output_resolution, P1080)
        self.assertEqual(tv.display_output_resolution, P4K)
        self.assertIs(tv.internal_render, InternalRender.UNKNOWN)
        self.assertIn("Display 3840x2160", tv.explain())
        self.assertIn("Game output 1920x1080", tv.explain())

    def test_internal_render_may_be_explicit_dynamic_or_unknown(self):
        self.assertEqual(plan(internal_render=P720).internal_render, P720)
        self.assertIn("Internal render dynamic",
                      plan(internal_render=InternalRender.DYNAMIC).explain())
        self.assertIs(plan().internal_render, InternalRender.UNKNOWN)

    def test_supersampling_is_not_refused_by_the_contract(self):
        # Internal above output is legitimate; any limit is the game mapping's.
        supersampled = plan(game_output_resolution=P1080, internal_render=P4K)
        self.assertEqual(supersampled.internal_render, P4K)

    def test_wrong_types_are_refused(self):
        for bad in (dict(internal_render=None), dict(internal_render="dynamic-ish"),
                    dict(game_output_resolution=(1920, 1080)),
                    dict(display_output_resolution="4k"),
                    dict(upscaling=UpscalingMode.AUTO)):
            with self.subTest(bad), self.assertRaises(ValueError):
                plan(**bad)


class VersionTests(unittest.TestCase):
    def test_constructor_is_version_2_only(self):
        self.assertEqual(PLAN_VERSION, 2)
        with self.assertRaisesRegex(ValueError, "from_v1"):
            plan(plan_version=1)
        with self.assertRaises(ValueError):
            plan(plan_version=3)

    def test_v1_resolution_is_game_output_and_internal_stays_unknown(self):
        for upscaling in (None, UpscalingMode.OFF, UpscalingMode.QUALITY):
            with self.subTest(upscaling):
                migrated = PerformancePlan.from_v1(60, 30, P1080, upscaling, FG2, "old")
                self.assertEqual(migrated.game_output_resolution, P1080)
                # Never inferred: not from "no upscaling", not from output size.
                self.assertIs(migrated.internal_render, InternalRender.UNKNOWN)
                self.assertIsNone(migrated.display_output_resolution)
                self.assertEqual(migrated.upscaling, upscaling)
                self.assertEqual(migrated.frame_generation, FG2)
                self.assertEqual(migrated.plan_version, 2)

    def test_v1_request_is_not_recorded_rather_than_guessed(self):
        migrated = PerformancePlan.from_v1(40, 40)
        self.assertIsNone(migrated.requested_display_fps)
        self.assertFalse(migrated.is_fallback)

    def test_v1_invariants_still_hold_through_migration(self):
        with self.assertRaises(ValueError):
            PerformancePlan.from_v1(60, 30)
        with self.assertRaises(ValueError):
            PerformancePlan.from_v1(60, 60, upscaling=UpscalingMode.AUTO)


class ApplyToTests(unittest.TestCase):
    def test_plan_fields_lay_over_the_profile_and_display_does_not(self):
        profile = fx.TV_BALANCED
        laid = plan(requested_display_fps=90, target_display_fps=60, base_fps_target=30,
                    frame_generation=FG2, game_output_resolution=P1080,
                    display_output_resolution=P4K, internal_render=P720).apply_to(profile)
        self.assertEqual(laid.target_fps, 60)
        self.assertEqual(laid.frame_limit, 30)  # rendered, not presented
        self.assertEqual(laid.game_output_resolution, P1080)
        self.assertEqual(laid.internal_render, P720)
        self.assertEqual(laid.graphics, profile.graphics)
        self.assertFalse(any("3840" in line for line in laid.recommendations()))

    def test_unknown_internal_leaves_the_profile_own_statement(self):
        profile = dataclasses.replace(fx.TV_BALANCED, internal_render=P720)
        self.assertEqual(plan().apply_to(profile).internal_render, P720)
        self.assertIsNone(plan().apply_to(fx.TV_BALANCED).internal_render)

    def test_unset_plan_fields_keep_the_profile(self):
        laid = plan().apply_to(fx.PORTABLE_BALANCED)
        self.assertEqual(laid.game_output_resolution, fx.PORTABLE_BALANCED.game_output_resolution)
        self.assertEqual(laid.upscaling, fx.PORTABLE_BALANCED.upscaling)


if __name__ == "__main__":
    unittest.main()
