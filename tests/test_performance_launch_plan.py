"""The inert launch plan, the LSFG-VK planner, and the fixture composition demo.

The composition test is the prototype's before/after trace:

    fake AppID -> existing adapter profile -> target 60 -> declared stable 30 at 2x
    -> proposed LSFG-VK environment overlay -> disabled -> original launch, exactly.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

import performance_fixtures as fx  # noqa: E402
from regear.application.performance_launch_plan import (  # noqa: E402
    LaunchPlan,
    OriginalLaunch,
    build_launch_plan,
)
from regear.domain.frame_generation_provider import (  # noqa: E402
    LSFG_VK_REVISION,
    LsfgVkProvider,
    ProviderConfiguration,
)
from regear.domain.mode_profiles import ExperienceTarget  # noqa: E402
from regear.domain.models import GameState  # noqa: E402
from regear.domain.performance_target_resolver import (  # noqa: E402
    Outcome,
    PerformanceIntent,
    resolve,
)


#: A realistic, awkward launch-options string: a wrapper, quoting, an existing
#: environment assignment and %command%. It must survive byte-for-byte.
ORIGINAL_OPTIONS = 'gamemoderun MANGOHUD_CONFIG="fps_limit=0,position=top-left" %command% -dx12 --skip-intro'
ORIGINAL_ENV = {"PROTON_LOG": "1", "DXVK_HUD": "fps"}


def fg_decision(**context_overrides):
    return resolve(
        PerformanceIntent(60),
        fx.context(**context_overrides),
        GameState.IDLE,
        fx.adapter(),
        (fx.native(), fx.frame_generation()),
        fx.providers(),
    )


def original(options=ORIGINAL_OPTIONS, env=None):
    return OriginalLaunch(options, dict(ORIGINAL_ENV if env is None else env))


class CompositionDemoTests(unittest.TestCase):
    """The before/after trace the assignment asks for, end to end."""

    def test_fixture_app_to_proposed_overlay_and_back_to_the_original(self):
        # Before: the player's own launch.
        before = original()

        # 1. The fixture game is served by an existing adapter profile.
        adapter = fx.adapter()
        self.assertTrue(adapter.serves(fx.FIXTURE_APP_ID))

        # 2. The player asks for 60 FPS on a 60 Hz TV.
        decision = fg_decision()

        # 3. Native quality is validated at only 30; the FG record declares a
        #    stable 30 at 2x, compared against that native result.
        self.assertIs(decision.outcome, Outcome.FRAME_GENERATION)
        self.assertEqual(decision.required_stable_base_fps, 30)
        self.assertEqual(decision.multiplier, 2)
        self.assertEqual(decision.achievable_fps, 60)
        self.assertEqual(decision.profile.settings,
                         adapter.profile_for(fx.FIXTURE_APP_ID, decision.profile.mode,
                                             ExperienceTarget.QUALITY).settings)

        # 4. The provider proposes an overlay -- data only.
        plan = build_launch_plan(decision, before, LsfgVkProvider(fx.FIXTURE_DLL))
        self.assertEqual(
            dict(plan.environment_overlay),
            {
                "LSFGVK_ENV": "1",
                "LSFGVK_DLL_PATH": fx.FIXTURE_DLL,
                "LSFGVK_MULTIPLIER": "2",
                "LSFGVK_PACING_MODE": "vsync",
            },
        )
        self.assertFalse(plan.execution_allowed)
        self.assertEqual(plan.provider_revision, LSFG_VK_REVISION)
        self.assertEqual(plan.launch_options, ORIGINAL_OPTIONS)
        self.assertEqual(dict(plan.original.environment), ORIGINAL_ENV)

        # 5. Unresolved requirements are carried, not dropped.
        self.assertTrue(any(u.startswith("base_limiter") for u in plan.unresolved))
        self.assertTrue(any(u.startswith("provider_initialization_failure") for u in plan.unresolved))
        self.assertTrue(any(u.startswith("launch_interception_seam") for u in plan.unresolved))

        # After: disabling returns the original launch exactly.
        after = plan.disable()
        self.assertEqual(after.launch_options, before.launch_options)
        self.assertEqual(dict(after.proposed_environment), dict(before.environment))
        self.assertFalse(after.changes_anything)
        self.assertFalse(after.execution_allowed)


class InertnessTests(unittest.TestCase):
    def test_a_plan_can_never_allow_execution(self):
        with self.assertRaises(ValueError):
            LaunchPlan(original(), Outcome.FRAME_GENERATION, execution_allowed=True)

    def test_even_a_fully_resolved_looking_plan_is_inert(self):
        plan = build_launch_plan(fg_decision(), original(), LsfgVkProvider(fx.FIXTURE_DLL))
        self.assertTrue(plan.changes_anything)
        self.assertFalse(plan.execution_allowed)
        self.assertTrue(plan.unresolved)

    def test_plans_and_originals_cannot_be_mutated_after_construction(self):
        plan = build_launch_plan(fg_decision(), original(), LsfgVkProvider(fx.FIXTURE_DLL))
        with self.assertRaises(TypeError):
            plan.environment_overlay["LSFGVK_MULTIPLIER"] = "4"
        with self.assertRaises(TypeError):
            plan.original.environment["PROTON_LOG"] = "0"


class PreservationTests(unittest.TestCase):
    def test_launch_options_are_carried_byte_for_byte(self):
        awkward = "  WINEDLLOVERRIDES=\"dxgi=n,b\"   %command%  'quoted arg' \\\"x\\\"\t"
        plan = build_launch_plan(fg_decision(), original(awkward), LsfgVkProvider(fx.FIXTURE_DLL))
        self.assertEqual(plan.launch_options, awkward)
        self.assertEqual(plan.disable().launch_options, awkward)

    def test_the_original_environment_is_never_edited(self):
        env = dict(ORIGINAL_ENV)
        plan = build_launch_plan(fg_decision(), original(env=env), LsfgVkProvider(fx.FIXTURE_DLL))
        self.assertEqual(env, ORIGINAL_ENV)
        self.assertEqual(dict(plan.original.environment), ORIGINAL_ENV)
        for key, value in ORIGINAL_ENV.items():
            self.assertEqual(plan.proposed_environment[key], value)

    def test_an_overlay_may_not_replace_a_player_variable(self):
        with self.assertRaises(ValueError):
            LaunchPlan(original(env={"LSFGVK_MULTIPLIER": "3"}), Outcome.FRAME_GENERATION,
                       environment_overlay={"LSFGVK_MULTIPLIER": "2"})


class PlayerOverrideTests(unittest.TestCase):
    def assert_original_kept(self, env, fragment):
        plan = build_launch_plan(fg_decision(), original(env=env), LsfgVkProvider(fx.FIXTURE_DLL))
        self.assertFalse(plan.changes_anything)
        self.assertEqual(dict(plan.proposed_environment), env)
        self.assertEqual(plan.launch_options, ORIGINAL_OPTIONS)
        self.assertTrue(any(fragment in r for r in plan.reasons), plan.reasons)

    def test_disable_lsfgvk_is_respected(self):
        self.assert_original_kept({"DISABLE_LSFGVK": "1"}, "opt-out is respected")

    def test_an_existing_player_lsfg_configuration_is_not_overwritten(self):
        self.assert_original_kept({"LSFGVK_MULTIPLIER": "3"}, "not overwritten")

    def test_a_file_based_player_configuration_is_not_overwritten(self):
        self.assert_original_kept({"LSFGVK_CONFIG": "/home/deck/lsfg.toml"}, "not overwritten")


class FallbackTests(unittest.TestCase):
    def test_non_frame_generation_decisions_carry_no_overlay(self):
        decision = resolve(PerformanceIntent(60), fx.context(), GameState.IDLE, fx.adapter(),
                           (fx.native("native-quality", 60),), fx.providers())
        plan = build_launch_plan(decision, original(), LsfgVkProvider(fx.FIXTURE_DLL))
        self.assertIs(plan.outcome, Outcome.NATIVE)
        self.assertFalse(plan.changes_anything)

    def test_a_deferred_decision_keeps_the_original(self):
        decision = resolve(PerformanceIntent(60), fx.context(), GameState.RUNNING, fx.adapter(),
                           (fx.native(), fx.frame_generation()), fx.providers())
        plan = build_launch_plan(decision, original(), LsfgVkProvider(fx.FIXTURE_DLL))
        self.assertIs(plan.outcome, Outcome.DEFERRED)
        self.assertFalse(plan.changes_anything)

    def test_a_provider_that_raises_leaves_the_original_exactly(self):
        class Exploding:
            provider_id = "lsfg-vk"
            revision = LSFG_VK_REVISION

            def plan(self, decision, environment):
                raise RuntimeError("provider blew up")

        plan = build_launch_plan(fg_decision(), original(), Exploding())
        self.assertFalse(plan.changes_anything)
        self.assertEqual(plan.launch_options, ORIGINAL_OPTIONS)
        self.assertEqual(dict(plan.proposed_environment), ORIGINAL_ENV)
        self.assertTrue(any("original launch is kept" in r for r in plan.reasons))

    def test_no_provider_keeps_the_original(self):
        plan = build_launch_plan(fg_decision(), original(), None)
        self.assertFalse(plan.changes_anything)

    def test_a_provider_for_another_revision_refuses(self):
        stale = LsfgVkProvider(fx.FIXTURE_DLL, revision="0" * 40)
        plan = build_launch_plan(fg_decision(), original(), stale)
        self.assertFalse(plan.changes_anything)

    def test_a_missing_dll_path_refuses(self):
        plan = build_launch_plan(fg_decision(), original(), LsfgVkProvider(""))
        self.assertFalse(plan.changes_anything)


class ProviderTests(unittest.TestCase):
    def test_the_provider_refuses_a_non_frame_generation_decision(self):
        decision = resolve(PerformanceIntent(60), fx.context(), GameState.IDLE, fx.adapter(),
                           (fx.native("native-quality", 60),), fx.providers())
        result = LsfgVkProvider(fx.FIXTURE_DLL).plan(decision, {})
        self.assertIsInstance(result, ProviderConfiguration)
        self.assertFalse(result.proposes_anything)
        self.assertTrue(result.refused)

    def test_the_multiplier_comes_from_the_decision_not_a_default(self):
        decision = resolve(
            PerformanceIntent(90),
            fx.context(refresh_hz=90),
            GameState.IDLE,
            fx.adapter(),
            (fx.frame_generation("fg-3x", base=30, multiplier=3, refresh_hz=90,
                                 compared_against=()),),
            fx.providers(supported_multipliers=(2, 3)),
        )
        result = LsfgVkProvider(fx.FIXTURE_DLL).plan(decision, {})
        self.assertEqual(result.environment_overlay["LSFGVK_MULTIPLIER"], "3")


if __name__ == "__main__":
    unittest.main()
