from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

from graphics_profile_fixtures import SAMPLE_CONFIG  # noqa: E402
from regear.domain.graphics_config_format import parse_document  # noqa: E402
from regear.domain.graphics_profiles import (  # noqa: E402
    GraphicsProfile,
    ManagedKey,
    PlanRefusal,
    SupportTier,
    ValueKind,
    plan_application,
    verify_application,
)
from regear.domain.models import OperatingMode  # noqa: E402


MANAGED = {
    key.address: key
    for key in (
        ManagedKey("Graphics", "TextureQuality", ValueKind.INTEGER, minimum=0, maximum=3),
        ManagedKey("Graphics", "ShadowQuality", ValueKind.INTEGER, minimum=0, maximum=3),
        ManagedKey("Graphics", "FrameRateLimit", ValueKind.INTEGER, minimum=30, maximum=240),
        ManagedKey("Display", "Fullscreen", ValueKind.BOOLEAN),
    )
}


def profile(settings, mode=OperatingMode.PORTABLE):
    return GraphicsProfile("620", mode, "graphics.ini", settings)


class ManagedKeyTests(unittest.TestCase):
    def test_integer_range_is_enforced(self):
        key = MANAGED["Graphics/TextureQuality"]
        self.assertTrue(key.accepts("0"))
        self.assertTrue(key.accepts("3"))
        self.assertFalse(key.accepts("4"))
        self.assertFalse(key.accepts("-1"))
        self.assertFalse(key.accepts("high"))
        self.assertFalse(key.accepts(""))

    def test_enumerated_key_accepts_only_its_values(self):
        key = ManagedKey("Graphics", "Preset", ValueKind.ENUMERATED, allowed=("low", "high"))
        self.assertTrue(key.accepts("low"))
        self.assertFalse(key.accepts("ultra"))

    def test_boolean_key_accepts_the_shapes_games_write(self):
        key = MANAGED["Display/Fullscreen"]
        for value in ("0", "1", "true", "False"):
            self.assertTrue(key.accepts(value), value)
        self.assertFalse(key.accepts("yes"))

    def test_malformed_definitions_are_refused(self):
        with self.assertRaises(ValueError):
            ManagedKey("Graphics", "Bad Key", ValueKind.BOOLEAN)
        with self.assertRaises(ValueError):
            ManagedKey("Graphics", "NoRange", ValueKind.INTEGER)
        with self.assertRaises(ValueError):
            ManagedKey("Graphics", "Empty", ValueKind.ENUMERATED)
        with self.assertRaises(ValueError):
            ManagedKey("Graphics", "Inverted", ValueKind.INTEGER, minimum=5, maximum=1)


class ProfileTests(unittest.TestCase):
    def test_unsupported_mode_is_refused_at_construction(self):
        for mode in (OperatingMode.UNKNOWN, OperatingMode.DEGRADED, OperatingMode.BOOSTED_HANDHELD):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                profile({"Graphics/TextureQuality": "1"}, mode)

    def test_malformed_identity_or_filename_is_refused(self):
        with self.assertRaises(ValueError):
            GraphicsProfile("0", OperatingMode.PORTABLE, "graphics.ini", {"Graphics/X": "1"})
        with self.assertRaises(ValueError):
            GraphicsProfile("620", OperatingMode.PORTABLE, "../graphics.ini", {"Graphics/X": "1"})
        with self.assertRaises(ValueError):
            GraphicsProfile("620", OperatingMode.PORTABLE, "graphics.ini", {})


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.document = parse_document(SAMPLE_CONFIG)

    def test_managed_plan_names_only_what_differs(self):
        plan = plan_application(
            self.document,
            profile({"Graphics/TextureQuality": "1", "Graphics/FrameRateLimit": "60"}),
            MANAGED,
        )
        self.assertIs(plan.tier, SupportTier.MANAGED)
        self.assertEqual(plan.changes, {"Graphics/TextureQuality": "1"})
        self.assertEqual(plan.unchanged, ("Graphics/FrameRateLimit",))
        self.assertTrue(plan.writes_anything)

    def test_matching_profile_writes_nothing(self):
        plan = plan_application(self.document, profile({"Graphics/FrameRateLimit": "60"}), MANAGED)
        self.assertIs(plan.tier, SupportTier.MANAGED)
        self.assertFalse(plan.writes_anything)

    def test_absent_key_drops_the_whole_profile_to_advisor(self):
        catalog = MANAGED | {
            "Graphics/Missing": ManagedKey(
                "Graphics", "Missing", ValueKind.INTEGER, minimum=0, maximum=1
            )
        }
        plan = plan_application(
            self.document,
            profile({"Graphics/TextureQuality": "1", "Graphics/Missing": "1"}),
            catalog,
        )
        self.assertIs(plan.tier, SupportTier.ADVISOR)
        # The valid half is not written either: half a profile is a combination
        # the player never chose.
        self.assertEqual(plan.changes, {})
        self.assertIn(("Graphics/Missing", PlanRefusal.KEY_ABSENT), plan.refusals)
        self.assertTrue(plan.advice)

    def test_out_of_range_value_is_advisor_not_a_clamp(self):
        plan = plan_application(self.document, profile({"Graphics/TextureQuality": "9"}), MANAGED)
        self.assertIs(plan.tier, SupportTier.ADVISOR)
        self.assertEqual(plan.refusals, (("Graphics/TextureQuality", PlanRefusal.VALUE_REJECTED),))

    def test_unmanaged_key_is_advisor_even_if_present_in_the_file(self):
        plan = plan_application(self.document, profile({"Audio/MasterVolume": "0.2"}), MANAGED)
        self.assertIs(plan.tier, SupportTier.ADVISOR)
        self.assertEqual(plan.refusals, (("Audio/MasterVolume", PlanRefusal.VALUE_REJECTED),))

    def test_empty_catalog_never_plans_a_write(self):
        plan = plan_application(self.document, profile({"Graphics/TextureQuality": "1"}), {})
        self.assertIs(plan.tier, SupportTier.ADVISOR)


class VerifyTests(unittest.TestCase):
    def test_verification_passes_when_only_managed_keys_moved(self):
        document = parse_document(SAMPLE_CONFIG)
        target = profile({"Graphics/TextureQuality": "1"})
        before = {
            key: value
            for key, value in document.values().items()
            if key not in target.settings
        }
        after = parse_document(document.with_values({"Graphics/TextureQuality": "1"}).render())
        ok, problems = verify_application(after, target, before)
        self.assertTrue(ok, problems)

    def test_verification_fails_when_an_unmanaged_key_moved(self):
        document = parse_document(SAMPLE_CONFIG)
        target = profile({"Graphics/TextureQuality": "1"})
        before = {
            key: value
            for key, value in document.values().items()
            if key not in target.settings
        }
        tampered = parse_document(
            document.with_values(
                {"Graphics/TextureQuality": "1", "Audio/MasterVolume": "0.1"}
            ).render()
        )
        ok, problems = verify_application(tampered, target, before)
        self.assertFalse(ok)
        self.assertTrue(any("Audio/MasterVolume" in problem for problem in problems))

    def test_verification_fails_when_the_managed_value_did_not_land(self):
        document = parse_document(SAMPLE_CONFIG)
        target = profile({"Graphics/TextureQuality": "1"})
        before = {
            key: value
            for key, value in document.values().items()
            if key not in target.settings
        }
        ok, problems = verify_application(document, target, before)
        self.assertFalse(ok)
        self.assertTrue(any("TextureQuality" in problem for problem in problems))


if __name__ == "__main__":
    unittest.main()
