import inspect
import time
import unittest
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import test_auto_tdp_session as session_fixtures
import test_tdp_control as control_fixtures
import test_tdp_sensor_readiness as sensor_fixtures
from regear.adapters.steamos.gamescope_performance import PerformanceReading, PerformanceTarget
from regear.adapters.steamos.auto_tdp_host import AutoTdpHostContext
from regear.adapters.steamos.gamescope_performance_target import PerformanceTargetResolution
from regear.application.tdp_control import TdpControlService
from regear.delivery.auto_tdp_evidence import AutoTdpEligibility
from regear.delivery import auto_tdp_factory
from regear.delivery.auto_tdp_factory import AutoTdpSessionFactory
from regear.delivery.auto_tdp_benchmark import benchmark_auto_tdp
from regear.domain.auto_tdp import AutoTdpPolicy
from regear.domain.models import GameState
from regear.domain.telemetry import TelemetryCollectionContract, TelemetryConsumer, TelemetryMetric


class AutoFactoryTests(unittest.TestCase):
    def setUp(self):
        fixture = sensor_fixtures.TdpSensorReadinessTests()
        fixture.setUp()
        self.inventory = fixture.inventory
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

    def test_the_default_session_clock_keeps_counting_across_a_suspend(self):
        """Every staleness guard is measured on this clock, so it must see sleep.

        CLOCK_MONOTONIC stops while the handheld is suspended, so an arbitrarily
        long sleep between two samples is indistinguishable from the ordinary
        one-second cadence: the sample_gap guard never fires and a pre-suspend
        streak survives to authorise a post-resume write. This repository already
        depends on that distinction elsewhere -- domain/relaunch_intent.py records
        which clock an intent is aged against, and main.py reads CLOCK_BOOTTIME
        for exactly this reason.
        """
        default = inspect.signature(AutoTdpSessionFactory.__init__).parameters["clock"].default
        suspended = SimpleNamespace(CLOCK_BOOTTIME=7, monotonic=lambda: 10.0,
                                    clock_gettime=lambda which: 40_000.0 if which == 7 else 0.0)
        with mock.patch.object(auto_tdp_factory, "time", suspended):
            self.assertEqual(default(), 40_000.0)

    def test_the_default_session_clock_falls_back_where_boottime_is_absent(self):
        """A platform without CLOCK_BOOTTIME still gets a usable monotonic clock."""
        default = inspect.signature(AutoTdpSessionFactory.__init__).parameters["clock"].default
        for absent in (SimpleNamespace(monotonic=lambda: 10.0),
                       SimpleNamespace(CLOCK_BOOTTIME=7, monotonic=lambda: 10.0,
                                       clock_gettime=mock.Mock(side_effect=OSError))):
            with self.subTest(absent=absent), mock.patch.object(auto_tdp_factory, "time", absent):
                self.assertEqual(default(), 10.0)

    def test_a_suspend_between_samples_does_not_let_the_pre_suspend_streak_write(self):
        """Sleeping mid-streak discards the old evidence instead of completing a quorum.

        The control arm writes on the very next sample, so the suspend arm cannot
        pass vacuously: the only difference between them is the sleep.

        The control arm is also the defect it guards against. On a clock that
        stops during suspend, the tick after an eight-hour sleep reads as second
        11 -- indistinguishable from the control -- so the pre-suspend streak
        completes its quorum and writes. Only a clock that counts through the
        sleep reaches the second arm at all.
        """
        session = self.create()
        session.start(self.policy)
        self.feed(session, 0, 10)
        self.assertEqual(self.provider.writes, [])
        self.now = 11.0
        self.assertEqual(session.tick().transaction.state, "applied")
        self.assertEqual(self.provider.writes, [16])

        self.setUp()
        session = self.create()
        session.start(self.policy)
        self.feed(session, 0, 10)
        self.assertEqual(self.provider.writes, [])
        self.now = 10.0 + 8 * 3600
        self.assertEqual(session.tick().code, "auto_tdp.sample_unavailable")
        self.assertEqual(self.provider.writes, [])
        self.assertIsNone(self.journal.record)

    def test_a_resumed_session_settles_again_before_it_may_write(self):
        """Detected evidence loss earns a fresh settling window, not an immediate write."""
        session = self.create()
        session.start(self.policy)
        self.feed(session, 0, 10)
        self.now = 10.0 + 8 * 3600
        session.tick()
        codes = []
        for extra in range(1, 6):
            self.now = 10.0 + 8 * 3600 + extra
            codes.append(session.tick().code)
        self.assertEqual(codes, ["auto_tdp.sample_unavailable"] * 3
                         + ["auto_tdp.context_settling", "auto_tdp.settling"])
        self.assertEqual(self.provider.writes, [])

    def _suspendable_composition(self):
        """A session built exactly as production builds it: no injected clock.

        The frame and sensor timestamps are read from whichever clock the
        composition actually selected, so the arms below differ only by the
        sleep and never by a mismatched fake epoch.
        """
        selected = inspect.signature(AutoTdpSessionFactory.__init__).parameters["clock"].default
        elapsed = SimpleNamespace(awake=0.0, slept=0.0)
        module_time = SimpleNamespace(
            CLOCK_BOOTTIME=7,
            monotonic=lambda: elapsed.awake,
            clock_gettime=lambda which: elapsed.awake + elapsed.slept if which == 7 else elapsed.awake,
        )
        patcher = mock.patch.object(auto_tdp_factory, "time", module_time)
        patcher.start()
        self.addCleanup(patcher.stop)

        def frame(target):
            self.reads += 1
            return PerformanceReading("performance.observed", target.context_key,
                                      int(selected() * 1000), 22_222_222)

        args = {key: value for key, value in self.args.items() if key != "clock"}
        args["performance_reader"] = SimpleNamespace(observe=frame)
        args["sensors"] = lambda: replace(self.inventory, started_at=selected(),
                                          finished_at=selected())
        session = AutoTdpSessionFactory(**args)(self.service, self.provider)

        def run(*, awake=1.0, slept=0.0):
            elapsed.awake += awake
            elapsed.slept += slept
            return session.tick()

        return session, run

    def test_the_default_clock_composition_rejects_a_pre_suspend_streak(self):
        """End-to-end on the production default clock, with no injected fixture clock.

        The awake arm must still reach its first verified write on the ordinary
        cadence. The sleep arm differs only by eight hours of suspend, which the
        production clock has to see; on a clock that stops during suspend the two
        arms are the same tick and the pre-suspend streak writes.
        """
        session, run = self._suspendable_composition()
        session.start(self.policy)
        awake_codes = [run().code for _ in range(12)]
        self.assertEqual(self.provider.writes, [16], awake_codes)

        self.setUp()
        session, run = self._suspendable_composition()
        session.start(self.policy)
        for _ in range(11):
            run()
        self.assertEqual(self.provider.writes, [])
        self.assertEqual(run(slept=8 * 3600).code, "auto_tdp.sample_unavailable")
        self.assertEqual(self.provider.writes, [])
        self.assertIsNone(self.journal.record)
        self.assertEqual([run().code for _ in range(5)],
                         ["auto_tdp.sample_unavailable"] * 3
                         + ["auto_tdp.context_settling", "auto_tdp.settling"])
        self.assertEqual(self.provider.writes, [])
