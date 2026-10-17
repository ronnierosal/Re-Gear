"""Sanitized structural replay, not a recording of historical Mini inputs.

Saved evidence establishes attachment and connected/disabled external output.
It does not establish DMI, consent, current render selection or managed-session
readiness. Favorable values below are deliberately synthetic counterfactuals.
"""
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from test_automatic_dock import current
from regear.adapters.steamos.discovery import SteamOsDiscovery
from regear.adapters.steamos.host import HostRecord
from regear.application.automatic_dock import AutomaticDockCoordinator
from regear.application.connection_readiness import ConnectionReadinessStage, ConnectionReadinessStatus
from regear.delivery.automatic_dock_preferences import AutomaticDockPreferenceStore
from regear.domain.models import GameState, SupportTier
from regear.profiles.ally_x import match_ally_x
from regear.profiles.gpd_g1 import GpdG1Match
from regear.profiles.registry import resolve_runtime_profiles


class MiniHandoffAdmissionReplayTests(unittest.TestCase):
    def test_non_catalog_host_is_denied_despite_favorable_synthetic_inputs(self):
        # These are categorical synthetic non-catalog identities, not Mini DMI.
        for host in (HostRecord("fixture vendor", "fixture mini", "fixture board"),
                     HostRecord("", "", "")):
            with self.subTest(host=host):
                self.assertFalse(match_ally_x(host).exact)
        tier = SteamOsDiscovery._support_tier(
            "unknown", (), GpdG1Match(detected=True, verified=True)
        )
        self.assertIs(tier, SupportTier.UNKNOWN)
        observed = current("connected-internal.json")
        observed = replace(observed, snapshot=replace(
            observed.snapshot, host_profile="unknown", support_tier=tier))
        profiles = resolve_runtime_profiles(observed.snapshot)
        self.assertFalse(profiles.exact_host)
        self.assertFalse(profiles.exact_egpu)  # Combination tier is also required.
        decision = AutomaticDockCoordinator().update(
            enabled=True, current=observed,
            readiness=ConnectionReadinessStatus(
                ConnectionReadinessStage.READY_IDLE, "connection.ready_idle", 1000))
        self.assertFalse(decision.should_switch)
        self.assertEqual(decision.status.code, "automatic_dock.waiting_for_exact_g1")

    def test_host_gate_alone_denies_even_if_combination_tier_is_synthetic_certified(self):
        observed = current("connected-internal.json")
        observed = replace(observed, snapshot=replace(observed.snapshot, host_profile="unknown"))
        self.assertTrue(resolve_runtime_profiles(observed.snapshot).exact_egpu)
        decision = AutomaticDockCoordinator().update(
            enabled=True, current=observed,
            readiness=ConnectionReadinessStatus(
                ConnectionReadinessStage.READY_IDLE, "connection.ready_idle", 1000))
        self.assertFalse(decision.should_switch)

    def test_supported_control_dispatches_once_and_retains_disabled_and_game_guards(self):
        observed = current("connected-internal.json")
        ready = ConnectionReadinessStatus(ConnectionReadinessStage.READY_IDLE, "connection.ready_idle", 1000)
        coordinator = AutomaticDockCoordinator()
        self.assertTrue(coordinator.update(enabled=True, current=observed, readiness=ready).should_switch)
        self.assertFalse(coordinator.update(enabled=True, current=observed, readiness=ready).should_switch)
        disabled = AutomaticDockCoordinator().update(enabled=False, current=observed, readiness=ready)
        self.assertEqual(disabled.status.code, "automatic_dock.disabled")
        self.assertFalse(disabled.should_switch)
        running = replace(observed, snapshot=replace(observed.snapshot, game_state=GameState.RUNNING))
        held = AutomaticDockCoordinator().update(enabled=True, current=running,
            readiness=ConnectionReadinessStatus(ConnectionReadinessStage.GAME_RUNNING, "connection.game_running", 1000))
        self.assertFalse(held.should_switch)

    def test_missing_stored_opt_in_is_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIs(AutomaticDockPreferenceStore(Path(directory).resolve()).load(), False)


if __name__ == "__main__":
    unittest.main()
