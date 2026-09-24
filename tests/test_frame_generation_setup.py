from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.frame_generation_setup import (  # noqa: E402
    SetupFacts,
    SetupState,
    assess_setup,
)


def complete(**overrides):
    values = dict(
        lossless_scaling_installed=True,
        lsfg_component_present=True,
        linux_component_present=True,
        linux_component_version="2.0.0",
        layer_visible_to_games=True,
    )
    values.update(overrides)
    return SetupFacts(**values)


class SetupStateTests(unittest.TestCase):
    def test_missing_purchase_or_install(self):
        result = assess_setup(complete(lossless_scaling_installed=False))
        self.assertIs(result.state, SetupState.LOSSLESS_SCALING_MISSING)
        self.assertFalse(result.installed)
        self.assertTrue(any("yourself" in step for step in result.next_steps))

    def test_missing_lsfg_component_branch(self):
        result = assess_setup(complete(lsfg_component_present=False))
        self.assertIs(result.state, SetupState.LSFG_COMPONENT_MISSING)

    def test_missing_linux_component(self):
        result = assess_setup(complete(linux_component_present=False))
        self.assertIs(result.state, SetupState.LINUX_COMPONENT_MISSING)

    def test_linux_component_installed_but_invisible_to_games(self):
        # A host installation does not establish availability inside Steam's
        # runtime; invisibility counts as missing where games run.
        result = assess_setup(complete(layer_visible_to_games=False))
        self.assertIs(result.state, SetupState.LINUX_COMPONENT_MISSING)

    def test_version_mismatch(self):
        result = assess_setup(complete(linux_component_version="1.0.0"))
        self.assertIs(result.state, SetupState.VERSION_MISMATCH)
        self.assertFalse(result.installed)

    def test_installed_but_unvalidated(self):
        result = assess_setup(complete())
        self.assertIs(result.state, SetupState.INSTALLED_UNVALIDATED)
        self.assertTrue(result.installed)
        self.assertFalse(result.validated)
        self.assertTrue(any("installation is not validation" in s for s in result.next_steps))

    def test_eligible_fixture_configuration_is_scoped_to_fixtures(self):
        result = assess_setup(complete(fixture=True, validated_record_available=True))
        self.assertIs(result.state, SetupState.ELIGIBLE_FIXTURE_CONFIGURATION)
        self.assertTrue(result.installed)
        self.assertTrue(result.validated)
        self.assertTrue(result.fixture_only)
        self.assertTrue(any("not support for any real game" in s for s in result.next_steps))

    def test_a_real_game_record_never_reaches_an_eligible_state(self):
        # Real-game validation is a supervised gate this milestone does not pass.
        result = assess_setup(complete(validated_record_available=True))
        self.assertIs(result.state, SetupState.INSTALLED_UNVALIDATED)
        self.assertFalse(result.validated)
        self.assertFalse(result.fixture_only)

    def test_installed_is_never_validated_on_its_own(self):
        for facts in (complete(), complete(fixture=True)):
            with self.subTest(facts=facts):
                self.assertFalse(assess_setup(facts).validated)


class UnknownFactTests(unittest.TestCase):
    def test_no_facts_is_unknown_not_missing(self):
        result = assess_setup(SetupFacts())
        self.assertIs(result.state, SetupState.UNKNOWN)
        self.assertFalse(result.installed)
        self.assertIn("lossless_scaling_installed", result.unknown)
        self.assertTrue(any("Nothing is assumed" in s for s in result.next_steps))

    def test_one_unknown_fact_prevents_an_installed_verdict(self):
        result = assess_setup(complete(layer_visible_to_games=None))
        self.assertIs(result.state, SetupState.UNKNOWN)
        self.assertIn("layer_visible_to_games", result.unknown)

    def test_an_unknown_version_is_unknown_not_a_mismatch(self):
        result = assess_setup(complete(linux_component_version=None))
        self.assertIs(result.state, SetupState.UNKNOWN)
        self.assertIn("linux_component_version", result.unknown)

    def test_a_known_missing_step_wins_over_later_unknowns(self):
        # The first concrete blocker is reported even if later facts are unknown,
        # and those unknowns are still listed.
        result = assess_setup(SetupFacts(lossless_scaling_installed=False))
        self.assertIs(result.state, SetupState.LOSSLESS_SCALING_MISSING)
        self.assertIn("linux_component_present", result.unknown)


if __name__ == "__main__":
    unittest.main()
