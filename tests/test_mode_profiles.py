from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.mode_profiles import (  # noqa: E402
    DisplayModePreference,
    DisplayPreference,
    ExperienceTarget,
    FeaturePreference,
    GameRenderTarget,
    ModeProfile,
    ModeProfileSet,
    resolve_mode_profile,
)
from regear.domain.models import OperatingMode  # noqa: E402


def profile(mode: OperatingMode, profile_id: str = "profile") -> ModeProfile:
    return ModeProfile(
        profile_id,
        mode,
        DisplayModePreference(DisplayPreference.PRESERVE_CURRENT),
    )


class ModeProfileTests(unittest.TestCase):
    def test_display_and_game_render_targets_are_explicitly_independent(self):
        mode_profile = ModeProfile(
            "tv-quality",
            OperatingMode.TV_DOCKED,
            DisplayModePreference(
                DisplayPreference.EXTERNAL,
                width=3840,
                height=2160,
                refresh_hz=120,
                hdr=FeaturePreference.PREFER,
                vrr=FeaturePreference.PREFER,
            ),
            GameRenderTarget(width=1920, height=1080, target_fps=60),
            ExperienceTarget.QUALITY,
        )
        self.assertEqual(mode_profile.display.width, 3840)
        self.assertEqual(mode_profile.game_render.width, 1920)
        self.assertEqual(mode_profile.game_render.target_fps, 60)

    def test_only_an_exact_stable_observed_mode_gets_a_profile(self):
        profiles = ModeProfileSet(
            (
                profile(OperatingMode.PORTABLE, "portable"),
                profile(OperatingMode.TV_DOCKED, "tv"),
            )
        )
        matched = resolve_mode_profile(profiles, OperatingMode.TV_DOCKED)
        self.assertTrue(matched.available)
        self.assertEqual(matched.profile.profile_id, "tv")
        self.assertEqual(matched.reason, "mode_profile.exact_match")

        missing = resolve_mode_profile(profiles, OperatingMode.BOOSTED_HANDHELD)
        self.assertFalse(missing.available)
        self.assertEqual(missing.reason, "mode_profile.not_configured")

    def test_unknown_and_degraded_modes_never_receive_a_fallback_profile(self):
        profiles = ModeProfileSet((profile(OperatingMode.PORTABLE, "portable"),))
        for mode in (OperatingMode.UNKNOWN, OperatingMode.DEGRADED):
            with self.subTest(mode=mode):
                decision = resolve_mode_profile(profiles, mode)
                self.assertFalse(decision.available)
                self.assertEqual(
                    decision.reason, "mode_profile.observed_mode_unstable"
                )

    def test_invalid_or_ambiguous_preferences_are_rejected_at_construction(self):
        with self.assertRaisesRegex(ValueError, "together"):
            DisplayModePreference(DisplayPreference.INTERNAL, width=1920)
        with self.assertRaisesRegex(ValueError, "positive"):
            GameRenderTarget(target_fps=0)
        with self.assertRaisesRegex(ValueError, "stable"):
            profile(OperatingMode.UNKNOWN)
        with self.assertRaisesRegex(ValueError, "one mode profile"):
            ModeProfileSet(
                (
                    profile(OperatingMode.PORTABLE, "one"),
                    profile(OperatingMode.PORTABLE, "two"),
                )
            )


if __name__ == "__main__":
    unittest.main()
