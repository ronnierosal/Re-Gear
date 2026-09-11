"""The RPC surface for releasing the session when the link never trains.

Two things are tested here that the service tests cannot reach: that the
plugin keeps ONE service so its latch survives, and that the destructive call
re-checks the offer against a fresh reading instead of trusting whatever the
panel was showing when somebody pressed the button.
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


if __name__ == "__main__":
    unittest.main()
