import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import test_tdp_control as control_fixtures
import test_tdp_sensor_readiness as sensor_fixtures
from hdm.adapters.steamos.gamescope_performance import PerformanceReading, PerformanceTarget
from hdm.adapters.steamos.gamescope_performance_target import PerformanceTargetResolution
from hdm.adapters.steamos.tdp_sensors import SensorField
from hdm.delivery.auto_tdp_evidence import AutoTdpEligibility, AutoTdpEvidenceCollector
from hdm.delivery.game_frame_collector import FrameCollection, GameFrameCollector
from hdm.domain.models import GameState


class Frames:
    def __init__(self):
        self.resets = 0
        self.calls = 0
        self.after = lambda: None
        self.result = FrameCollection("frames.estimated", "workload", 55.0, 10500, 5, 4000)

    def collect(self):
        self.calls += 1
        self.after()
        return self.result

    def reset(self):
        self.resets += 1


class AutoEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = sensor_fixtures.TdpSensorReadinessTests()
        self.fixture.setUp()
        self.inventory = self.fixture.inventory
        self.now = 11.0
        self.provider = control_fixtures.Provider(control_fixtures.MemoryJournal())
        self.frames = Frames()
        self.target = PerformanceTarget(Path(__file__).resolve(), 1000, 123, 456, "workload", 789)
        self.eligibility = AutoTdpEligibility(GameState.RUNNING, True)
        self.collector = AutoTdpEvidenceCollector(provider=self.provider, frames=self.frames,
            resolve=lambda: PerformanceTargetResolution("performance.target_resolved", self.target),
            sensors=lambda: self.inventory, eligibility=lambda: self.eligibility,
            sensor_config=self.fixture.config, clock=lambda: self.now, maximum_frame_age_ms=2000)

    def test_collection_preserves_frame_timestamp_and_revalidation_does_not_query_frames(self):
        evidence = self.collector.collect()
        self.assertEqual(evidence.observation.sampled_at_ms, 10500)
        self.assertEqual(evidence.observation.configured_watts, 15)
        live = self.collector.revalidate()
        self.assertEqual(live.workload_key, evidence.observation.context_key)
        self.assertEqual(live.reading, evidence.reading)
        self.assertEqual(self.frames.calls, 1)

    def test_lost_game_render_or_provider_ownership_rejects_valid_numbers(self):
        self.collector.collect()
        for state in (AutoTdpEligibility(GameState.RUNNING, False), AutoTdpEligibility(GameState.UNKNOWN, True)):
            self.eligibility = state
            self.assertIsNone(self.collector.collect())
            self.assertIsNone(self.collector.revalidate())
        self.eligibility = AutoTdpEligibility(GameState.RUNNING, True)
        self.provider.code = "tdp.ownership_unverified"
        self.assertIsNone(self.collector.collect())
        self.assertIsNone(self.collector.revalidate())
        self.assertEqual(self.frames.calls, 1)

    def test_readback_or_target_changes_during_frame_collection_discard_window(self):
        self.frames.after = lambda: setattr(self.provider, "current", control_fixtures.reading(16, 16, 16))
        self.assertIsNone(self.collector.collect())
        self.assertEqual(self.frames.resets, 2)
        self.setUp()
        self.frames.after = lambda: setattr(self, "target", replace(self.target, process_start_ticks=790))
        self.assertIsNone(self.collector.collect())
        self.assertEqual(self.frames.resets, 2)

    def test_power_source_change_changes_dispatch_identity_and_resets_history(self):
        before = self.collector.collect()
        self.inventory = replace(self.inventory, power_supplies=(
            replace(self.fixture.battery, status=SensorField("observed", "discharging")),
            replace(self.fixture.external, online=SensorField("observed", "offline"))))
        self.assertNotEqual(self.collector.revalidate().workload_key, before.observation.context_key)
        after = self.collector.collect()
        self.assertNotEqual(after.observation.context_key, before.observation.context_key)
        self.assertEqual(self.frames.resets, 3)

    def test_setting_or_provider_restart_resets_frame_history(self):
        self.collector.collect()
        self.collector.collect()
        self.assertEqual(self.frames.resets, 1)
        self.provider.current = control_fixtures.reading(16, 16, 16)
        self.collector.collect()
        self.provider.current = replace(self.provider.current, binding="restarted")
        self.collector.collect()
        self.assertEqual(self.frames.resets, 3)

    def test_sensors_age_out_during_provider_read(self):
        original = self.provider.observe
        def slow_read():
            self.now = 13.0
            return original()
        self.provider.observe = slow_read
        self.assertIsNone(self.collector.collect())
        self.assertIsNone(self.collector.revalidate())
        self.assertEqual(self.frames.calls, 0)

    def test_thermal_ceiling_and_unknown_power_reject_at_dispatch(self):
        self.assertIsNotNone(self.collector.collect())
        channel = replace(self.fixture.channel, celsius=SensorField("observed", 80.0))
        self.inventory = replace(self.inventory, temperatures=(replace(self.fixture.thermal, channels=(channel,)),))
        self.assertIsNone(self.collector.revalidate())
        self.inventory = replace(self.fixture.inventory, power_supplies=())
        self.assertIsNone(self.collector.revalidate())

    def test_stale_future_nonfinite_and_mismatched_frames_are_rejected(self):
        for frame in (replace(self.frames.result, newest_received_at_ms=8000),
                      replace(self.frames.result, newest_received_at_ms=12000),
                      replace(self.frames.result, sampled_fps=float("nan")),
                      replace(self.frames.result, code="frames.unavailable"),
                      replace(self.frames.result, context_key="another-game")):
            self.frames.result = frame
            self.assertIsNone(self.collector.collect())

    def test_warmup_is_preserved_but_explicit_reset_discards_epoch(self):
        self.frames.result = FrameCollection("frames.warming", "workload")
        self.assertIsNone(self.collector.collect())
        self.assertIsNone(self.collector.collect())
        self.assertEqual(self.frames.resets, 1)
        self.collector.reset()
        self.assertEqual(self.frames.resets, 2)

    def test_context_change_during_warmup_discards_retained_samples(self):
        self.frames.result = FrameCollection("frames.warming", "workload")
        self.frames.after = lambda: setattr(self.provider, "current", control_fixtures.reading(16, 16, 16))
        self.assertIsNone(self.collector.collect())
        self.assertEqual(self.frames.resets, 2)

    def test_reader_failures_return_no_evidence(self):
        def fail():
            raise OSError("private details")
        self.provider.observe = fail
        self.assertIsNone(self.collector.collect())
        self.assertIsNone(self.collector.revalidate())

    def test_real_frame_window_rewarms_after_verified_power_change(self):
        self.collector._sensors = lambda: replace(self.inventory, started_at=self.now - 0.1, finished_at=self.now)
        self.collector._frames = GameFrameCollector(resolve=self.collector._resolve,
            reader=SimpleNamespace(observe=lambda target: PerformanceReading(
                "performance.observed", target.context_key, int(self.now * 1000), 20_000_000)),
            clock=lambda: self.now)
        for _ in range(4):
            self.assertIsNone(self.collector.collect())
            self.now += 1
        self.assertEqual(self.collector.collect().observation.fps, 50)
        self.provider.current = control_fixtures.reading(16, 16, 16)
        for _ in range(4):
            self.now += 1
            self.assertIsNone(self.collector.collect())
        self.now += 1
        self.assertEqual(self.collector.collect().observation.configured_watts, 16)
