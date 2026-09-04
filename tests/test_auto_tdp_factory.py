import unittest
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import test_auto_tdp_session as session_fixtures
import test_tdp_control as control_fixtures
import test_tdp_sensor_readiness as sensor_fixtures
from hdm.adapters.steamos.gamescope_performance import PerformanceReading, PerformanceTarget
from hdm.adapters.steamos.auto_tdp_host import AutoTdpHostContext
from hdm.adapters.steamos.gamescope_performance_target import PerformanceTargetResolution
from hdm.application.tdp_control import TdpControlService
from hdm.delivery.auto_tdp_evidence import AutoTdpEligibility
from hdm.delivery.auto_tdp_factory import AutoTdpSessionFactory
from hdm.delivery.auto_tdp_benchmark import benchmark_auto_tdp
from hdm.domain.auto_tdp import AutoTdpPolicy
from hdm.domain.models import GameState
from hdm.domain.telemetry import TelemetryCollectionContract, TelemetryConsumer, TelemetryMetric


class AutoFactoryTests(unittest.TestCase):
    def setUp(self):
        fixture = sensor_fixtures.TdpSensorReadinessTests()
        fixture.setUp()
        self.now = 0.0
        self.reads = 0
        self.game = GameState.RUNNING
        self.internal = True
        self.host_key = "a" * 64
        self.target = PerformanceTarget(Path(__file__).resolve(), 1000, 123, 456, "game", 789)
        # All timing and thermal values are synthetic fixture inputs.
        self.contract = TelemetryCollectionContract(TelemetryConsumer.AUTO_TDP,
            (TelemetryMetric.FPS, TelemetryMetric.TEMPERATURE_C), 1000, 5, True)
        self.args = dict(resolve=lambda: PerformanceTargetResolution("performance.target_resolved", self.target),
            eligibility=lambda: AutoTdpEligibility(self.game, self.internal),
            sensor_config=fixture.config, contract=self.contract, clock=lambda: self.now,
            host_context_key=self.host_key, thermal_evidence_reference="synthetic-fixture-only",
            host_context=lambda reading: AutoTdpHostContext("auto_tdp.host_context_observed", self.host_key),
            performance_reader=SimpleNamespace(observe=self.frame),
            sensors=lambda: replace(fixture.inventory, started_at=self.now, finished_at=self.now))
        self.journal = control_fixtures.MemoryJournal()
        self.provider = session_fixtures.GuardedProvider(self.journal)
        self.service = TdpControlService(self.provider, self.journal, wait=lambda _: None)
        self.policy = AutoTdpPolicy(7, 30, 60)

    def frame(self, target):
        self.reads += 1
        return PerformanceReading("performance.observed", target.context_key, int(self.now * 1000), 22_222_222)

    def create(self, **changes):
        return AutoTdpSessionFactory(**(self.args | changes))(self.service, self.provider)

    def feed(self, session, start, end):
        for second in range(start, end + 1):
            self.now = float(second)
            result = session.tick()
        return result

    def test_construction_and_disabled_ticks_perform_no_reads_or_writes(self):
        session = self.create()
        self.assertFalse(session.enabled)
        session.tick()
        self.assertEqual(self.reads, 0)
        self.assertEqual(self.provider.writes, [])

    def test_factory_benchmark_uses_real_window_without_creating_a_session_or_writer(self):
        evidence = AutoTdpSessionFactory(**self.args).create_evidence(self.provider)
        def advance(seconds):
            self.now += seconds
            return False
        result = benchmark_auto_tdp(evidence, cancel=threading.Event(),
                                   clock=lambda: self.now, wait=advance)
        self.assertEqual(result.code, "auto_tdp.benchmark_within_budget")
        self.assertEqual(result.usable_samples, 8)
        self.assertEqual(self.provider.writes, [])
        self.assertIsNone(self.journal.record)

    def test_composed_samples_drive_verified_transaction_then_rewarm(self):
        session = self.create()
        session.start(self.policy)
        result = self.feed(session, 0, 11)
        self.assertEqual(result.transaction.state, "applied")
        self.assertEqual(self.provider.writes, [16])
        self.assertEqual(self.journal.record.baseline.sustained.current, 15)
        self.assertEqual(self.feed(session, 12, 15).code, "auto_tdp.sample_unavailable")
        self.assertEqual(self.provider.writes, [16])

    def test_late_loss_of_render_eligibility_prevents_dispatch(self):
        session = self.create()
        session.start(self.policy)
        self.provider.before_dispatch = lambda: setattr(self, "internal", False)
        result = self.feed(session, 0, 11)
        self.assertEqual(result.transaction.code, "tdp.dispatch_rejected")
        self.assertEqual(self.provider.writes, [])
        self.assertIsNone(self.journal.record)

    def test_restart_discards_previous_frame_window(self):
        session = self.create()
        session.start(self.policy)
        self.feed(session, 0, 4)
        session.stop()
        session.start(self.policy)
        self.assertEqual(self.feed(session, 5, 8).code, "auto_tdp.sample_unavailable")
        self.assertEqual(self.feed(session, 9, 9).code, "auto_tdp.context_settling")

    def test_unbenchmarked_or_expensive_contract_cannot_start_collection(self):
        for contract in (replace(self.contract, benchmarked=False),
                         replace(self.contract, measured_collection_cost_ms=11)):
            session = self.create(contract=contract)
            self.assertFalse(session.start(self.policy).enabled)
            session.tick()
            self.assertEqual(self.reads, 0)

    def test_incompatible_contracts_and_missing_sensor_policy_rejected(self):
        for change in (dict(contract=replace(self.contract, consumer=TelemetryConsumer.HEALTH)),
                       dict(contract=replace(self.contract, metrics=(TelemetryMetric.TEMPERATURE_C,))),
                       dict(contract=replace(self.contract, interval_ms=2000)),
                       dict(host_context_key=""), dict(thermal_evidence_reference=""),
                       dict(sensor_config=None)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.create(**change)

    def test_changed_host_configuration_blocks_collection_and_pending_dispatch(self):
        session = self.create()
        session.start(self.policy)
        self.provider.before_dispatch = lambda: setattr(self, "host_key", "b" * 64)
        result = self.feed(session, 0, 11)
        self.assertEqual(result.transaction.code, "tdp.dispatch_rejected")
        self.assertEqual(self.provider.writes, [])
        self.assertIsNone(self.journal.record)
        reads = self.reads
        self.assertEqual(self.feed(session, 12, 12).code, "auto_tdp.sample_unavailable")
        self.assertEqual(self.reads, reads)
