"""Durable preferences and lifecycle state: reopen, corruption, conflicts."""

from __future__ import annotations

import dataclasses
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.delivery.game_optimization_store import (  # noqa: E402
    MAX_QUARANTINED,
    MAX_STATE_BYTES,
    PREFERENCES_FILENAME,
    QUARANTINE_DIRECTORY,
    GameOptimizationStore,
    LoadState,
    StateConflict,
)
from regear.domain.game_optimization_preferences import (  # noqa: E402
    GameChoice,
    GamePreference,
    OptimizationPreferences,
)
from regear.domain.game_optimization_state import (  # noqa: E402
    DispatchKind,
    InFlight,
    LaneKey,
    LearningPolicy,
    ObservationWindow,
    OptimizationContext,
    PerformanceContextRef,
    Phase,
    QueuedPlan,
    WindowVerdict,
    assess,
    begin_dispatch,
    current_binding,
    initial,
    launched,
    next_dispatch,
    observe,
    propose,
)
from regear.domain.graphics_profiles import SupportTier  # noqa: E402
from regear.domain.mode_profiles import ExperienceTarget  # noqa: E402
from regear.domain.models import OperatingMode  # noqa: E402
from regear.domain.performance_plan import FrameGenerationRef, PerformancePlan  # noqa: E402
from regear.domain.semantic_profiles import InternalRender, Resolution, UpscalingMode  # noqa: E402

APP = "4000000002"
KEY = LaneKey(APP, OperatingMode.PORTABLE)
TV_KEY = LaneKey(APP, OperatingMode.TV_DOCKED)
POLICY = LearningPolicy()
BALANCED = ExperienceTarget.BALANCED
CONTEXT = OptimizationContext(
    BALANCED, "build-7", 1, 1, "schema-v5", PerformanceContextRef("fixture-gpu-a", 2)
)
PLAN = PerformancePlan.from_v1(
    target_display_fps=60,
    base_fps_target=30,
    resolution=Resolution(1280, 800),
    upscaling=UpscalingMode.QUALITY,
    frame_generation=FrameGenerationRef("fixture-provider", 2),
    source="fixture",
)


def rich_state():
    """A staged candidate with a full plan and some history: most fields set."""
    state = launched(assess(initial(KEY), SupportTier.MANAGED, CONTEXT, POLICY))
    for qualified in [True] * POLICY.learning_windows + [False]:
        window = ObservationWindow(current_binding(state), qualified, WindowVerdict.MEETS_TARGET)
        state = observe(state, window, POLICY)
    return propose(state, QueuedPlan("candidate-a", BALANCED, PLAN), CONTEXT, POLICY).state


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "state"
        self.store = GameOptimizationStore(self.root)

    def reopen(self):
        return GameOptimizationStore(self.root)

    def state_file(self, key=KEY):
        return self.root / "optimization-state" / f"{key.identity}.json"


class PreferenceStoreTests(StoreTestCase):
    def test_absent_is_not_untrusted(self):
        self.assertIs(self.store.load_preferences().state, LoadState.ABSENT)

    def test_round_trip_survives_reopen(self):
        prefs = (
            OptimizationPreferences()
            .with_global(True)
            .with_game(APP, GamePreference(GameChoice.MANUAL, ExperienceTarget.QUALITY))
        )
        self.store.save_preferences(OptimizationPreferences().with_global(True), 0)
        self.store.save_preferences(prefs, 1)
        loaded = self.reopen().load_preferences()
        self.assertTrue(loaded.trusted)
        self.assertEqual(loaded.value, prefs)

    def test_stale_writer_cannot_undo_a_change_it_has_not_seen(self):
        first = OptimizationPreferences().with_global(True)
        self.store.save_preferences(first, 0)
        stale = OptimizationPreferences().with_game(APP, GamePreference(GameChoice.MANUAL))
        with self.assertRaises(StateConflict):
            self.store.save_preferences(stale, 0)
        self.assertTrue(self.store.load_preferences().value.global_enabled)

    def test_one_malformed_game_makes_the_whole_record_untrusted(self):
        prefs = OptimizationPreferences(True).with_game(APP, GamePreference(GameChoice.MANUAL))
        self.store.save_preferences(prefs, 0)
        path = self.root / PREFERENCES_FILENAME
        value = json.loads(path.read_text(encoding="utf-8"))
        value["games"][APP]["choice"] = "sometimes"
        path.write_text(json.dumps(value), encoding="utf-8")
        # Dropping only that entry would silently re-enable management there.
        self.assertIs(self.store.load_preferences().state, LoadState.UNTRUSTED)

    def test_untrusted_preferences_refuse_writes_until_quarantined(self):
        (self.root).mkdir(parents=True)
        (self.root / PREFERENCES_FILENAME).write_bytes(b"{not json")
        with self.assertRaises(StateConflict):
            self.store.save_preferences(OptimizationPreferences().with_global(True), 0)
        self.assertTrue(self.store.quarantine_preferences())
        self.assertIs(self.store.load_preferences().state, LoadState.ABSENT)
        self.assertEqual(len(list((self.root / QUARANTINE_DIRECTORY).iterdir())), 1)
        self.store.save_preferences(OptimizationPreferences().with_global(True), 0)

    def test_trusted_preferences_are_never_quarantined(self):
        self.store.save_preferences(OptimizationPreferences().with_global(True), 0)
        self.assertFalse(self.store.quarantine_preferences())
        self.assertTrue(self.store.load_preferences().trusted)


class StateStoreTests(StoreTestCase):
    def test_round_trip_keeps_every_field(self):
        state = rich_state()
        self.store.save_state(state, 0)
        loaded = self.reopen().load_state(KEY)
        self.assertTrue(loaded.trusted)
        self.assertEqual(loaded.value, state)

    def test_in_flight_marker_survives_reopen(self):
        state = rich_state()
        self.store.save_state(state, 0)
        marked = begin_dispatch(state, next_dispatch(state))
        self.store.save_state(marked, state.revision)
        loaded = self.reopen().load_state(KEY).value
        self.assertEqual(loaded.in_flight, InFlight(DispatchKind.APPLY_CANDIDATE, "candidate-a"))

    def test_lanes_are_independent_and_listed(self):
        self.store.save_state(rich_state(), 0)
        tv = assess(initial(TV_KEY), SupportTier.ADVISOR, CONTEXT, POLICY)
        self.store.save_state(tv, 0)
        self.assertEqual(set(self.store.lanes()), {KEY, TV_KEY})
        self.assertIs(self.store.load_state(TV_KEY).value.phase, Phase.ADVISOR_ONLY)
        self.assertIs(self.store.load_state(KEY).value.phase, Phase.TESTING_PROFILE)

    def test_revision_conflict_is_refused_and_leaves_the_record(self):
        state = rich_state()
        self.store.save_state(state, 0)
        with self.assertRaises(StateConflict):
            self.store.save_state(dataclasses.replace(state, revision=state.revision + 1), 0)
        with self.assertRaises(StateConflict):
            self.store.save_state(state, state.revision)  # does not advance
        self.assertEqual(self.store.load_state(KEY).value, state)

    def test_leftover_temporary_file_from_a_crash_is_ignored(self):
        state = rich_state()
        self.store.save_state(state, 0)
        (self.state_file().parent / f".{self.state_file().name}.dead.tmp").write_bytes(b"{half")
        self.assertEqual(self.reopen().load_state(KEY).value, state)
        self.assertEqual(self.reopen().lanes(), (KEY,))

    def corrupt(self, raw: bytes):
        self.store.save_state(rich_state(), 0)
        self.state_file().write_bytes(raw)
        return self.store.load_state(KEY)

    def test_corruption_is_untrusted_never_absent(self):
        good = self.state_file
        cases = {
            "truncated": b'{"record_version":1,',
            "not json": b"\x00\xff",
            "wrong version": json.dumps({"record_version": 99}).encode(),
            "oversized": b" " * (MAX_STATE_BYTES + 1),
            "missing field": json.dumps({"record_version": 1, "steam_app_id": APP}).encode(),
        }
        for name, raw in cases.items():
            with self.subTest(name):
                self.state_file().unlink(missing_ok=True)
                self.assertIs(self.corrupt(raw).state, LoadState.UNTRUSTED)
        self.assertTrue(good().exists())

    def test_record_for_another_lane_is_untrusted(self):
        self.store.save_state(rich_state(), 0)
        tv_path = self.state_file(TV_KEY)
        tv_path.write_bytes(self.state_file().read_bytes())
        self.assertIs(self.store.load_state(TV_KEY).state, LoadState.UNTRUSTED)

    def test_inconsistent_record_is_untrusted(self):
        self.store.save_state(rich_state(), 0)
        value = json.loads(self.state_file().read_text(encoding="utf-8"))
        value["phase"] = "baseline"  # a candidate outside testing
        self.state_file().write_text(json.dumps(value), encoding="utf-8")
        self.assertIs(self.store.load_state(KEY).state, LoadState.UNTRUSTED)

    def stored_plan(self, plan_value):
        """Write a staged-candidate record whose plan is ``plan_value``, then read it."""
        self.store.save_state(rich_state(), 0)
        value = json.loads(self.state_file().read_text(encoding="utf-8"))
        value["candidate"]["plan"] = plan_value
        self.state_file().write_text(json.dumps(value), encoding="utf-8")
        return self.store.load_state(KEY)

    def test_v2_plan_round_trips_every_field(self):
        plan = PerformancePlan(
            requested_display_fps=90, target_display_fps=60, base_fps_target=30,
            game_output_resolution=Resolution(1920, 1080),
            internal_render=Resolution(1440, 810),
            display_output_resolution=Resolution(3840, 2160),
            upscaling=UpscalingMode.QUALITY,
            frame_generation=FrameGenerationRef("fixture-provider", 2), source="rec-1@3",
        )
        state = dataclasses.replace(rich_state(), candidate=QueuedPlan("candidate-a", BALANCED, plan))
        self.store.save_state(state, 0)
        self.assertEqual(self.reopen().load_state(KEY).value.candidate.plan, plan)
        for internal in (InternalRender.DYNAMIC, InternalRender.UNKNOWN):
            with self.subTest(internal):
                other = dataclasses.replace(plan, internal_render=internal)
                self.state_file().unlink()
                self.store.save_state(dataclasses.replace(
                    state, candidate=QueuedPlan("candidate-a", BALANCED, other)), 0)
                self.assertIs(self.store.load_state(KEY).value.candidate.plan.internal_render, internal)

    def test_stored_v1_plan_is_read_only_through_the_deterministic_migration(self):
        loaded = self.stored_plan({
            "plan_version": 1, "target_display_fps": 60, "base_fps_target": 30,
            "resolution": [1920, 1080], "upscaling": "quality",
            "frame_generation": {"provider_id": "fixture-provider", "multiplier": 2},
            "source": "old",
        })
        self.assertTrue(loaded.trusted, loaded.detail)
        plan = loaded.value.candidate.plan
        self.assertEqual(plan, PerformancePlan.from_v1(
            60, 30, Resolution(1920, 1080), UpscalingMode.QUALITY,
            FrameGenerationRef("fixture-provider", 2), "old"))
        self.assertIs(plan.internal_render, InternalRender.UNKNOWN)
        self.assertIsNone(plan.requested_display_fps)

    def test_ambiguous_or_mixed_plan_records_are_untrusted(self):
        v2 = {
            "plan_version": 2, "requested_display_fps": 60, "target_display_fps": 60,
            "base_fps_target": 60, "game_output_resolution": [1920, 1080],
            "internal_render": "unknown", "display_output_resolution": None,
            "upscaling": None, "frame_generation": None, "source": "",
        }
        cases = {
            "v2 missing internal render": {k: v for k, v in v2.items() if k != "internal_render"},
            "v2 using the v1 field": {**{k: v for k, v in v2.items() if k != "game_output_resolution"},
                                      "resolution": [1920, 1080]},
            "v2 selecting above the request": {**v2, "requested_display_fps": 45},
            "unknown internal token": {**v2, "internal_render": "auto"},
            "v1 missing its resolution field": {
                "plan_version": 1, "target_display_fps": 60, "base_fps_target": 60,
                "upscaling": None, "frame_generation": None, "source": ""},
        }
        for name, value in cases.items():
            with self.subTest(name):
                self.state_file().unlink(missing_ok=True)
                self.assertIs(self.stored_plan(value).state, LoadState.UNTRUSTED)

    def test_queued_plan_from_a_future_contract_is_untrusted(self):
        self.store.save_state(rich_state(), 0)
        value = json.loads(self.state_file().read_text(encoding="utf-8"))
        value["candidate"]["plan"]["plan_version"] = 3
        self.state_file().write_text(json.dumps(value), encoding="utf-8")
        self.assertIs(self.store.load_state(KEY).state, LoadState.UNTRUSTED)

    def test_untrusted_state_refuses_writes_until_quarantined_explicitly(self):
        self.corrupt(b"garbage")
        with self.assertRaises(StateConflict):
            self.store.save_state(rich_state(), 0)
        self.assertTrue(self.store.quarantine(KEY))
        self.assertIs(self.store.load_state(KEY).state, LoadState.ABSENT)
        self.store.save_state(rich_state(), 0)
        self.assertFalse(self.store.quarantine(KEY))  # trusted: refused

    def test_quarantine_keeps_a_bounded_number_of_records(self):
        for _ in range(MAX_QUARANTINED + 2):
            self.state_file().parent.mkdir(parents=True, exist_ok=True)
            self.state_file().write_bytes(b"garbage")
            self.assertTrue(self.store.quarantine(KEY))
        kept = [p for p in (self.root / QUARANTINE_DIRECTORY).iterdir()
                if p.name.startswith(KEY.identity)]
        self.assertEqual(len(kept), MAX_QUARANTINED)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_symlinked_record_is_untrusted_and_never_replaced(self):
        outside = self.root.parent / "elsewhere.json"
        outside.write_text("{}", encoding="utf-8")
        self.state_file().parent.mkdir(parents=True)
        try:
            os.symlink(outside, self.state_file())
        except OSError:
            self.skipTest("symlink creation is not permitted here")
        self.assertIs(self.store.load_state(KEY).state, LoadState.UNTRUSTED)
        with self.assertRaises(StateConflict):
            self.store.save_state(rich_state(), 0)
        self.assertEqual(outside.read_text(encoding="utf-8"), "{}")

    def test_relative_root_is_refused(self):
        with self.assertRaises(ValueError):
            GameOptimizationStore(Path("relative"))


if __name__ == "__main__":
    unittest.main()
