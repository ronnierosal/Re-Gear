import unittest
from dataclasses import replace

from test_tdp_control import MemoryJournal, Provider
from hdm.application.auto_tdp_session import AutoTdpEvidence, AutoTdpLiveContext, AutoTdpSession
from hdm.application.tdp_control import TdpControlService
from hdm.domain.auto_tdp import AutoTdpObservation, AutoTdpPolicy
from hdm.domain.models import GameState
from hdm.domain.telemetry import TelemetryCollectionContract, TelemetryConsumer, TelemetryMetric
from hdm.ports.tdp import TdpWriteOutcome


class GuardedProvider(Provider):
    before_dispatch = lambda self: None

    def set_limit(self, expected, watts, *, dispatch_guard=None):
        self.before_dispatch()
        if dispatch_guard is not None and dispatch_guard() is not True:
            return TdpWriteOutcome(False, False, "tdp.dispatch_rejected")
        return super().set_limit(expected, watts)


class AutoSessionTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.fps = 45
        self.game = GameState.RUNNING
        self.workload = "game-generation"
        self.ready = True
        self.collections = 0
        self.journal = MemoryJournal()
        self.provider = GuardedProvider(self.journal)
        self.service = TdpControlService(self.provider, self.journal, wait=lambda _: None)
        self.contract = TelemetryCollectionContract(TelemetryConsumer.AUTO_TDP, (TelemetryMetric.FPS,), 1000, 5, True)
        self.session = AutoTdpSession(service=self.service, collect=self.collect,
            revalidate=self.revalidate, game_state=lambda: self.game,
            clock_ms=lambda: self.now, contract=self.contract)
        self.policy = AutoTdpPolicy(7, 30, 60)

    def collect(self):
        self.collections += 1
        observation = AutoTdpObservation(self.workload, self.now, self.fps, self.provider.current.sustained.current,
                                        self.game, True, True, self.ready, self.ready)
        return AutoTdpEvidence(observation, self.provider.current)

    def revalidate(self):
        if not self.ready or self.game is not GameState.RUNNING:
            return None
        return AutoTdpLiveContext(self.workload, self.provider.current)

    def feed(self, last):
        result = None
        for at in range(0, last + 1, 1000):
            self.now = at
            result = self.session.tick()
        return result

    def test_disabled_session_never_collects_or_writes(self):
        self.assertEqual(self.session.tick().code, "auto_tdp.disabled")
        self.assertEqual(self.collections, 0)
        self.assertEqual(self.provider.writes, [])

    def test_restart_and_game_admission_loss_reset_collection_history(self):
        resets = []
        self.session._reset_collection = lambda: resets.append(True)
        self.session.start(self.policy)
        self.session.tick()
        self.game = GameState.UNKNOWN
        self.now += 1000
        self.session.tick()
        self.session.stop()
        self.session.start(self.policy)
        self.assertEqual(len(resets), 3)

    def test_fast_ticks_do_not_exceed_declared_collection_interval(self):
        self.session.start(self.policy)
        self.session.tick()
        for at in (0, 1, 500, 999):
            self.now = at
            self.assertEqual(self.session.tick().code, "auto_tdp.waiting_interval")
        self.assertEqual(self.collections, 1)
        self.now = 1000
        self.session.tick()
        self.assertEqual(self.collections, 2)

    def test_provider_restart_discards_old_policy_streak(self):
        self.session.start(self.policy)
        self.feed(6000)
        self.provider.current = replace(self.provider.current, binding="restarted-owner")
        self.now = 7000
        self.assertEqual(self.session.tick().code, "auto_tdp.context_settling")
        self.assertEqual(self.provider.writes, [])

    def test_missed_target_drives_shared_verified_adjustment_and_preserves_baseline(self):
        self.session.start(self.policy)
        result = self.feed(7000)
        self.assertEqual(result.transaction.state, "applied")
        self.assertEqual(result.proposed_watts, 16)
        self.assertEqual(self.provider.writes, [16])
        self.assertEqual(self.journal.record.baseline.sustained.current, 15)
        self.now = 8000
        self.assertEqual(self.session.tick().code, "auto_tdp.settling")
        self.session.stop()
        self.assertEqual(self.service.restore().state, "restored")
        self.assertEqual(self.provider.writes, [16, 15])

    def test_stable_target_probes_down_through_same_service(self):
        self.fps = 60
        self.session.start(self.policy)
        result = self.feed(9000)
        self.assertEqual(result.transaction.state, "applied")
        self.assertEqual(self.provider.current.values, (14, 15, 15))

    def test_known_idle_unknown_or_unready_samples_never_adjust(self):
        self.session.start(self.policy)
        for game in (GameState.IDLE, GameState.UNKNOWN):
            self.game = game
            for _ in range(11):
                result = self.session.tick()
                self.assertEqual(result.code, "telemetry.auto_tdp_game_not_running")
                self.assertTrue(result.enabled)
                self.now += 1000
        self.assertEqual(self.collections, 0)
        self.game = GameState.RUNNING
        self.ready = False
        for _ in range(11):
            result = self.session.tick()
            self.assertEqual(result.code, "auto_tdp.thermal_unverified")
            self.assertTrue(result.enabled)
            self.now += 1000
        self.assertEqual(self.collections, 11)
        self.assertEqual(self.provider.writes, [])

    def test_stop_during_provider_work_prevents_dispatch_without_pending_journal(self):
        self.session.start(self.policy)
        self.provider.before_dispatch = self.session.stop
        result = self.feed(7000)
        self.assertEqual(result.code, "tdp.dispatch_rejected")
        self.assertFalse(result.enabled)
        self.assertEqual(self.provider.writes, [])
        self.assertIsNone(self.journal.record)

    def test_game_change_or_expiry_during_provider_work_prevents_dispatch(self):
        for change in (lambda: setattr(self, "workload", "new-game"), lambda: setattr(self, "now", self.now + 2001)):
            self.session.start(self.policy)
            self.provider.before_dispatch = change
            self.assertEqual(self.feed(7000).code, "tdp.dispatch_rejected")
            self.assertEqual(self.provider.writes, [])
            self.assertIsNone(self.journal.record)

    def test_uncertain_write_stops_session_and_preserves_recovery(self):
        self.session.start(self.policy)
        self.provider.behavior = "timeout"
        result = self.feed(7000)
        self.assertEqual(result.transaction.state, "recovery_required")
        self.assertFalse(self.session.enabled)
        self.assertEqual(self.journal.record.phase, "pending")
        self.assertEqual(self.session.tick().code, "auto_tdp.disabled")
        self.assertEqual(self.provider.writes, [16])

    def test_unbenchmarked_collection_cannot_start(self):
        self.session._contract = replace(self.contract, benchmarked=False)
        self.assertFalse(self.session.start(self.policy).enabled)
        self.assertEqual(self.collections, 0)

    def test_bad_collector_stops_without_dispatch(self):
        self.session.start(self.policy)
        def fail():
            raise OSError("private process details")
        self.session._collect = fail
        self.assertEqual(self.session.tick().code, "auto_tdp.session_unavailable")
        self.assertFalse(self.session.enabled)
        self.assertEqual(self.provider.writes, [])
