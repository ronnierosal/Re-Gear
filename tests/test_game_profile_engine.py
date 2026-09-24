"""The Game Profile Engine milestone, end to end, on synthetic fixtures only.

Numbered comments refer to the handoff's required test list.
"""

from __future__ import annotations

import dataclasses
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

import game_profile_engine_fixtures as fx  # noqa: E402
from regear.delivery.game_profile_engine import (  # noqa: E402
    EngineResult,
    GameProfileEngine,
    ProfileRegistry,
)
from regear.delivery.graphics_backup import BackupManager  # noqa: E402
from regear.delivery.graphics_config_locator import GraphicsConfigLocator  # noqa: E402
from regear.delivery.graphics_config_store import ConfigIoError, GraphicsConfigStore  # noqa: E402
from regear.delivery.graphics_management_state import ManagementStateStore  # noqa: E402
from regear.delivery.graphics_profile_service import GameRunState, RestoreResult  # noqa: E402
from regear.domain.graphics_config_format import parse_document  # noqa: E402
from regear.domain.graphics_profiles import SupportTier  # noqa: E402
from regear.domain.mode_profiles import ExperienceTarget  # noqa: E402
from regear.domain.models import OperatingMode  # noqa: E402
from regear.domain.performance_plan import FrameGenerationRef, PerformancePlan  # noqa: E402
from regear.domain.semantic_profiles import (  # noqa: E402
    InternalRender,
    Resolution,
    UpscalingMode,
    ValidationStatus,
)

PORTABLE, TV = OperatingMode.PORTABLE, OperatingMode.TV_DOCKED
BALANCED, QUALITY = ExperienceTarget.BALANCED, ExperienceTarget.QUALITY
IDLE = GameRunState.NOT_RUNNING


class EngineTestCase(unittest.TestCase):
    native = False
    config = fx.SAMPLE

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.steam, self.path = fx.build_library(self.base, native=self.native, config=self.config)
        self.original = self.path.read_bytes()
        self.backups = BackupManager(self.base / "backups")
        self.management = ManagementStateStore(self.base / "state")
        self.engine = self.build()

    def build(self, *, document=None, mapping=None, store=None, allow_fixture=True):
        registry = ProfileRegistry(
            {fx.NATIVE_APP_ID if self.native else fx.APP_ID:
                 dataclasses.replace(document or fx.document(),
                                     steam_app_id=fx.NATIVE_APP_ID if self.native else fx.APP_ID)},
            {"regear-fixture-engine-game": mapping or fx.mapping()},
            {"fixture-ue-gameusersettings-v5": fx.schema()},
        )
        return GameProfileEngine(
            GraphicsConfigLocator(self.steam), self.backups, self.management, registry,
            store, allow_fixture_profiles=allow_fixture,
        )

    @property
    def app(self):
        return fx.NATIVE_APP_ID if self.native else fx.APP_ID

    def apply(self, mode=PORTABLE, preference=BALANCED, state=IDLE, version=fx.GAME_BUILD,
              plan=None, engine=None):
        return (engine or self.engine).apply(self.app, mode, preference, state, version, plan)

    def values(self):
        return parse_document(self.path.read_bytes().decode("utf-8")).values()


class MilestonePipelineTests(EngineTestCase):
    def test_discover_apply_portable_then_tv_then_restore(self):
        # discover -> identify adapter -> read -> validate
        decision = self.engine.decide(self.app, PORTABLE, BALANCED, fx.GAME_BUILD)
        self.assertIs(decision.tier, SupportTier.MANAGED)

        # preserve original -> apply Portable -> verify
        portable = self.apply(PORTABLE)
        self.assertIs(portable.result, EngineResult.APPLIED)
        self.assertEqual(self.values()[fx.TEXTURE], "2")        # textures high
        self.assertEqual(self.values()[fx.SHADOW], "1")         # shadows medium
        self.assertEqual(self.values()[fx.WIDTH], "1280")
        self.assertEqual(self.values()[fx.FRAME_LIMIT], "45")
        self.assertEqual(self.values()[fx.SCALE], "67")         # upscaling quality
        self.assertTrue(self.backups.baseline(portable.apply_outcome.backup.identity).verified)

        # apply TV Docked -> verify
        tv = self.apply(TV)
        self.assertIs(tv.result, EngineResult.APPLIED)
        self.assertEqual(self.values()[fx.WIDTH], "1920")
        self.assertEqual(self.values()[fx.SHADOW], "2")         # shadows high
        self.assertEqual(self.values()[fx.VIEW], "3")           # view distance epic
        self.assertEqual(self.values()[fx.FRAME_LIMIT], "60")
        self.assertEqual(self.values()[fx.SCALE], "100")        # upscaling off

        # restore original -> verify restoration byte-for-byte
        restored = self.engine.restore(self.app, IDLE)
        self.assertIs(restored.result, RestoreResult.RESTORED)
        self.assertTrue(restored.restored_enrolled_original)
        self.assertEqual(self.path.read_bytes(), self.original)


class DiscoveryTests(EngineTestCase):
    def test_01_supported_game_is_managed(self):
        self.assertIs(self.engine.decide(self.app, PORTABLE, BALANCED, fx.GAME_BUILD).tier,
                      SupportTier.MANAGED)

    def test_02_unsupported_game_is_unknown_and_touches_nothing(self):
        outcome = self.engine.apply("4000000099", PORTABLE, BALANCED, IDLE, "x")
        self.assertIs(outcome.result, EngineResult.UNKNOWN)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_03_missing_config_is_not_located(self):
        self.path.unlink()
        self.assertIs(self.apply().result, EngineResult.NOT_LOCATED)

    def test_13_proton_prefix_is_discovered(self):
        self.assertIn("compatdata", str(self.path))
        self.assertIs(self.apply().result, EngineResult.APPLIED)

    def test_a_mode_with_no_profile_is_unknown(self):
        outcome = self.apply(OperatingMode.BOOSTED_HANDHELD)
        self.assertIs(outcome.result, EngineResult.UNKNOWN)


class NativeDiscoveryTests(EngineTestCase):
    native = True

    def test_14_native_linux_install_is_discovered(self):
        self.assertNotIn("compatdata", str(self.path))
        self.assertIs(self.apply().result, EngineResult.APPLIED)
        self.assertEqual(self.values()[fx.TEXTURE], "2")


class MalformedConfigTests(EngineTestCase):
    config = fx.SAMPLE.replace("sg.ShadowQuality=3", "this line is not a setting")

    def test_04_malformed_config_is_never_modified(self):
        outcome = self.apply()
        self.assertIs(outcome.result, EngineResult.ADVISOR)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertTrue(outcome.recommendations)


class UnknownSchemaTests(EngineTestCase):
    config = fx.SAMPLE.replace("Version=5", "Version=6")

    def test_05_and_17_changed_schema_falls_back_from_managed_to_advisor(self):
        outcome = self.apply()
        self.assertIs(outcome.result, EngineResult.ADVISOR)
        self.assertIs(outcome.support, SupportTier.ADVISOR)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertIn("Textures High", outcome.recommendations)


class ApplyTests(EngineTestCase):
    def test_06_and_12_apply_changes_owned_keys_only(self):
        self.apply()
        after = self.values()
        self.assertEqual(after[fx.VOLUME], "0.8")
        self.assertEqual(after[f"{fx.SECTION}/bUseVSync"], "False")
        before = [l for l in self.original.decode().splitlines(keepends=True)
                  if l.startswith(";") or l.startswith("[") or "Volume" in l or "VSync" in l]
        after_lines = [l for l in self.path.read_bytes().decode().splitlines(keepends=True)
                       if l.startswith(";") or l.startswith("[") or "Volume" in l or "VSync" in l]
        self.assertEqual(before, after_lines)                   # CRLF preserved too

    def test_07_first_managed_write_preserves_the_original(self):
        outcome = self.apply()
        baseline = self.backups.baseline(outcome.apply_outcome.backup.identity)
        self.assertEqual(self.backups.payload(baseline.record), self.original)

    def test_09_repeated_apply_is_idempotent(self):
        self.apply()
        after = self.path.read_bytes()
        again = self.apply()
        self.assertIs(again.result, EngineResult.ALREADY_MATCHES)
        self.assertEqual(self.path.read_bytes(), after)

    def test_10_failed_write_preserves_the_original(self):
        class FailingStore(GraphicsConfigStore):
            def write(self, path, text, expected=None):
                raise ConfigIoError("disk full")

        outcome = self.apply(engine=self.build(store=FailingStore()))
        self.assertIs(outcome.result, EngineResult.ROLLED_BACK)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_11_read_only_config_is_advice_not_a_target(self):
        os.chmod(self.path, 0o444)
        self.addCleanup(os.chmod, self.path, 0o644)
        outcome = self.apply()
        self.assertIs(outcome.result, EngineResult.ADVISOR)
        self.assertIn("read-only", outcome.detail)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_unexpected_failures_are_contained(self):
        class Exploding(GraphicsConfigStore):
            def read(self, path):
                raise RuntimeError("nobody predicted this")

        outcome = self.apply(engine=self.build(store=Exploding()))
        self.assertIs(outcome.result, EngineResult.FAILED)


class RestoreTests(EngineTestCase):
    def test_08_restore_returns_the_original(self):
        self.apply()
        self.assertIs(self.engine.restore(self.app, IDLE).result, RestoreResult.RESTORED)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_18_missing_backup_is_reported_not_guessed(self):
        self.assertIs(self.engine.restore(self.app, IDLE).result, RestoreResult.NOTHING_TO_RESTORE)

    def test_19_corrupt_backup_refuses_and_keeps_current_settings(self):
        outcome = self.apply()
        applied = self.path.read_bytes()
        record = self.backups.baseline(outcome.apply_outcome.backup.identity).record
        (self.backups.root / record.identity / record.payload_name).write_bytes(b"junk")
        self.assertIs(self.engine.restore(self.app, IDLE).result, RestoreResult.FAILED)
        self.assertEqual(self.path.read_bytes(), applied)

    def test_stop_managing_keeps_the_file_and_blocks_writes(self):
        self.apply()
        applied = self.path.read_bytes()
        self.assertIsNotNone(self.engine.stop_managing(self.app))
        self.assertIs(self.apply(TV).result, EngineResult.CONFLICT)
        self.assertEqual(self.path.read_bytes(), applied)


class VersionTests(EngineTestCase):
    def test_15_profile_validated_for_another_game_version_is_advisor(self):
        outcome = self.apply(version="fixture-build-8")
        self.assertIs(outcome.result, EngineResult.ADVISOR)
        self.assertTrue(any("tested on" in r for r in outcome.reasons))
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_unknown_game_version_is_advisor(self):
        self.assertIs(self.apply(version=None).result, EngineResult.ADVISOR)

    def test_16_adapter_version_mismatch_is_advisor(self):
        outcome = self.apply(engine=self.build(mapping=fx.mapping(adapter_version=2)))
        self.assertIs(outcome.result, EngineResult.ADVISOR)
        self.assertTrue(any("adapter version" in r for r in outcome.reasons))

    def test_unvalidated_profiles_are_advice(self):
        doc = fx.document(validation=ValidationStatus.UNVALIDATED)
        self.assertIs(self.apply(engine=self.build(document=doc)).result, EngineResult.ADVISOR)

    def test_fixture_profiles_are_not_managed_without_an_explicit_opt_in(self):
        self.assertIs(self.apply(engine=self.build(allow_fixture=False)).result,
                      EngineResult.ADVISOR)


class OverrideAndModeTests(EngineTestCase):
    def test_20_player_changed_managed_value_is_never_silently_overwritten(self):
        self.apply()
        edited = self.path.read_bytes().replace(b"sg.ShadowQuality=1", b"sg.ShadowQuality=2")
        self.path.write_bytes(edited)
        outcome = self.apply(TV)
        self.assertIs(outcome.result, EngineResult.CONFLICT)
        self.assertEqual(self.path.read_bytes(), edited)

    def test_21_mode_change_while_running_is_queued_for_next_launch(self):
        self.apply(PORTABLE)
        portable = self.path.read_bytes()
        outcome = self.apply(TV, state=GameRunState.RUNNING)
        self.assertIs(outcome.result, EngineResult.QUEUED_NEXT_LAUNCH)
        self.assertEqual(outcome.next_launch.mode, TV)
        self.assertEqual(self.path.read_bytes(), portable)
        # At the next launch the request is resolved afresh and applied.
        again = self.apply(outcome.next_launch.mode, outcome.next_launch.preference)
        self.assertIs(again.result, EngineResult.APPLIED)

    def test_unknown_run_state_is_queued_too(self):
        self.assertIs(self.apply(state=GameRunState.UNKNOWN).result,
                      EngineResult.QUEUED_NEXT_LAUNCH)

    def test_22_profile_the_mapping_cannot_express_falls_back_to_advisor(self):
        outcome = self.apply(PORTABLE, QUALITY)
        self.assertIs(outcome.result, EngineResult.ADVISOR)
        self.assertTrue(any("volumetrics" in r for r in outcome.reasons))
        self.assertIn("Volumetrics High", outcome.recommendations)
        self.assertIn("Resolution 1280x800", outcome.recommendations)
        self.assertEqual(self.path.read_bytes(), self.original)


class PerformancePlanTests(EngineTestCase):
    def test_a_frame_generation_plan_caps_real_frames_and_passes_the_provider_through(self):
        plan = PerformancePlan.from_v1(60, 30, Resolution(1600, 900), UpscalingMode.QUALITY,
                               FrameGenerationRef("external-provider", 2), source="fixture")
        outcome = self.apply(TV, plan=plan)
        self.assertIs(outcome.result, EngineResult.APPLIED)
        self.assertEqual(self.values()[fx.FRAME_LIMIT], "30")   # real frames
        self.assertEqual(self.values()[fx.WIDTH], "1600")
        self.assertEqual(self.values()[fx.SCALE], "67")
        self.assertEqual(self.values()[fx.SHADOW], "2")         # profile's own quality
        self.assertEqual(outcome.frame_generation, FrameGenerationRef("external-provider", 2))
        self.assertIn("Target 60 FPS", outcome.recommendations)

    def test_a_native_plan_uses_the_display_target_as_the_cap(self):
        outcome = self.apply(PORTABLE, plan=PerformancePlan.from_v1(40, 40))
        self.assertEqual(self.values()[fx.FRAME_LIMIT], "40")
        self.assertIsNone(outcome.frame_generation)

    def test_a_plan_the_mapping_cannot_express_is_advisor(self):
        outcome = self.apply(TV, plan=PerformancePlan.from_v1(60, 60, Resolution(9000, 9000)))
        self.assertIs(outcome.result, EngineResult.ADVISOR)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_the_plan_contract_refuses_inconsistent_or_unresolved_plans(self):
        with self.assertRaises(ValueError):
            PerformancePlan.from_v1(60, 30)                              # 30 real ≠ 60 shown
        with self.assertRaises(ValueError):
            PerformancePlan.from_v1(60, 30, frame_generation=FrameGenerationRef("x", 3))
        with self.assertRaises(ValueError):
            PerformancePlan.from_v1(60, 60, upscaling=UpscalingMode.AUTO)

    def test_a_queued_request_keeps_the_plan_for_next_launch(self):
        plan = PerformancePlan.from_v1(60, 30, frame_generation=FrameGenerationRef("x", 2))
        outcome = self.apply(TV, state=GameRunState.RUNNING, plan=plan)
        self.assertEqual(outcome.next_launch.plan, plan)


class PlanV2Tests(EngineTestCase):
    """PerformancePlan v2 through the real engine and foundation, bytes on disk."""

    FG = FrameGenerationRef("fixture-provider", 2)

    def render_scale_engine(self):
        return self.build(document=fx.render_scale_document(), mapping=fx.render_scale_mapping())

    def v2(self, **changes):
        values = dict(requested_display_fps=60, target_display_fps=60, base_fps_target=60)
        values.update(changes)
        return PerformancePlan(**values)

    def test_1080p_game_output_on_a_4k_display_writes_only_the_game_output(self):
        plan = self.v2(requested_display_fps=90, target_display_fps=60, base_fps_target=30,
                       frame_generation=self.FG, game_output_resolution=Resolution(1920, 1080),
                       display_output_resolution=Resolution(3840, 2160))
        outcome = self.apply(TV, plan=plan)
        self.assertIs(outcome.result, EngineResult.APPLIED)
        self.assertEqual(self.values()[fx.WIDTH], "1920")
        self.assertEqual(self.values()[fx.HEIGHT], "1080")
        self.assertEqual(self.values()[fx.FRAME_LIMIT], "30")  # rendered frames
        self.assertNotIn(b"3840", self.path.read_bytes())       # display is never written
        self.assertEqual(outcome.frame_generation, self.FG)
        self.assertIn("Requested 90 FPS; planned 60 FPS", outcome.plan_notes)
        self.assertIn("Display 3840x2160", outcome.plan_notes)

    def test_native_upscaling_keeps_internal_and_output_apart(self):
        # 1440x810 inside a 1920x1080 output is exactly 75 percent.
        plan = self.v2(game_output_resolution=Resolution(1920, 1080),
                       internal_render=Resolution(1440, 810))
        outcome = self.apply(TV, plan=plan, engine=self.render_scale_engine())
        self.assertIs(outcome.result, EngineResult.APPLIED)
        self.assertEqual(self.values()[fx.WIDTH], "1920")
        self.assertEqual(self.values()[fx.SCALE], "75")

    def test_supersampling_within_the_game_limit_is_written(self):
        plan = self.v2(game_output_resolution=Resolution(1280, 800),
                       internal_render=Resolution(1920, 1200))
        outcome = self.apply(PORTABLE, plan=plan, engine=self.render_scale_engine())
        self.assertIs(outcome.result, EngineResult.APPLIED)
        self.assertEqual(self.values()[fx.SCALE], "150")

    def test_unknown_internal_render_writes_no_render_scale(self):
        outcome = self.apply(TV, plan=self.v2(game_output_resolution=Resolution(1920, 1080)),
                             engine=self.render_scale_engine())
        self.assertIs(outcome.result, EngineResult.APPLIED)
        self.assertEqual(self.values()[fx.SCALE], "100")  # the player's own value

    def test_inexpressible_internal_render_is_advisor_with_no_partial_write(self):
        cases = {
            "no render-scale relation in this mapping": (
                self.engine, Resolution(1920, 1080), Resolution(1440, 810)),
            "dynamic": (self.render_scale_engine(), Resolution(1920, 1080), InternalRender.DYNAMIC),
            "different aspect": (self.render_scale_engine(), Resolution(1280, 800), Resolution(1280, 720)),
            "fractional percent": (self.render_scale_engine(), Resolution(1920, 1080), Resolution(1280, 720)),
            "beyond the game's limit": (self.render_scale_engine(), Resolution(1280, 800), Resolution(3200, 2000)),
            "unknown game output": (self.render_scale_engine(), None, Resolution(640, 400)),
        }
        for name, (engine, output, internal) in cases.items():
            with self.subTest(name):
                profile_output = dict(game_output_resolution=output) if output else {}
                plan = self.v2(internal_render=internal, **profile_output)
                document = fx.render_scale_document()
                if output is None:
                    # A profile that states no output either, so nothing anchors the scale.
                    document = dataclasses.replace(document, profiles={
                        PORTABLE: {BALANCED: dataclasses.replace(
                            document.profile(PORTABLE, BALANCED), game_output_resolution=None)}})
                    engine = self.build(document=document, mapping=fx.render_scale_mapping())
                outcome = self.apply(PORTABLE, plan=plan, engine=engine)
                self.assertIs(outcome.result, EngineResult.ADVISOR)
                self.assertTrue(any("internal_render" in reason for reason in outcome.reasons))
                self.assertEqual(self.path.read_bytes(), self.original)

    def test_a_render_scale_key_cannot_share_the_upscaling_key(self):
        with self.assertRaises(ValueError):
            dataclasses.replace(fx.mapping(), render_scale_key=fx.mapping().upscaling_key)

    def test_a_queued_v2_plan_is_kept_whole_for_next_launch(self):
        plan = self.v2(requested_display_fps=90, target_display_fps=60, base_fps_target=30,
                       frame_generation=self.FG, display_output_resolution=Resolution(3840, 2160))
        outcome = self.apply(TV, state=GameRunState.RUNNING, plan=plan)
        self.assertIs(outcome.result, EngineResult.QUEUED_NEXT_LAUNCH)
        self.assertEqual(outcome.next_launch.plan, plan)
        self.assertEqual(self.path.read_bytes(), self.original)


if __name__ == "__main__":
    unittest.main()
