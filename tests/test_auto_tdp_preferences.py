import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from hdm.domain.auto_tdp import AutoTdpPolicy
from hdm.domain.auto_tdp_preferences import (
    AutoTdpModePreference,
    AutoTdpPreferenceSet,
    AutoTdpProviderBounds,
    resolve_auto_tdp_preference,
    validate_auto_tdp_preference_bounds,
)
from hdm.domain.control_plane import PlacementState


def preference(placement, minimum, maximum, fps):
    return AutoTdpModePreference(
        placement,
        AutoTdpPolicy(minimum, maximum, fps),
    )


class AutoTdpPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.portable = preference(PlacementState.PORTABLE, 7, 18, 40)
        self.boosted = preference(PlacementState.BOOSTED_HANDHELD, 12, 25, 60)
        self.docked_igpu = preference(PlacementState.DOCKED_IGPU, 10, 22, 50)
        self.docked_egpu = preference(PlacementState.DOCKED_EGPU, 8, 15, 30)
        self.preferences = AutoTdpPreferenceSet(
            (self.portable, self.boosted, self.docked_igpu, self.docked_egpu)
        )

    def test_distinct_stable_placements_resolve_exact_policy(self):
        expected = {
            PlacementState.PORTABLE: (7, 18, 40),
            PlacementState.BOOSTED_HANDHELD: (12, 25, 60),
            PlacementState.DOCKED_IGPU: (10, 22, 50),
            PlacementState.DOCKED_EGPU: (8, 15, 30),
        }
        for placement, values in expected.items():
            with self.subTest(placement=placement):
                result = resolve_auto_tdp_preference(self.preferences, placement)
                self.assertTrue(result.available)
                self.assertEqual(result.code, "auto_tdp_preference.exact_match")
                self.assertEqual(
                    (
                        result.preference.minimum_watts,
                        result.preference.maximum_watts,
                        result.preference.target_fps,
                    ),
                    values,
                )
                self.assertFalse(result.authorizes_activation)

    def test_unknown_degraded_or_invalid_placement_never_falls_back(self):
        for placement, code in (
            (PlacementState.UNKNOWN, "auto_tdp_preference.placement_unresolved"),
            (PlacementState.DEGRADED, "auto_tdp_preference.placement_unresolved"),
            ("portable", "auto_tdp_preference.placement_invalid"),
            (None, "auto_tdp_preference.placement_invalid"),
        ):
            with self.subTest(placement=placement):
                result = resolve_auto_tdp_preference(self.preferences, placement)
                self.assertFalse(result.available)
                self.assertEqual(result.code, code)

    def test_stable_unconfigured_placement_has_no_fallback(self):
        result = resolve_auto_tdp_preference(
            AutoTdpPreferenceSet((self.portable,)),
            PlacementState.DOCKED_IGPU,
        )
        self.assertFalse(result.available)
        self.assertEqual(result.code, "auto_tdp_preference.not_configured")

    def test_unstable_placement_cannot_be_configured(self):
        for placement in (PlacementState.UNKNOWN, PlacementState.DEGRADED):
            with self.subTest(placement=placement), self.assertRaises(ValueError):
                preference(placement, 7, 18, 40)
        with self.assertRaises(ValueError):
            AutoTdpModePreference("portable", AutoTdpPolicy(7, 18, 40))

    def test_policy_validation_rejects_invalid_fps_and_watts(self):
        for minimum, maximum, fps in (
            (0, 18, 40), (-1, 18, 40), (True, 18, 40),
            (7, 0, 40), (7, 6, 40), (7, 18.0, 40),
            (7, 18, 0), (7, 18, -1), (7, 18, float("nan")),
            (7, 18, float("inf")), (7, 18, True),
        ):
            with self.subTest(values=(minimum, maximum, fps)), self.assertRaises(ValueError):
                preference(PlacementState.PORTABLE, minimum, maximum, fps)

    def test_set_requires_immutable_nonempty_valid_unique_entries(self):
        for entries in ((), [self.portable], (object(),), (self.portable, self.portable)):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                AutoTdpPreferenceSet(entries)

    def test_preference_set_and_nested_policy_are_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            self.preferences.preferences = ()
        with self.assertRaises(FrozenInstanceError):
            self.portable.policy.minimum_watts = 10

    def test_provider_bounds_validation_is_separate_and_non_authorizing(self):
        bounds = AutoTdpProviderBounds(5, 20)
        result = validate_auto_tdp_preference_bounds(self.portable, bounds)
        self.assertTrue(result.fits_provider_bounds)
        self.assertEqual(result.code, "auto_tdp_preference.within_provider_bounds")
        self.assertFalse(result.authorizes_activation)
        result = validate_auto_tdp_preference_bounds(self.boosted, bounds)
        self.assertFalse(result.fits_provider_bounds)
        self.assertEqual(result.code, "auto_tdp_preference.outside_provider_bounds")
        self.assertFalse(result.authorizes_activation)

    def test_provider_bounds_are_strict_validated_values(self):
        for minimum, maximum in (
            (0, 20), (-1, 20), (True, 20), (5, 0),
            (5, 4), (5.0, 20), (5, 20.0), (5, 1 << 32),
        ):
            with self.subTest(bounds=(minimum, maximum)), self.assertRaises(ValueError):
                AutoTdpProviderBounds(minimum, maximum)
        for preference_value, bounds_value in (
            (object(), AutoTdpProviderBounds(5, 20)),
            (self.portable, object()),
        ):
            result = validate_auto_tdp_preference_bounds(preference_value, bounds_value)
            self.assertFalse(result.fits_provider_bounds)
            self.assertEqual(result.code, "auto_tdp_preference.bounds_invalid")

    def test_invalid_set_input_resolves_without_activation(self):
        result = resolve_auto_tdp_preference(object(), PlacementState.PORTABLE)
        self.assertFalse(result.available)
        self.assertFalse(result.authorizes_activation)
        self.assertEqual(result.code, "auto_tdp_preference.set_invalid")


if __name__ == "__main__":
    unittest.main()
