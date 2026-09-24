"""Global and per-game optimization intent."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.game_optimization_preferences import (  # noqa: E402
    DEFAULT_GLOBAL_ENABLED,
    MAX_GAME_PREFERENCES,
    GameChoice,
    GamePreference,
    IntentReason,
    OptimizationPreferences,
    resolve_intent,
)
from regear.domain.mode_profiles import ExperienceTarget  # noqa: E402

APP = "4000000002"
OTHER = "4000000009"


class IntentTests(unittest.TestCase):
    def test_nothing_stored_is_opted_out(self):
        self.assertFalse(DEFAULT_GLOBAL_ENABLED)
        intent = resolve_intent(OptimizationPreferences(), APP)
        self.assertFalse(intent.automatic)
        self.assertIs(intent.reason, IntentReason.GLOBAL_DISABLED)

    def test_untrusted_preferences_withhold_management(self):
        intent = resolve_intent(None, APP)
        self.assertFalse(intent.automatic)
        self.assertIs(intent.reason, IntentReason.PREFERENCES_UNTRUSTED)

    def test_global_switch_is_a_master_switch(self):
        chosen = OptimizationPreferences().with_game(APP, GamePreference(GameChoice.AUTOMATIC))
        self.assertFalse(resolve_intent(chosen, APP).automatic)
        enabled = chosen.with_global(True)
        self.assertIs(resolve_intent(enabled, APP).reason, IntentReason.AUTOMATIC_CHOSEN)
        self.assertIs(resolve_intent(enabled, OTHER).reason, IntentReason.AUTOMATIC_INHERITED)

    def test_manual_opts_one_game_out(self):
        prefs = OptimizationPreferences(True).with_game(APP, GamePreference(GameChoice.MANUAL))
        self.assertIs(resolve_intent(prefs, APP).reason, IntentReason.GAME_MANUAL)
        self.assertTrue(resolve_intent(prefs, OTHER).automatic)

    def test_game_preference_overrides_default_and_inherits_otherwise(self):
        prefs = OptimizationPreferences(True, ExperienceTarget.QUALITY).with_game(
            APP, GamePreference(preference=ExperienceTarget.BATTERY)
        )
        self.assertIs(resolve_intent(prefs, APP).preference, ExperienceTarget.BATTERY)
        self.assertIs(resolve_intent(prefs, OTHER).preference, ExperienceTarget.QUALITY)

    def test_every_change_advances_revision(self):
        prefs = OptimizationPreferences()
        self.assertEqual(prefs.with_global(True).revision, 1)
        self.assertEqual(prefs.with_global(True).with_game(APP, GamePreference()).revision, 2)

    def test_returning_to_inherit_drops_the_entry(self):
        prefs = OptimizationPreferences().with_game(APP, GamePreference(GameChoice.MANUAL))
        self.assertIn(APP, prefs.games)
        self.assertNotIn(APP, prefs.with_game(APP, GamePreference()).games)

    def test_bound_refuses_rather_than_evicting_a_manual_choice(self):
        games = {str(4000000000 + index): GamePreference(GameChoice.MANUAL)
                 for index in range(1, MAX_GAME_PREFERENCES + 1)}
        prefs = OptimizationPreferences(True, games=games)
        with self.assertRaises(ValueError):
            prefs.with_game("4100000000", GamePreference(GameChoice.MANUAL))
        # Changing an existing game is still possible at the bound.
        prefs.with_game("4000000001", GamePreference(GameChoice.AUTOMATIC))

    def test_invalid_values_are_refused(self):
        with self.assertRaises(ValueError):
            OptimizationPreferences(global_enabled=1)
        with self.assertRaises(ValueError):
            OptimizationPreferences(games={"../etc": GamePreference()})
        with self.assertRaises(ValueError):
            OptimizationPreferences().with_game("0", GamePreference())


if __name__ == "__main__":
    unittest.main()
