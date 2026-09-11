"""The RPC surface for bouncing the session when the link never trains.

Three things are tested here that the service tests cannot reach: that the
plugin keeps ONE service so its latch survives, that the destructive call
re-checks the offer against a fresh reading instead of trusting whatever the
panel was showing when somebody pressed the button, and that the strategy the
caller names is the one that runs -- including the rung that is not built,
which must be refused before anything is observed or touched.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from tests.test_main_process_delivery import load_main_module  # noqa: E402
from regear.application.connection_readiness import (  # noqa: E402
    ConnectionReadinessObservation,
    ConnectionReadinessStage,
    ConnectionReadinessStatus,
)
from regear.application.link_recovery import (  # noqa: E402
    LinkRecoveryOutcome,
    LinkRecoveryStrategy,
)
from regear.domain.link_training_recovery import (  # noqa: E402
    LinkRecoveryAssessment,
    LinkRecoveryAvailability,
)
from regear.domain.models import GameState  # noqa: E402


def observation(**overrides) -> ConnectionReadinessObservation:
    """The measured failure: dock there, PCI never completed, nothing running."""
    facts = {
        "sample_id": "sample-1",
        "transport_present": True,
        # The observation refuses a present transport with no identity, which
        # is the right invariant: "something is plugged in" is not a fact
        # without saying what.
        "transport_identity": "opaque-transport-1",
        "pci_complete": False,
        "game_state": GameState.IDLE,
    }
    facts.update(overrides)
    return ConnectionReadinessObservation(**facts)


def status(stage=ConnectionReadinessStage.TIMED_OUT) -> ConnectionReadinessStatus:
    return ConnectionReadinessStatus(
        stage=stage, code="connection.readiness_timed_out", poll_after_ms=1000
    )


class LinkRecoveryRpcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_main_module()

    def plugin(self, *, stage=ConnectionReadinessStage.TIMED_OUT, obs=None):
        plugin = self.module.Plugin.__new__(self.module.Plugin)
        plugin._link_recovery = None
        plugin._last_readiness_observation = observation() if obs is None else obs
        plugin._connection_readiness = type(
            "Readiness", (), {"status": staticmethod(lambda: status(stage))}
        )()
        return plugin

    # -- the pollable half ---------------------------------------------------

    def test_offers_recovery_in_the_measured_failure_state(self):
        plugin = self.plugin()
        with patch.object(self.module, "UserServiceCommandRunner"):
            result = asyncio.run(plugin.get_link_recovery_status())
        self.assertTrue(result["offered"])
        self.assertEqual(result["code"], "link_recovery.available")
        self.assertEqual(result["availability"], "offered")

    def test_a_complete_link_is_not_offered_recovery(self):
        plugin = self.plugin(obs=observation(pci_complete=True))
        with patch.object(self.module, "UserServiceCommandRunner"):
            result = asyncio.run(plugin.get_link_recovery_status())
        self.assertFalse(result["offered"])
        self.assertEqual(result["code"], "link_recovery.pci_complete")

    def test_a_readiness_window_still_open_is_not_offered_recovery(self):
        plugin = self.plugin(stage=ConnectionReadinessStage.WAITING_FOR_PCI)
        with patch.object(self.module, "UserServiceCommandRunner"):
            result = asyncio.run(plugin.get_link_recovery_status())
        self.assertEqual(result["code"], "link_recovery.readiness_not_exhausted")

    def test_no_observation_yet_is_answered_not_crashed(self):
        plugin = self.plugin()
        plugin._last_readiness_observation = None
        result = asyncio.run(plugin.get_link_recovery_status())
        self.assertFalse(result["offered"])
        self.assertEqual(result["code"], "link_recovery.no_observation")

    def test_asking_never_touches_the_command_runner(self):
        """It is pollable, so it must not shell out or probe hardware."""
        plugin = self.plugin()
        with patch.object(self.module, "UserServiceCommandRunner") as runner:
            asyncio.run(plugin.get_link_recovery_status())
        runner.return_value.run.assert_not_called()

    # -- the destructive half ------------------------------------------------

    def test_it_refuses_without_an_exact_true_confirmation(self):
        plugin = self.plugin()
        for value in (False, None, 0, "", "yes", 1):
            with self.subTest(confirm=value):
                result = asyncio.run(plugin.execute_link_recovery(confirm=value))
                self.assertFalse(result["ok"])
                self.assertEqual(
                    result["code"], "link_recovery.confirmation_required"
                )

    def test_it_refuses_by_default(self):
        plugin = self.plugin()
        result = asyncio.run(plugin.execute_link_recovery())
        self.assertEqual(result["code"], "link_recovery.confirmation_required")

    def test_a_game_started_after_the_offer_refuses_at_confirmation(self):
        """The panel's offer is stale; the fresh reading is what counts."""
        plugin = self.plugin()
        plugin._discovery = object()
        started = observation(game_state=GameState.RUNNING)

        async def observe_readiness(_current):
            plugin._last_readiness_observation = started
            return status()

        plugin._observe_connection_readiness = observe_readiness
        with patch.object(self.module, "SnapshotTransitionObservationAdapter"), \
             patch.object(self.module, "UserServiceCommandRunner") as runner:
            result = asyncio.run(plugin.execute_link_recovery(confirm=True))
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "link_recovery.game_running")
        runner.return_value.run.assert_not_called()

    def test_an_unobservable_device_refuses_rather_than_acting_blind(self):
        plugin = self.plugin()
        plugin._discovery = object()
        with patch.object(
            self.module,
            "SnapshotTransitionObservationAdapter",
            side_effect=OSError("no device"),
        ), patch.object(self.module, "UserServiceCommandRunner") as runner:
            result = asyncio.run(plugin.execute_link_recovery(confirm=True))
        self.assertEqual(result["code"], "link_recovery.observation_unavailable")
        runner.return_value.run.assert_not_called()

    # -- the latch has to survive ------------------------------------------

    def test_the_service_is_built_once_so_its_latch_persists(self):
        """A per-call service would arrive with a fresh latch every time."""
        plugin = self.plugin()
        with patch.object(self.module, "UserServiceCommandRunner"):
            first = plugin._link_recovery_service()
            second = plugin._link_recovery_service()
        self.assertIs(first, second)

    def test_the_loop_rearms_the_latch_when_the_egpu_goes_away(self):
        plugin = self.plugin()
        with patch.object(self.module, "UserServiceCommandRunner"):
            service = plugin._link_recovery_service()
            service._attempted = True
            service.observe_transport(True)
            self.assertTrue(service.attempted)
            service.observe_transport(False)
            self.assertFalse(service.attempted)


class RecordingService:
    """Stands in for the real service to record which rung it was asked for."""

    def __init__(self) -> None:
        self.default_strategy = LinkRecoveryStrategy.SESSION_RESTART
        self.asked_for: list[object] = []

    def assess(self, **_facts) -> LinkRecoveryAssessment:
        return LinkRecoveryAssessment(
            LinkRecoveryAvailability.OFFERED, "link_recovery.available"
        )

    def observe_transport(self, present: bool) -> None:
        pass

    def recover(self, _user, *, strategy=None) -> LinkRecoveryOutcome:
        self.asked_for.append(strategy)
        return LinkRecoveryOutcome(
            True,
            "link_recovery.trained",
            seconds=1.0,
            strategy=getattr(strategy, "value", ""),
        )


class LinkRecoveryStrategySelectionTests(unittest.TestCase):
    """Which mechanism runs is the caller's choice, and it is not guessed."""

    @classmethod
    def setUpClass(cls):
        cls.module = load_main_module()

    def plugin(self):
        plugin = self.module.Plugin.__new__(self.module.Plugin)
        plugin._link_recovery = None
        plugin._last_readiness_observation = observation()
        plugin._connection_readiness = type(
            "Readiness", (), {"status": staticmethod(status)}
        )()
        return plugin

    def executable(self):
        """A plugin wired far enough to reach `recover`, with a fake service."""
        plugin = self.plugin()
        service = RecordingService()
        plugin._link_recovery = service
        plugin._discovery = object()
        plugin._append_journey_event = lambda **_kwargs: None

        async def observe_readiness(_current):
            return status()

        plugin._observe_connection_readiness = observe_readiness
        return plugin, service

    def run_execute(self, plugin, **kwargs):
        resolution = type("Resolution", (), {"ok": True, "context": object()})()
        with patch.object(self.module, "SnapshotTransitionObservationAdapter"), \
             patch.object(self.module, "GamescopeDiscovery"), \
             patch.object(
                 self.module, "resolve_gamescope_user", return_value=resolution
             ):
            return asyncio.run(plugin.execute_link_recovery(**kwargs))

    def test_the_status_reports_the_default_and_every_known_rung(self):
        plugin = self.plugin()
        with patch.object(self.module, "UserServiceCommandRunner"):
            result = asyncio.run(plugin.get_link_recovery_status())
        self.assertEqual(result["default_strategy"], "session_restart")
        named = {row["strategy"]: row["implemented"] for row in result["strategies"]}
        self.assertEqual(
            named,
            {
                "session_restart": True,
                "session_stop_start": True,
                "desktop_round_trip": False,
            },
        )

    def test_omitting_the_strategy_runs_the_plain_bounce(self):
        plugin, service = self.executable()
        result = self.run_execute(plugin, confirm=True)
        self.assertEqual(service.asked_for, [LinkRecoveryStrategy.SESSION_RESTART])
        self.assertEqual(result["strategy"], "session_restart")

    def test_concurrent_confirmed_rpcs_issue_only_one_restart(self):
        from threading import Barrier
        from tests.test_link_recovery_service import FakeCommands, USER, RESTART, service

        plugin, _ = self.executable()
        commands = FakeCommands()
        plugin._link_recovery, _ = service(commands, [True])
        barrier = Barrier(2)

        def resolve(_scan):
            # Both RPCs have passed assessment before either reaches recover.
            barrier.wait(timeout=5)
            return type("Resolution", (), {"ok": True, "context": USER})()

        async def concurrent():
            return await asyncio.gather(
                plugin.execute_link_recovery(confirm=True),
                plugin.execute_link_recovery(confirm=True),
            )

        with patch.object(self.module, "SnapshotTransitionObservationAdapter"), \
             patch.object(self.module, "GamescopeDiscovery"), \
             patch.object(self.module, "resolve_gamescope_user", side_effect=resolve):
            results = asyncio.run(concurrent())
        self.assertCountEqual([row["code"] for row in results], [
            "link_recovery.trained", "link_recovery.already_attempted",
        ])
        self.assertEqual(commands.calls, [RESTART])

    def test_a_named_rung_is_the_one_that_runs(self):
        plugin, service = self.executable()
        result = self.run_execute(
            plugin, confirm=True, strategy="session_stop_start"
        )
        self.assertEqual(service.asked_for, [LinkRecoveryStrategy.SESSION_STOP_START])
        self.assertEqual(result["strategy"], "session_stop_start")

    def test_the_desktop_round_trip_refuses_before_anything_is_observed(self):
        """Rung 3 is named, not built. It must not reach hardware to say so."""
        plugin = self.plugin()
        with patch.object(self.module, "UserServiceCommandRunner") as runner, \
             patch.object(
                 self.module, "SnapshotTransitionObservationAdapter"
             ) as observations:
            result = asyncio.run(
                plugin.execute_link_recovery(
                    confirm=True, strategy="desktop_round_trip"
                )
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "link_recovery.strategy_not_implemented")
        self.assertEqual(result["strategy"], "desktop_round_trip")
        self.assertTrue(result["session_restored"])
        observations.assert_not_called()
        runner.return_value.run.assert_not_called()

    def test_an_unknown_rung_refuses_rather_than_falling_back(self):
        plugin = self.plugin()
        with patch.object(self.module, "UserServiceCommandRunner") as runner, \
             patch.object(
                 self.module, "SnapshotTransitionObservationAdapter"
             ) as observations:
            result = asyncio.run(
                plugin.execute_link_recovery(confirm=True, strategy="reboot_it")
            )
        self.assertEqual(result["code"], "link_recovery.strategy_unknown")
        observations.assert_not_called()
        runner.return_value.run.assert_not_called()

    def test_the_confirmation_still_outranks_the_strategy(self):
        plugin = self.plugin()
        result = asyncio.run(
            plugin.execute_link_recovery(strategy="session_stop_start")
        )
        self.assertEqual(result["code"], "link_recovery.confirmation_required")


class AutomaticRecoveryIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_main_module()

    def test_fresh_guarded_recovery_and_separate_consent(self):
        from types import SimpleNamespace as NS
        from regear.application.automatic_link_recovery import AutomaticLinkRecovery
        from tests.test_link_recovery_service import FakeCommands, USER, RESTART, service

        for fresh_idle, consent, journal_idle in [(True, True, True), (False, True, True), (True, False, True), (True, True, False)]:
            with self.subTest(fresh_idle=fresh_idle, consent=consent, journal_idle=journal_idle):
                plugin = self.module.Plugin.__new__(self.module.Plugin)
                plugin._unloading = False
                plugin._discovery = object()
                plugin._last_readiness_observation = observation(transport_identity="transport:known")
                policy = plugin._automatic_link_recovery = AutomaticLinkRecovery()
                facts = dict(absent=False, present=True, identity="transport:known", pci_complete=False, enabled=True, idle=True)
                policy.observe(now=0, **{**facts,"absent":True,"present":False})
                policy.observe(now=1, **facts)
                plugin._automatic_recovery_preferences = lambda: NS(load=lambda: consent)
                plugin._automatic_dock_preferences = lambda: NS(load=lambda: True)
                plugin._transition_journal_service = lambda: NS(status=lambda: NS(durable=True,owner=NS(value="none" if journal_idle else "presentation")))
                gpus=(NS(role=self.module.GpuRole.INTERNAL,present=True,confidence=self.module.Confidence.VERIFIED),)
                current = NS(snapshot=NS(game_state=GameState.IDLE,gamescope=NS(running=True),gpus=gpus))
                fresh = NS(snapshot=NS(game_state=GameState.IDLE if fresh_idle else GameState.RUNNING,gamescope=NS(running=True),gpus=gpus))
                async def observe(_): return status()
                async def background(fn): return fn()
                plugin._observe_connection_readiness = observe
                plugin._run_background_operation = background
                plugin._append_journey_event = lambda **kwargs: None
                commands = FakeCommands()
                plugin._link_recovery, _ = service(commands, [True])
                with patch.object(self.module.time, "monotonic", return_value=11), \
                     patch.object(self.module,"resolve_runtime_profiles",return_value=NS(exact_host=True)), \
                     patch.object(self.module,"GamescopeDiscovery"), \
                     patch.object(self.module,"resolve_gamescope_user",return_value=NS(ok=True,context=USER)), \
                     patch.object(self.module,"SnapshotTransitionObservationAdapter") as adapter:
                    adapter.return_value.observe.return_value=fresh
                    result=asyncio.run(plugin._maybe_automatic_link_recovery(current,True))
                self.assertEqual(result, fresh_idle and consent and journal_idle)
                self.assertEqual(commands.calls,[RESTART] if result else [])

    def test_enabling_requires_explicit_boolean_confirmation(self):
        plugin = self.module.Plugin.__new__(self.module.Plugin)
        for confirm in [False, None, 1, "true"]:
            result=asyncio.run(plugin.set_automatic_dock_enabled(True,confirm,True))
            self.assertIn(result['code'],['automatic_dock.confirmation_required','automatic_dock.request_invalid'])


if __name__ == "__main__":
    unittest.main()
