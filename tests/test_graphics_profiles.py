from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

import graphics_profile_fixtures as fixtures  # noqa: E402
from regear.domain.graphics_config_format import parse_document  # noqa: E402
from regear.domain.graphics_game_adapter import ProfileResolver  # noqa: E402
from regear.domain.graphics_profiles import (  # noqa: E402
    GraphicsProfile,
    ManagedKey,
    PlanRefusal,
    SupportTier,
    ValueKind,
    plan_application,
    verify_application,
)
from regear.domain.graphics_schema import SchemaVerdict  # noqa: E402
from regear.domain.mode_profiles import ExperienceTarget  # noqa: E402
from regear.domain.models import OperatingMode  # noqa: E402


SCHEMA, MANAGED = fixtures.sample_schema()
ADAPTER = fixtures.sample_adapter()
APP = fixtures.PROTON_APP_ID


def profile(settings, mode=OperatingMode.PORTABLE):
    return GraphicsProfile(APP, mode, fixtures.CONFIG_FILENAME, settings)


class ManagedKeyTests(unittest.TestCase):
    def test_integer_range_is_enforced(self):
        key = MANAGED[fixtures.TEXTURE]
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
        key = ManagedKey("Graphics", "bUseVSync", ValueKind.BOOLEAN)
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
    def test_unrecognised_placements_are_refused_at_construction(self):
        for mode in (OperatingMode.UNKNOWN, OperatingMode.DEGRADED):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                profile({fixtures.TEXTURE: "1"}, mode)

    def test_the_three_player_facing_placements_are_bindable(self):
        for mode in (
            OperatingMode.PORTABLE,
            OperatingMode.BOOSTED_HANDHELD,
            OperatingMode.TV_DOCKED,
        ):
            with self.subTest(mode=mode):
                self.assertEqual(profile({fixtures.TEXTURE: "1"}, mode).mode, mode)

    def test_malformed_identity_version_or_filename_is_refused(self):
        with self.assertRaises(ValueError):
            GraphicsProfile("0", OperatingMode.PORTABLE, "g.ini", {fixtures.TEXTURE: "1"})
        with self.assertRaises(ValueError):
            GraphicsProfile("620", OperatingMode.PORTABLE, "../g.ini", {fixtures.TEXTURE: "1"})
        with self.assertRaises(ValueError):
            GraphicsProfile("620", OperatingMode.PORTABLE, "g.ini", {})
        with self.assertRaises(ValueError):
            GraphicsProfile(
                "620", OperatingMode.PORTABLE, "g.ini", {fixtures.TEXTURE: "1"},
                profile_version=0,
            )


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.document = parse_document(fixtures.SAMPLE_CONFIG)

    def test_the_sample_matches_the_declared_schema(self):
        assessment = SCHEMA.assess(self.document)
        self.assertIs(assessment.verdict, SchemaVerdict.MATCHED)
        self.assertEqual(assessment.observed_version, "5")
        self.assertTrue(assessment.signature)

    def test_an_unsupported_version_does_not_match(self):
        document = parse_document(fixtures.SAMPLE_CONFIG.replace("Version=5", "Version=999"))
        self.assertIs(SCHEMA.assess(document).verdict, SchemaVerdict.VERSION_UNSUPPORTED)

    def test_an_absent_version_does_not_match(self):
        document = parse_document(fixtures.SAMPLE_CONFIG.replace("Version=5\n", ""))
        self.assertIs(SCHEMA.assess(document).verdict, SchemaVerdict.VERSION_ABSENT)

    def test_a_missing_required_key_does_not_match(self):
        document = parse_document(
            fixtures.SAMPLE_CONFIG.replace("sg.ViewDistanceQuality = 3\r\n", "")
        )
        self.assertIs(SCHEMA.assess(document).verdict, SchemaVerdict.KEY_ABSENT)

    def test_an_unrecognised_current_value_does_not_match(self):
        document = parse_document(
            fixtures.SAMPLE_CONFIG.replace("sg.TextureQuality=3", "sg.TextureQuality=EPIC")
        )
        self.assertIs(
            SCHEMA.assess(document).verdict, SchemaVerdict.CURRENT_VALUE_UNSUPPORTED
        )

    def test_the_signature_follows_shape_not_values(self):
        changed_value = parse_document(
            fixtures.SAMPLE_CONFIG.replace("sg.TextureQuality=3", "sg.TextureQuality=1")
        )
        added_key = parse_document(fixtures.SAMPLE_CONFIG + "[New]\nKey=1\n")
        base = SCHEMA.assess(self.document).signature
        self.assertEqual(SCHEMA.assess(changed_value).signature, base)
        self.assertNotEqual(SCHEMA.assess(added_key).signature, base)


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.document = parse_document(fixtures.SAMPLE_CONFIG)
        self.matched = SCHEMA.assess(self.document)

    def test_managed_plan_names_only_what_differs(self):
        plan = plan_application(
            self.document,
            profile({fixtures.TEXTURE: "1", fixtures.FRAME_LIMIT: "60"}),
            MANAGED,
            self.matched,
        )
        self.assertIs(plan.tier, SupportTier.MANAGED)
        self.assertEqual(plan.changes, {fixtures.TEXTURE: "1"})
        self.assertEqual(plan.unchanged, (fixtures.FRAME_LIMIT,))
        self.assertTrue(plan.writes_anything)

    def test_matching_profile_writes_nothing(self):
        plan = plan_application(
            self.document, profile({fixtures.FRAME_LIMIT: "60"}), MANAGED, self.matched
        )
        self.assertIs(plan.tier, SupportTier.MANAGED)
        self.assertFalse(plan.writes_anything)

    def test_without_a_matched_schema_the_tier_is_unknown(self):
        document = parse_document(fixtures.SAMPLE_CONFIG.replace("Version=5", "Version=999"))
        plan = plan_application(
            document, profile({fixtures.TEXTURE: "1"}), MANAGED, SCHEMA.assess(document)
        )
        self.assertIs(plan.tier, SupportTier.UNKNOWN)
        self.assertEqual(plan.changes, {})
        self.assertEqual(plan.refusals[0][1], PlanRefusal.SCHEMA_UNRECOGNISED)

    def test_no_assessment_at_all_is_unknown(self):
        plan = plan_application(self.document, profile({fixtures.TEXTURE: "1"}), MANAGED)
        self.assertIs(plan.tier, SupportTier.UNKNOWN)

    def test_absent_key_drops_the_whole_profile_to_advisor(self):
        catalog = MANAGED | {
            "Audio/Missing": ManagedKey("Audio", "Missing", ValueKind.INTEGER, minimum=0, maximum=1)
        }
        plan = plan_application(
            self.document,
            profile({fixtures.TEXTURE: "1", "Audio/Missing": "1"}),
            catalog,
            self.matched,
        )
        self.assertIs(plan.tier, SupportTier.ADVISOR)
        # The valid half is not written either: half a profile is a combination
        # the player never chose.
        self.assertEqual(plan.changes, {})
        self.assertIn(("Audio/Missing", PlanRefusal.KEY_ABSENT), plan.refusals)
        self.assertTrue(plan.advice)

    def test_out_of_range_value_is_advisor_not_a_clamp(self):
        plan = plan_application(
            self.document, profile({fixtures.TEXTURE: "9"}), MANAGED, self.matched
        )
        self.assertIs(plan.tier, SupportTier.ADVISOR)
        self.assertEqual(plan.refusals, ((fixtures.TEXTURE, PlanRefusal.VALUE_REJECTED),))

    def test_unmanaged_key_is_advisor_even_if_present_in_the_file(self):
        plan = plan_application(
            self.document, profile({fixtures.MASTER_VOLUME: "0.2"}), MANAGED, self.matched
        )
        self.assertIs(plan.tier, SupportTier.ADVISOR)

    def test_empty_catalog_never_plans_a_write(self):
        plan = plan_application(self.document, profile({fixtures.TEXTURE: "1"}), {}, self.matched)
        self.assertIs(plan.tier, SupportTier.ADVISOR)


class VerifyTests(unittest.TestCase):
    def remainder(self, document, target):
        return {
            key: value
            for key, value in document.values().items()
            if key not in target.settings
        }

    def test_verification_passes_when_only_managed_keys_moved(self):
        document = parse_document(fixtures.SAMPLE_CONFIG)
        target = profile({fixtures.TEXTURE: "1"})
        after = parse_document(document.with_values({fixtures.TEXTURE: "1"}).render())
        ok, problems = verify_application(after, target, self.remainder(document, target))
        self.assertTrue(ok, problems)

    def test_verification_fails_when_an_unmanaged_key_moved(self):
        document = parse_document(fixtures.SAMPLE_CONFIG)
        target = profile({fixtures.TEXTURE: "1"})
        tampered = parse_document(
            document.with_values(
                {fixtures.TEXTURE: "1", fixtures.MASTER_VOLUME: "0.1"}
            ).render()
        )
        ok, problems = verify_application(tampered, target, self.remainder(document, target))
        self.assertFalse(ok)
        self.assertTrue(any(fixtures.MASTER_VOLUME in problem for problem in problems))

    def test_verification_fails_when_the_managed_value_did_not_land(self):
        document = parse_document(fixtures.SAMPLE_CONFIG)
        target = profile({fixtures.TEXTURE: "1"})
        ok, problems = verify_application(document, target, self.remainder(document, target))
        self.assertFalse(ok)
        self.assertTrue(any("TextureQuality" in problem for problem in problems))


class AdapterAndResolverTests(unittest.TestCase):
    def resolver(self, preferences):
        return ProfileResolver((ADAPTER,), preferences)

    def test_a_declared_mode_and_target_produce_a_versioned_bound_profile(self):
        resolved = self.resolver({OperatingMode.PORTABLE: ExperienceTarget.BATTERY}).resolve(
            APP, OperatingMode.PORTABLE
        )
        self.assertIsNotNone(resolved.profile)
        self.assertEqual(resolved.profile.schema_id, SCHEMA.schema_id)
        self.assertEqual(resolved.profile.profile_version, 1)

    def test_an_undeclared_target_yields_no_profile_rather_than_a_guess(self):
        resolved = self.resolver({OperatingMode.PORTABLE: ExperienceTarget.SMOOTH_60}).resolve(
            APP, OperatingMode.PORTABLE
        )
        self.assertIsNone(resolved.profile)
        self.assertIn("declares no settings", resolved.reason)

    def test_an_unrecognised_placement_selects_nothing(self):
        for mode in (OperatingMode.UNKNOWN, OperatingMode.DEGRADED):
            with self.subTest(mode=mode):
                resolved = self.resolver(
                    {OperatingMode.PORTABLE: ExperienceTarget.BATTERY}
                ).resolve(APP, mode)
                self.assertIsNone(resolved.profile)

    def test_no_preference_selects_nothing(self):
        resolved = self.resolver({}).resolve(APP, OperatingMode.PORTABLE)
        self.assertIsNone(resolved.profile)
        self.assertIn("no preference", resolved.reason)

    def test_an_unserved_app_selects_nothing(self):
        resolved = self.resolver({OperatingMode.PORTABLE: ExperienceTarget.BATTERY}).resolve(
            "999999", OperatingMode.PORTABLE
        )
        self.assertIsNone(resolved.profile)

    def test_an_adapter_may_not_declare_values_for_keys_it_does_not_own(self):
        from regear.domain.graphics_game_adapter import GameSettingsAdapter

        with self.assertRaises(ValueError):
            GameSettingsAdapter(
                adapter_id="bad",
                steam_app_ids=(APP,),
                config_filename=fixtures.CONFIG_FILENAME,
                relative_dir=fixtures.GAME_CONFIG_DIR,
                schema=SCHEMA,
                owned_keys=MANAGED,
                declared_settings={ExperienceTarget.BATTERY: {fixtures.MASTER_VOLUME: "0.1"}},
            )


if __name__ == "__main__":
    unittest.main()
