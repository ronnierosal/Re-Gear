import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.control_plane import PlacementState  # noqa: E402
from regear.domain.power_modes import PowerMode  # noqa: E402
from regear.domain.power_profile_catalog import (  # noqa: E402
    CurrentPowerEvidence,
    CatalogEvaluationProvenance,
    DeviceIdentity,
    DevicePowerProfile,
    DocumentedPowerRange,
    EvidenceDimensions,
    NativePowerProfile,
    PowerProfileCatalog,
    PowerRangeKind,
    PowerSource,
    ProviderBinding,
    SourceReference,
    resolve_power_profile,
)
from regear.profiles.handheld_power_catalog import (  # noqa: E402
    ALLY_X_2024,
    GPD_WIN_MINI_2023,
    HANDHELD_POWER_CATALOG,
    LEGION_GO_8APU1,
    STEAM_DECK_LCD,
    STEAM_DECK_OLED,
)


SOURCE = SourceReference("native-test", "https://example.test/power", "synthetic test evidence")
IDENTITY = DeviceIdentity("Example", "Handheld", "Exact Variant")
PROVIDER = ProviderBinding("native-provider", "binding-v1")
VALIDATED = EvidenceDimensions(
    researched=True,
    backend_discovered=True,
    fixture_tested=True,
    write_tested=True,
    restore_tested=True,
    hardware_validated=True,
)


def native(
    *,
    mode=PowerMode.BALANCED,
    watts=15,
    power_source=PowerSource.BATTERY,
    placement=PlacementState.PORTABLE,
    provider=PROVIDER,
    evidence=VALIDATED,
):
    return NativePowerProfile(
        mode,
        f"native-{mode.value}",
        watts,
        provider,
        power_source,
        placement,
        evidence,
        (SOURCE,),
    )


def catalog(*profiles):
    return PowerProfileCatalog(
        1,
        (DevicePowerProfile(IDENTITY, VALIDATED, (SOURCE,), native_profiles=tuple(profiles)),),
    )


def current(**changes):
    values = dict(
        identity=IDENTITY,
        provider=PROVIDER,
        power_source=PowerSource.BATTERY,
        placement=PlacementState.PORTABLE,
        generation=5,
        observed_generation=5,
        minimum_watts=5,
        maximum_watts=25,
        identity_verified=True,
        binding_verified=True,
        range_verified=True,
        restoration_verified=True,
        ownership_verified=True,
        context_verified=True,
        evidence_id="current-5",
    )
    values.update(changes)
    return CurrentPowerEvidence(**values)


class CatalogResolutionTests(unittest.TestCase):
    def test_exact_native_profile_is_available_but_never_authorizes_activation(self):
        profile = native()
        result = resolve_power_profile(catalog(profile), PowerMode.BALANCED, current())
        self.assertTrue(result.available)
        self.assertIs(result.profile, profile)
        self.assertFalse(result.follow_system)
        self.assertFalse(result.authorizes_activation)
        self.assertEqual(result.code, "power_profile.exact_non_authorizing_match")
        self.assertEqual(
            result.provenance,
            CatalogEvaluationProvenance(1, "current-5", 5, 5),
        )

    def test_identity_model_variant_provider_power_source_and_placement_are_exact(self):
        base = catalog(native())
        cases = (
            (dict(identity=DeviceIdentity("Example", "Handheld", "Other Variant")), "device_missing"),
            (dict(provider=ProviderBinding("native-provider", "binding-v2")), "named_profile_missing"),
            (dict(power_source=PowerSource.AC), "named_profile_missing"),
            (dict(placement=PlacementState.DOCKED_IGPU), "named_profile_missing"),
        )
        for changes, fragment in cases:
            with self.subTest(changes=changes):
                result = resolve_power_profile(base, PowerMode.BALANCED, current(**changes))
                self.assertFalse(result.available)
                self.assertTrue(result.follow_system)
                self.assertIn(fragment, result.code)
                self.assertIs(result.requested_mode, PowerMode.BALANCED)

    def test_no_manual_mode_is_derived_from_verified_range(self):
        empty = catalog()
        for mode in (PowerMode.BATTERY_SAVER, PowerMode.BALANCED, PowerMode.PERFORMANCE):
            with self.subTest(mode=mode):
                result = resolve_power_profile(empty, mode, current(minimum_watts=4, maximum_watts=30))
                self.assertFalse(result.available)
                self.assertEqual(result.code, "power_profile.named_profile_missing_or_ambiguous")
                self.assertIs(result.requested_mode, mode)

    def test_target_outside_range_is_rejected_without_clamping(self):
        result = resolve_power_profile(
            catalog(native(watts=25)),
            PowerMode.BALANCED,
            current(minimum_watts=5, maximum_watts=20),
        )
        self.assertFalse(result.available)
        self.assertEqual(result.code, "power_profile.target_outside_verified_range")

    def test_missing_conflicting_or_research_only_evidence_never_becomes_ready(self):
        evidence_cases = (
            EvidenceDimensions(researched=True),
            EvidenceDimensions(researched=True, source_conflicted=True),
            EvidenceDimensions(backend_discovered=True, fixture_tested=True),
            EvidenceDimensions(backend_discovered=True, write_tested=True, hardware_validated=True),
        )
        for evidence in evidence_cases:
            with self.subTest(evidence=evidence):
                result = resolve_power_profile(
                    catalog(native(evidence=evidence)), PowerMode.BALANCED, current()
                )
                self.assertFalse(result.available)
                self.assertEqual(result.code, "power_profile.native_validation_incomplete")

    def test_stale_or_uncertain_current_evidence_follows_system(self):
        cases = (
            (dict(observed_generation=4), "generation_stale"),
            (dict(identity_verified=False), "identity_unverified"),
            (dict(binding_verified=False), "binding_unverified"),
            (dict(range_verified=False), "range_unverified"),
            (dict(restoration_verified=False), "restoration_unverified"),
            (dict(ownership_verified=False), "ownership_unverified"),
            (dict(context_verified=False), "context_unverified"),
        )
        for changes, suffix in cases:
            with self.subTest(changes=changes):
                result = resolve_power_profile(catalog(native()), PowerMode.BALANCED, current(**changes))
                self.assertFalse(result.available)
                self.assertEqual(result.code, f"power_profile.{suffix}")
                self.assertEqual(result.provenance.catalog_version, 1)
                self.assertEqual(result.provenance.evidence_id, "current-5")
                self.assertEqual(result.provenance.current_generation, 5)
                self.assertEqual(
                    result.provenance.observed_generation,
                    changes.get("observed_generation", 5),
                )

    def test_resolution_provenance_changes_with_catalog_and_current_evidence(self):
        profile = native()
        first = resolve_power_profile(catalog(profile), PowerMode.BALANCED, current())
        second_catalog = PowerProfileCatalog(2, catalog(profile).profiles)
        second = resolve_power_profile(
            second_catalog,
            PowerMode.BALANCED,
            current(generation=6, observed_generation=6, evidence_id="current-6"),
        )
        self.assertNotEqual(first.provenance, second.provenance)
        self.assertEqual(second.provenance.catalog_version, 2)
        self.assertEqual(second.provenance.evidence_id, "current-6")
        self.assertEqual(second.provenance.current_generation, 6)
        self.assertFalse(second.authorizes_activation)

    def test_unresolved_placement_system_and_auto_do_not_select_manual_profiles(self):
        for placement in (PlacementState.UNKNOWN, PlacementState.DEGRADED):
            result = resolve_power_profile(
                catalog(native()), PowerMode.BALANCED, current(placement=placement)
            )
            self.assertEqual(result.code, "power_profile.placement_unresolved")
        self.assertEqual(
            resolve_power_profile(catalog(native()), PowerMode.SYSTEM_CONTROL, current()).code,
            "power_profile.follow_system",
        )
        self.assertEqual(
            resolve_power_profile(catalog(native()), PowerMode.AUTO, current()).code,
            "power_profile.auto_requires_runtime_admission",
        )


class CatalogValidationTests(unittest.TestCase):
    def test_bool_float_nonfinite_zero_reversed_and_partial_bounds_are_rejected(self):
        for changes in (
            dict(minimum_watts=True),
            dict(minimum_watts=0),
            dict(minimum_watts=-1),
            dict(minimum_watts=5.0),
            dict(minimum_watts=float("nan")),
            dict(minimum_watts=26, maximum_watts=25),
            dict(minimum_watts=None, maximum_watts=25),
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                current(**changes)
        for value in (True, 0, -1, 15.0, float("nan"), float("inf")):
            with self.subTest(target=value), self.assertRaises(ValueError):
                native(watts=value)
        for minimum, maximum in (
            (True, 30),
            (0, 30),
            (5.0, 30),
            (float("nan"), 30),
            (31, 30),
        ):
            with self.subTest(documented=(minimum, maximum)), self.assertRaises(ValueError):
                DocumentedPowerRange(
                    minimum,
                    maximum,
                    PowerRangeKind.PUBLISHED_APU_TDP,
                    SOURCE,
                )

    def test_catalog_version_and_evidence_flags_are_strict(self):
        device = DevicePowerProfile(IDENTITY, VALIDATED, (SOURCE,))
        for version in (True, 0, -1, 1.0):
            with self.subTest(version=version), self.assertRaises(ValueError):
                PowerProfileCatalog(version, (device,))
        with self.assertRaises(ValueError):
            EvidenceDimensions(researched=1)

    def test_duplicate_device_and_native_bindings_are_rejected(self):
        device = DevicePowerProfile(IDENTITY, VALIDATED, (SOURCE,), native_profiles=(native(),))
        with self.assertRaises(ValueError):
            PowerProfileCatalog(1, (device, device))
        with self.assertRaises(ValueError):
            DevicePowerProfile(IDENTITY, VALIDATED, (SOURCE,), native_profiles=(native(), native()))

    def test_catalog_and_nested_contracts_are_immutable(self):
        value = catalog(native())
        with self.assertRaises(FrozenInstanceError):
            value.version = 2
        with self.assertRaises(FrozenInstanceError):
            value.profiles[0].identity = DeviceIdentity("x", "y", "z")

    def test_new_contracts_have_no_production_callers_outside_the_new_catalog(self):
        allowed = {
            Path("backend/regear/domain/power_modes.py"),
            Path("backend/regear/domain/power_profile_catalog.py"),
            Path("backend/regear/profiles/handheld_power_catalog.py"),
        }
        unexpected = []
        for path in (ROOT / "backend" / "regear").rglob("*.py"):
            relative = path.relative_to(ROOT)
            if relative in allowed:
                continue
            source = path.read_text(encoding="utf-8")
            if "power_modes" in source or "power_profile_catalog" in source:
                unexpected.append(str(relative))
        self.assertEqual(unexpected, [])


class ResearchCatalogTests(unittest.TestCase):
    def test_research_records_are_exact_separate_models_without_native_profiles(self):
        records = HANDHELD_POWER_CATALOG.profiles
        self.assertEqual(len(records), 5)
        self.assertEqual(
            {record.identity.variant for record in records},
            {"RC72LA", "83E1", "LCD", "OLED", "Win Mini 2023 7840U"},
        )
        self.assertTrue(all(record.evidence.researched for record in records))
        self.assertTrue(all(record.native_profiles == () for record in records))
        self.assertIsNot(STEAM_DECK_LCD, STEAM_DECK_OLED)

    def test_ally_conflicting_sources_are_preserved_without_selecting_a_preset(self):
        self.assertTrue(ALLY_X_2024.evidence.source_conflicted)
        self.assertEqual(
            (ALLY_X_2024.documented_range.minimum_watts, ALLY_X_2024.documented_range.maximum_watts),
            (9, 30),
        )
        self.assertIs(ALLY_X_2024.documented_range.kind, PowerRangeKind.PUBLISHED_APU_TDP)
        performance = tuple(claim.watts for claim in ALLY_X_2024.oem_claims if claim.name == "Performance")
        self.assertEqual(performance, (17, 15, 17))
        result = resolve_power_profile(
            HANDHELD_POWER_CATALOG,
            PowerMode.PERFORMANCE,
            current(identity=ALLY_X_2024.identity),
        )
        self.assertFalse(result.available)
        self.assertEqual(result.code, "power_profile.named_profile_missing_or_ambiguous")

    def test_legion_custom_ceiling_is_not_performance_and_decks_have_no_modes(self):
        claims = {claim.name: claim.watts for claim in LEGION_GO_8APU1.oem_claims}
        self.assertEqual(claims["Performance"], 20)
        self.assertEqual(claims["Custom ceiling"], 30)
        self.assertIs(LEGION_GO_8APU1.documented_range.kind, PowerRangeKind.OEM_CUSTOM_MODE)
        self.assertEqual(STEAM_DECK_LCD.oem_claims, ())
        self.assertEqual(STEAM_DECK_OLED.oem_claims, ())

    def test_win_mini_limits_and_modes_remain_unknown(self):
        self.assertIsNone(GPD_WIN_MINI_2023.documented_range)
        self.assertEqual(GPD_WIN_MINI_2023.oem_claims, ())
        self.assertEqual(GPD_WIN_MINI_2023.native_profiles, ())


if __name__ == "__main__":
    unittest.main()
