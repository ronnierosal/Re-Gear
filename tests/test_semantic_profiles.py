from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

import game_profile_engine_fixtures as fx  # noqa: E402
from regear.domain.graphics_profiles import ManagedKey, SupportTier, ValueKind  # noqa: E402
from regear.domain.mode_profiles import ExperienceTarget  # noqa: E402
from regear.domain.models import OperatingMode  # noqa: E402
from regear.domain.semantic_profiles import (  # noqa: E402
    GraphicsSetting,
    ProfileMetadata,
    Quality,
    QualityKey,
    Resolution,
    SemanticProfile,
    UpscalingMode,
    ValidationStatus,
    decide_support,
    translate,
)

PORTABLE, BALANCED = OperatingMode.PORTABLE, ExperienceTarget.BALANCED


class TranslationTests(unittest.TestCase):
    def test_semantic_settings_become_game_keys(self):
        result = translate(fx.PORTABLE_BALANCED, fx.mapping())
        self.assertTrue(result.complete)
        self.assertEqual(result.settings[fx.TEXTURE], "2")
        self.assertEqual(result.settings[fx.SCALE], "67")

    def test_an_unmapped_setting_is_named(self):
        result = translate(fx.PORTABLE_QUALITY, fx.mapping())
        self.assertEqual(result.unmapped, ("volumetrics=high",))

    def test_auto_upscaling_is_never_expressible(self):
        profile = dataclasses.replace(fx.TV_BALANCED, upscaling=UpscalingMode.AUTO)
        self.assertIn("upscaling=auto", translate(profile, fx.mapping()).unmapped)

    def test_an_out_of_range_resolution_is_unmapped_not_clamped(self):
        profile = dataclasses.replace(fx.TV_BALANCED, resolution=Resolution(9000, 9000))
        self.assertIn("resolution=9000x9000", translate(profile, fx.mapping()).unmapped)

    def test_translation_is_deterministic(self):
        first = translate(fx.PORTABLE_BALANCED, fx.mapping())
        for _ in range(5):
            self.assertEqual(translate(fx.PORTABLE_BALANCED, fx.mapping()), first)


class RecommendationTests(unittest.TestCase):
    def test_recommendations_read_like_an_advisor_screen(self):
        self.assertEqual(
            fx.PORTABLE_BALANCED.recommendations(),
            ("Target 45 FPS", "Resolution 1280x800", "Textures High", "Shadows Medium",
             "Effects Medium", "View distance Medium", "Upscaling Quality", "Frame limit 45 FPS"),
        )


class MappingValidationTests(unittest.TestCase):
    def test_a_mapped_value_must_fit_its_key(self):
        key = ManagedKey("S", "k", ValueKind.INTEGER, minimum=0, maximum=3)
        with self.assertRaises(ValueError):
            QualityKey(key, {Quality.HIGH: "9"})

    def test_auto_cannot_be_mapped(self):
        with self.assertRaises(ValueError):
            dataclasses.replace(fx.mapping(), upscaling_values={UpscalingMode.AUTO: "100"})

    def test_profiles_reject_nonsense(self):
        with self.assertRaises(ValueError):
            SemanticProfile(target_fps=0)
        with self.assertRaises(ValueError):
            Resolution(0, 1080)
        with self.assertRaises(ValueError):
            SemanticProfile(graphics={"textures": "high"})

    def test_metadata_must_name_a_tested_version(self):
        with self.assertRaises(ValueError):
            ProfileMetadata(1, 1, "", ValidationStatus.FIXTURE)


class SupportLevelTests(unittest.TestCase):
    def decide(self, **kwargs):
        values = dict(document=fx.document(), mapping=fx.mapping(), mode=PORTABLE,
                      preference=BALANCED, observed_game_version=fx.GAME_BUILD,
                      allow_fixture_profiles=True)
        values.update(kwargs)
        return decide_support(**values)

    def test_level_0_without_a_document(self):
        self.assertIs(self.decide(document=None).tier, SupportTier.UNKNOWN)

    def test_level_1_without_a_mapping_still_recommends(self):
        decision = self.decide(mapping=None)
        self.assertIs(decision.tier, SupportTier.ADVISOR)
        self.assertIn("Textures High", decision.recommendations)
        self.assertIsNone(decision.graphics_profile)

    def test_level_2_carries_a_foundation_profile(self):
        decision = self.decide()
        self.assertTrue(decision.managed)
        self.assertEqual(decision.graphics_profile.schema_id, fx.mapping().schema_id)
        self.assertEqual(decision.graphics_profile.profile_version, 1)

    def test_every_reason_is_reported_not_just_the_first(self):
        decision = self.decide(mapping=fx.mapping(adapter_version=2), observed_game_version="old",
                               allow_fixture_profiles=False)
        self.assertIs(decision.tier, SupportTier.ADVISOR)
        self.assertEqual(len(decision.reasons), 3)


if __name__ == "__main__":
    unittest.main()
