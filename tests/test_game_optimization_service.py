"""Automatic optimization end to end, through the real engine, on fixtures only.

Every test drives the unchanged Game Profile Engine and graphics foundation
against the synthetic game's configuration file, and asserts on the bytes on
disk as well as on the lifecycle. No real game, launch hook or telemetry.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

import game_optimization_fixtures as ofx  # noqa: E402
import game_profile_engine_fixtures as fx  # noqa: E402
from regear.delivery.game_optimization_service import (  # noqa: E402
    GameOptimizationService,
    LaunchAction,
    ReviewedAdapters,
)
from regear.delivery.game_optimization_store import (  # noqa: E402
    GameOptimizationStore,
    LoadState,
    StoreError,
)
from regear.delivery.game_profile_catalog import load_catalog  # noqa: E402
from regear.delivery.game_profile_engine import EngineResult, GameProfileEngine  # noqa: E402
from regear.delivery.graphics_backup import BackupManager  # noqa: E402
from regear.delivery.graphics_config_locator import GraphicsConfigLocator  # noqa: E402
from regear.delivery.graphics_management_state import ManagementStateStore  # noqa: E402
from regear.delivery.graphics_profile_service import GameRunState  # noqa: E402
from regear.domain.game_optimization_preferences import GameChoice, GamePreference  # noqa: E402
from regear.domain.game_optimization_state import (  # noqa: E402
    AttemptOutcome,
    LaneKey,
    LearningPolicy,
    ObservationWindow,
    PerformanceContextRef,
    Phase,
    QueuedPlan,
    WindowVerdict,
)
from regear.domain.graphics_config_format import parse_document  # noqa: E402
from regear.domain.mode_profiles import ExperienceTarget  # noqa: E402
from regear.domain.models import OperatingMode  # noqa: E402
from regear.domain.performance_plan import FrameGenerationRef, PerformancePlan  # noqa: E402
from regear.domain.semantic_profiles import Resolution, UpscalingMode  # noqa: E402

APP = ofx.APP_ID
PORTABLE, TV = OperatingMode.PORTABLE, OperatingMode.TV_DOCKED
IDLE, RUNNING = GameRunState.NOT_RUNNING, GameRunState.RUNNING
BALANCED = ExperienceTarget.BALANCED
POLICY = LearningPolicy()
MEETS, BELOW = WindowVerdict.MEETS_TARGET, WindowVerdict.BELOW_TARGET
PERF = PerformanceContextRef("fixture-gpu-a.display-800p")
#: A lighter candidate: 40 FPS cap and a balanced render scale.
LIGHTER = QueuedPlan(
    "lighter-40",
    BALANCED,
    PerformancePlan(40, 40, Resolution(1280, 800), UpscalingMode.BALANCED, source="fixture"),
)


class SimulatedCrash(BaseException):
    """The process dies: nothing after this point in the call runs."""


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.steam, self.path = fx.build_library(self.base)
        self.original = self.path.read_bytes()
        self.catalog_dir = ofx.write_catalog(self.base / "catalog")
        self.state_root = self.base / "optimization"
        self.crash_after_write = False
        self.last = None
        self.service = self.build()

    def engine_factory(self, registry):
        engine = GameProfileEngine(
            GraphicsConfigLocator(self.steam),
            BackupManager(self.base / "backups"),
            ManagementStateStore(self.base / "management"),
            registry,
            allow_fixture_profiles=True,
        )
        if not self.crash_after_write:
            return engine
        test = self

        class Crashing:
            def decide(self, *args, **kwargs):
                return engine.decide(*args, **kwargs)

            def apply(self, *args, **kwargs):
                engine.apply(*args, **kwargs)
                test.crash_after_write = False
                raise SimulatedCrash()

            def restore(self, *args, **kwargs):
                return engine.restore(*args, **kwargs)

        return Crashing()

    def build(self, store=None):
        """A fresh service over the same disk: what a restart looks like."""
        return GameOptimizationService(
            store or GameOptimizationStore(self.state_root),
            load_catalog(self.catalog_dir),
            ReviewedAdapters(
                {"regear-fixture-engine-game": fx.mapping()},
                {"fixture-ue-gameusersettings-v5": fx.schema()},
            ),
            self.engine_factory,
            POLICY,
            allow_fixture_policy=True,
        )

    def launch(self, mode=PORTABLE, state=IDLE, version=fx.GAME_BUILD, service=None, perf=PERF):
        self.last = (service or self.service).prepare_launch(APP, mode, state, version, perf)
        return self.last

    def window(self, qualified=True, verdict=MEETS, binding=None):
        return ObservationWindow(binding or self.last.binding, qualified, verdict)

    def propose(self, candidate, mode=PORTABLE, service=None):
        basis = self.lane(mode).value.context
        return (service or self.service).propose(APP, mode, candidate, basis)

    def lane(self, mode=PORTABLE, service=None):
        return (service or self.service).state(APP, mode)

    def phase(self, mode=PORTABLE):
        return self.lane(mode).value.phase

    def values(self):
        return parse_document(self.path.read_bytes().decode("utf-8")).values()

    def windows(self, count, verdict=MEETS, qualified=True, mode=PORTABLE):
        for _ in range(count):
            outcome = self.service.record_window(APP, mode, self.window(qualified, verdict))
            self.assertTrue(outcome.ok, outcome.detail)

    def enable(self):
        self.assertTrue(self.service.set_global(True).ok)

    def learned(self):
        self.enable()
        self.launch()
        self.windows(POLICY.learning_windows)

    def validating(self):
        self.learned()
        self.assertTrue(self.propose(LIGHTER).ok)
        result = self.launch()
        self.assertIs(result.action, LaunchAction.APPLIED_CANDIDATE)

    def locked(self):
        self.validating()
        self.windows(POLICY.accept_windows)
        self.assertIs(self.phase(), Phase.OPTIMIZED_LOCKED)


class OptInTests(ServiceTestCase):
    def test_nothing_happens_until_the_player_opts_in(self):
        result = self.launch()
        self.assertIs(result.action, LaunchAction.PASSTHROUGH)
        self.assertTrue(result.may_launch)
        self.assertEqual(self.path.read_bytes(), self.original)
        # And no lifecycle record is left behind for a game never managed.
        self.assertIs(self.lane().state, LoadState.ABSENT)

    def test_first_enabled_launch_is_baseline_and_writes_nothing(self):
        self.enable()
        result = self.launch()
        self.assertIs(result.action, LaunchAction.PASSTHROUGH)
        self.assertIs(result.phase, Phase.BASELINE)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_unknown_or_degraded_mode_withholds_everything(self):
        self.enable()
        for mode in (OperatingMode.UNKNOWN, OperatingMode.DEGRADED):
            result = self.launch(mode=mode)
            self.assertIs(result.action, LaunchAction.PASSTHROUGH)
            self.assertIn(mode.value, result.reasons[0])
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_unknown_game_version_is_not_managed(self):
        self.enable()
        self.assertIs(self.launch(version=None).phase, Phase.ADVISOR_ONLY)


class NextLaunchTests(ServiceTestCase):
    def test_candidate_waits_for_the_next_idle_launch(self):
        self.learned()
        self.assertTrue(self.propose(LIGHTER).ok)
        self.assertEqual(self.path.read_bytes(), self.original)  # proposing writes nothing
        running = self.launch(state=RUNNING)
        self.assertIs(running.action, LaunchAction.PASSTHROUGH)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertIs(self.phase(), Phase.TESTING_PROFILE)
        applied = self.launch()
        self.assertIs(applied.action, LaunchAction.APPLIED_CANDIDATE)
        self.assertIs(applied.engine.result, EngineResult.APPLIED)
        self.assertEqual(self.values()[fx.FRAME_LIMIT], "40")
        self.assertEqual(self.values()[fx.SCALE], "58")
        self.assertIs(self.phase(), Phase.VALIDATING)

    def test_accepted_plan_locks_and_later_launches_change_nothing(self):
        self.locked()
        written = self.path.read_bytes()
        again = self.launch()
        self.assertIs(again.action, LaunchAction.REAPPLIED_ACCEPTED)
        self.assertIs(again.engine.result, EngineResult.ALREADY_MATCHES)
        self.assertEqual(self.path.read_bytes(), written)

    def test_rejected_candidate_puts_the_original_back_byte_for_byte(self):
        self.validating()
        self.windows(POLICY.reject_windows, BELOW)
        self.assertNotEqual(self.path.read_bytes(), self.original)
        result = self.launch()
        self.assertIs(result.action, LaunchAction.RESTORED_ORIGINAL)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.lane().value.history[-1].outcome, AttemptOutcome.REJECTED)
        # Nothing further is due: the original stays.
        self.assertIs(self.launch().action, LaunchAction.PASSTHROUGH)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_uncertain_evidence_never_locks(self):
        self.validating()
        self.windows(POLICY.validation_window_budget, qualified=False)
        self.assertIsNone(self.lane().value.accepted)
        self.assertEqual(self.lane().value.history[-1].outcome, AttemptOutcome.INCONCLUSIVE)
        self.launch()
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_frame_generation_reference_passes_through_untouched(self):
        self.learned()
        fg = FrameGenerationRef("fixture-provider", 2)
        plan = PerformancePlan(60, 30, Resolution(1280, 800), UpscalingMode.QUALITY, fg)
        self.propose(QueuedPlan("fg-60", BALANCED, plan))
        result = self.launch()
        self.assertEqual(result.frame_generation, fg)
        self.assertEqual(self.values()[fx.FRAME_LIMIT], "30")  # the real-frame cap

    def test_modes_have_independent_lifecycles(self):
        self.locked()
        tv = self.launch(mode=TV)
        self.assertIs(tv.phase, Phase.BASELINE)
        self.assertIs(self.phase(PORTABLE), Phase.OPTIMIZED_LOCKED)


class PlayerEditTests(ServiceTestCase):
    def edit(self):
        text = self.path.read_bytes().decode("utf-8").replace("sg.TextureQuality=2", "sg.TextureQuality=0")
        self.path.write_bytes(text.encode("utf-8"))
        return self.path.read_bytes()

    def test_edit_under_a_locked_plan_is_kept_and_ends_management(self):
        self.locked()
        edited = self.edit()
        result = self.launch()
        self.assertIs(result.action, LaunchAction.NOT_LANDED)
        self.assertIs(result.engine.result, EngineResult.CONFLICT)
        self.assertIs(self.phase(), Phase.USER_OVERRIDE)
        self.assertEqual(self.path.read_bytes(), edited)
        # Later launches leave it alone entirely.
        self.assertIs(self.launch().action, LaunchAction.PASSTHROUGH)
        self.assertEqual(self.path.read_bytes(), edited)

    def test_edit_during_validation_is_caught_at_the_next_launch(self):
        self.validating()
        edited = self.edit()
        self.launch()
        self.assertIs(self.phase(), Phase.USER_OVERRIDE)
        self.assertEqual(self.path.read_bytes(), edited)
        self.assertEqual(self.lane().value.history[-1].outcome, AttemptOutcome.CONFLICT)

    def test_handing_back_never_claims_the_edited_bytes(self):
        self.locked()
        edited = self.edit()
        self.launch()
        self.assertTrue(self.service.resume_automatic(APP, PORTABLE).ok)
        self.launch()
        # The engine's own conflict rule still decides: the edit survives.
        self.assertEqual(self.path.read_bytes(), edited)
        self.assertIs(self.phase(), Phase.USER_OVERRIDE)

    def test_explicit_restore_returns_the_original_and_hands_the_game_back(self):
        self.locked()
        outcome = self.service.restore_original(APP, PORTABLE, IDLE)
        self.assertTrue(outcome.restored_enrolled_original)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertIs(self.phase(), Phase.USER_OVERRIDE)
        self.assertIs(self.launch().action, LaunchAction.PASSTHROUGH)
        self.assertEqual(self.path.read_bytes(), self.original)


class DisableTests(ServiceTestCase):
    def test_global_off_cancels_pending_work_in_every_lane_now(self):
        self.learned()
        self.propose(LIGHTER)
        self.launch(mode=TV)
        self.assertTrue(self.service.set_global(False).ok)
        for mode in (PORTABLE, TV):
            self.assertIs(self.phase(mode), Phase.OPTIMIZATION_DISABLED)
        self.assertIsNone(self.lane().value.candidate)
        self.assertIs(self.launch().action, LaunchAction.PASSTHROUGH)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_turning_off_never_rewrites_settings(self):
        self.locked()
        written = self.path.read_bytes()
        self.service.set_global(False)
        self.launch()
        self.assertEqual(self.path.read_bytes(), written)

    def test_per_game_manual_cancels_only_that_game(self):
        self.learned()
        self.propose(LIGHTER)
        self.assertTrue(self.service.set_game(ofx.OTHER_APP_ID, GamePreference(GameChoice.MANUAL)).ok)
        self.assertIs(self.phase(), Phase.TESTING_PROFILE)
        self.assertTrue(self.service.set_game(APP, GamePreference(GameChoice.MANUAL)).ok)
        self.assertIs(self.phase(), Phase.OPTIMIZATION_DISABLED)

    def test_reenabling_resumes_a_locked_plan_through_the_engine(self):
        self.locked()
        written = self.path.read_bytes()
        self.service.set_global(False)
        self.service.set_global(True)
        result = self.launch()
        self.assertIs(result.action, LaunchAction.REAPPLIED_ACCEPTED)
        self.assertEqual(self.path.read_bytes(), written)
        self.assertIs(self.phase(), Phase.OPTIMIZED_LOCKED)

    def test_changing_the_preference_is_a_new_context(self):
        self.locked()
        self.service.set_default_preference(ExperienceTarget.QUALITY)
        result = self.launch()
        # Portable quality asks for volumetrics the mapping cannot express.
        self.assertIs(result.phase, Phase.ADVISOR_ONLY)
        self.assertIs(result.action, LaunchAction.PASSTHROUGH)


class VersionTests(ServiceTestCase):
    def test_game_update_revalidates_and_writes_nothing(self):
        self.locked()
        written = self.path.read_bytes()
        result = self.launch(version="fixture-build-8")
        # The profile was tested on build 7: the engine says Advisor.
        self.assertIs(result.phase, Phase.ADVISOR_ONLY)
        self.assertEqual(self.path.read_bytes(), written)
        self.assertEqual(self.lane().value.accepted, LIGHTER)  # kept as evidence
        # Back on the tested build, the accepted plan is reused.
        self.assertIs(self.launch().phase, Phase.OPTIMIZED_LOCKED)

    def test_adapter_version_change_invalidates_the_accepted_context(self):
        self.locked()
        service = GameOptimizationService(
            GameOptimizationStore(self.state_root),
            load_catalog(ofx.write_catalog(self.base / "catalog2", ofx.entry(adapter_version=2))),
            ReviewedAdapters(
                {"regear-fixture-engine-game": fx.mapping(adapter_version=2)},
                {"fixture-ue-gameusersettings-v5": fx.schema()},
            ),
            self.engine_factory,
            POLICY,
            allow_fixture_policy=True,
        )
        result = self.launch(service=service)
        self.assertIs(result.phase, Phase.NEEDS_REVALIDATION)
        self.assertIn("adapter_version", result.reasons[0])
        self.assertIs(result.action, LaunchAction.PASSTHROUGH)


class RestartTests(ServiceTestCase):
    def test_lifecycle_and_preferences_survive_a_restart(self):
        self.validating()
        self.windows(1)
        restarted = self.build()
        self.assertTrue(restarted.intent(APP).automatic)
        lane = self.lane(service=restarted).value
        self.assertIs(lane.phase, Phase.VALIDATING)
        self.assertEqual(lane.meets, 1)
        self.assertEqual(lane.candidate, LIGHTER)

    def test_crash_mid_write_is_uncertain_and_never_replayed(self):
        self.learned()
        self.propose(LIGHTER)
        self.crash_after_write = True
        with self.assertRaises(SimulatedCrash):
            self.launch()
        on_disk = self.lane().value
        self.assertIsNotNone(on_disk.in_flight)  # the mark was durable first
        written = self.path.read_bytes()
        restarted = self.build()
        result = self.launch(service=restarted)
        self.assertIs(result.action, LaunchAction.PASSTHROUGH)
        lane = self.lane(service=restarted).value
        self.assertIsNone(lane.in_flight)
        self.assertIs(lane.phase, Phase.NEEDS_REVALIDATION)
        self.assertEqual(lane.history[-1].outcome, AttemptOutcome.UNCERTAIN)
        self.assertEqual(self.path.read_bytes(), written)  # not replayed, not undone

    def test_no_write_happens_if_the_in_flight_mark_cannot_be_saved(self):
        self.learned()
        self.propose(LIGHTER)

        class FailingStore(GameOptimizationStore):
            def save_state(self, state, expected_revision):
                if state.in_flight is not None:
                    raise StoreError("disk full")
                super().save_state(state, expected_revision)

        service = self.build(FailingStore(self.state_root))
        result = self.launch(service=service)
        self.assertIs(result.action, LaunchAction.PASSTHROUGH)
        self.assertIn("disk full", result.reasons[0])
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertIs(self.phase(), Phase.TESTING_PROFILE)

    def test_concurrent_writer_gets_a_conflict_not_a_lost_update(self):
        self.learned()
        other = self.build()
        other.record_window(APP, PORTABLE, self.window())
        stale_revision = self.lane().value.revision - 1

        real = GameOptimizationStore(self.state_root)

        class StaleStore(GameOptimizationStore):
            """Hands the service the copy it read before the other writer."""

            def load_state(self, key):
                lookup = real.load_state(key)
                return dataclasses.replace(
                    lookup, value=dataclasses.replace(lookup.value, revision=stale_revision)
                )

            def save_state(self, state, expected_revision):
                real.save_state(state, expected_revision)

        before = self.lane().value
        stale = self.build(StaleStore(self.state_root))
        outcome = stale.record_window(APP, PORTABLE, self.window())
        self.assertFalse(outcome.ok)
        self.assertIn("revision", outcome.detail)
        self.assertEqual(self.lane().value, before)  # the other writer's change stands


class CorruptionTests(ServiceTestCase):
    def corrupt_lane(self):
        path = self.state_root / "optimization-state" / f"{LaneKey(APP, PORTABLE).identity}.json"
        path.write_bytes(b"{broken")

    def test_corrupt_lifecycle_writes_nothing_until_explicitly_reset(self):
        self.locked()
        written = self.path.read_bytes()
        self.corrupt_lane()
        result = self.launch()
        self.assertIs(result.action, LaunchAction.PASSTHROUGH)
        self.assertIn("untrusted", result.reasons[0])
        self.assertEqual(self.path.read_bytes(), written)
        self.assertFalse(self.service.record_window(APP, PORTABLE, self.window()).ok)
        self.assertTrue(self.service.reset_untrusted_lane(APP, PORTABLE).ok)
        self.assertIs(self.launch().phase, Phase.BASELINE)

    def test_corrupt_preferences_withhold_management_until_reset(self):
        self.locked()
        (self.state_root / "optimization-preferences.json").write_bytes(b"\x00")
        self.assertFalse(self.service.intent(APP).automatic)
        self.assertFalse(self.service.set_global(True).ok)
        written = self.path.read_bytes()
        self.launch()
        self.assertIs(self.phase(), Phase.OPTIMIZATION_DISABLED)
        self.assertEqual(self.path.read_bytes(), written)
        self.assertTrue(self.service.reset_untrusted_preferences().ok)
        self.assertFalse(self.service.intent(APP).automatic)  # reset means opted out
        self.assertTrue(self.service.set_global(True).ok)

    def test_catalog_entry_that_does_not_load_is_unsupported(self):
        (self.catalog_dir / f"{APP}.json").write_text(json.dumps(ofx.entry(extra=1)), encoding="utf-8")
        service = self.build()
        service.set_global(True)
        self.assertIs(self.launch(service=service).phase, Phase.UNSUPPORTED)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_unexpected_failure_is_contained_and_launch_proceeds(self):
        self.enable()

        def broken(registry):
            raise RuntimeError("adapter bug")

        service = GameOptimizationService(
            GameOptimizationStore(self.state_root),
            load_catalog(self.catalog_dir),
            ReviewedAdapters(),
            broken,
            allow_fixture_policy=True,
        )
        result = service.prepare_launch(APP, PORTABLE, IDLE, fx.GAME_BUILD, PERF)
        self.assertTrue(result.may_launch)
        self.assertIs(result.action, LaunchAction.PASSTHROUGH)
        self.assertIn("adapter bug", result.reasons[0])


class ReviewFindingTests(ServiceTestCase):
    """Primary review b5f4cbbc, each finding at the real dispatch path."""

    FG = FrameGenerationRef("fixture-provider", 2)

    def stage_fg(self):
        self.learned()
        plan = PerformancePlan(60, 30, Resolution(1280, 800), UpscalingMode.QUALITY, self.FG)
        self.assertTrue(self.propose(QueuedPlan("fg-60", BALANCED, plan)).ok)

    def test_frame_generation_is_withheld_unless_the_settings_landed(self):
        # Failed: the configuration is gone, so the engine cannot locate it.
        self.stage_fg()
        self.path.unlink()
        failed = self.launch()
        self.assertIs(failed.action, LaunchAction.NOT_LANDED)
        self.assertIsNotNone(failed.engine.frame_generation)  # the engine passed it through
        self.assertIsNone(failed.frame_generation)
        self.assertIsNone(failed.binding)

    def test_frame_generation_is_withheld_on_conflict_and_advisor(self):
        self.stage_fg()
        landed = self.launch()
        self.assertEqual(landed.frame_generation, self.FG)
        text = self.path.read_bytes().decode("utf-8").replace("sg.TextureQuality=2", "sg.TextureQuality=0")
        self.path.write_bytes(text.encode("utf-8"))
        conflict = self.launch()
        self.assertIs(conflict.engine.result, EngineResult.CONFLICT)
        self.assertIsNone(conflict.frame_generation)

    def test_frame_generation_is_withheld_when_the_file_is_locked(self):
        self.stage_fg()
        self.path.chmod(0o444)
        self.addCleanup(self.path.chmod, 0o644)
        advisor = self.launch()
        self.assertIs(advisor.engine.result, EngineResult.ADVISOR)
        self.assertIsNone(advisor.frame_generation)

    def test_performance_context_change_stops_a_locked_plan_being_redispatched(self):
        self.locked()
        written = self.path.read_bytes()
        moved = self.launch(perf=PerformanceContextRef("fixture-gpu-b.tv-4k"))
        self.assertIs(moved.action, LaunchAction.PASSTHROUGH)
        self.assertIs(moved.phase, Phase.NEEDS_REVALIDATION)
        self.assertIn("performance", moved.reasons[0])
        self.assertEqual(self.path.read_bytes(), written)

    def test_unknown_performance_context_withholds_everything(self):
        self.learned()
        self.propose(LIGHTER)
        result = self.launch(perf=None)
        self.assertIs(result.action, LaunchAction.PASSTHROUGH)
        self.assertIn("performance context is unknown", result.reasons[0])
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertIs(self.phase(), Phase.TESTING_PROFILE)  # still staged, not lost

    def test_late_window_from_an_earlier_launch_is_refused(self):
        self.validating()
        earlier = self.last.binding
        self.launch()  # the next launch re-checks the candidate
        late = self.service.record_window(APP, PORTABLE, self.window(binding=earlier))
        self.assertFalse(late.ok)
        self.assertIn("another launch", late.detail)
        self.assertEqual(self.lane().value.meets, 0)

    def test_window_for_another_plan_is_refused(self):
        self.validating()
        wrong = dataclasses.replace(self.last.binding, plan_id="someone-elses-plan")
        refused = self.service.record_window(APP, PORTABLE, self.window(binding=wrong))
        self.assertFalse(refused.ok)
        self.assertEqual(self.lane().value.meets, 0)

    def test_candidate_planned_for_a_stale_context_is_refused(self):
        self.learned()
        stale = dataclasses.replace(self.lane().value.context, game_version="fixture-build-6")
        outcome = self.service.propose(APP, PORTABLE, LIGHTER, stale)
        self.assertFalse(outcome.ok)
        self.assertIn("another context", outcome.detail)

    def test_partial_lane_cancellation_is_reported_and_reads_back_reconciled(self):
        self.learned()
        self.propose(LIGHTER)

        class FailingLanes(GameOptimizationStore):
            def save_state(self, state, expected_revision):
                raise StoreError("disk full")

        service = self.build(FailingLanes(self.state_root))
        outcome = service.set_global(False)
        self.assertFalse(outcome.ok)
        self.assertIn("preferences saved", outcome.detail)
        self.assertIn("disk full", outcome.detail)
        self.assertFalse(service.intent(APP).automatic)
        # Stored record still says testing; the readback does not.
        stored = GameOptimizationStore(self.state_root).load_state(LaneKey(APP, PORTABLE)).value
        self.assertIs(stored.phase, Phase.TESTING_PROFILE)
        self.assertIs(self.lane(service=service).value.phase, Phase.OPTIMIZATION_DISABLED)
        self.assertIs(self.launch(service=service).action, LaunchAction.PASSTHROUGH)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_unlistable_lanes_are_reported_not_hidden(self):
        class Unlistable(GameOptimizationStore):
            def lanes(self):
                raise StoreError("state directory unreadable")

        outcome = self.build(Unlistable(self.state_root)).set_global(True)
        self.assertFalse(outcome.ok)
        self.assertIn("unreadable", outcome.detail)

    def test_restore_with_nothing_to_restore_still_hands_the_game_back(self):
        self.enable()
        self.launch()  # baseline: nothing of ours was ever written
        outcome = self.service.restore_original(APP, PORTABLE, IDLE)
        self.assertEqual(outcome.result.name, "NOTHING_TO_RESTORE")
        self.assertIs(self.phase(), Phase.USER_OVERRIDE)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_placeholder_policy_is_refused_outside_fixtures(self):
        self.enable()
        service = GameOptimizationService(
            GameOptimizationStore(self.state_root),
            load_catalog(self.catalog_dir),
            ReviewedAdapters(),
            self.engine_factory,
        )
        result = service.prepare_launch(APP, PORTABLE, IDLE, fx.GAME_BUILD, PERF)
        self.assertIs(result.action, LaunchAction.PASSTHROUGH)
        self.assertIn("placeholder", result.reasons[0])
        self.assertIs(self.lane().state, LoadState.ABSENT)  # nothing was even read into a lane


class CatalogAdmissionTests(ServiceTestCase):
    def test_community_profile_is_advice_only(self):
        community = ofx.entry(
            validation="validated",
            provenance={"source": "community", "evidence_id": "c-1", "validated_modes": ["portable"]},
        )
        ofx.write_catalog(self.catalog_dir, community)
        service = self.build()
        service.set_global(True)
        result = self.launch(service=service)
        self.assertIs(result.phase, Phase.ADVISOR_ONLY)
        self.assertEqual(self.path.read_bytes(), self.original)


if __name__ == "__main__":
    unittest.main()
