import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from hdm.adapters.steamos.offline_steam_details import project_steam_app_details
from hdm.application.offline_details import classify_minimized_steam_details
from hdm.domain.models import GameState
from test_main_process_delivery import load_main_module


OBSERVED = {
    "iInstallFolder": 0, "eDisplayStatus": 19, "eCloudStatus": 1,
    "bCloudAvailable": False, "bCloudEnabledForAccount": True,
    "bCloudEnabledForApp": False, "bIsThirdPartyUpdater": False,
}


class OfflineDetailsDeliveryTests(unittest.TestCase):
    def classify(self, details, state=GameState.IDLE):
        return classify_minimized_steam_details(
            details, game_state=state, project_details=project_steam_app_details,
        )

    def test_observed_native_callback_reports_update_only(self):
        self.assertEqual(self.classify(OBSERVED), {
            "schema_version": 1, "status": "needs_attention",
            "reason_codes": ["update_pending"],
        })

    def test_invalid_and_identity_fields_reject_without_echo(self):
        for data in [None, [], "private", {"appid": 123}, {"path": "/private"},
                     OBSERVED | {"title": "private"}, {"eDisplayStatus": True},
                     {"eDisplayStatus": "19"}, {"eCloudStatus": None},
                     {"iInstallFolder": 2**100}, {"bCloudAvailable": 1}]:
            with self.subTest(data=data):
                self.assertEqual(self.classify(data), {
                    "schema_version": 1, "status": "unknown",
                    "reason_codes": ["offline_evidence_unavailable"],
                })

    def test_gate_precedes_projection(self):
        project = Mock(side_effect=AssertionError("must not project"))
        for state, reason in [(GameState.RUNNING, "offline_evidence_game_active"),
                              (GameState.UNKNOWN, "offline_evidence_game_unknown"),
                              ("idle", "offline_evidence_game_unknown")]:
            self.assertEqual(classify_minimized_steam_details(
                OBSERVED, game_state=state, project_details=project,
            )["reason_codes"], [reason])
        project.assert_not_called()

    def test_favorable_fields_do_not_prove_offline_readiness(self):
        result = self.classify(OBSERVED | {
            "eDisplayStatus": 0, "eCloudStatus": 3,
            "bCloudAvailable": True, "bCloudEnabledForApp": True,
        })
        self.assertEqual(result["status"], "unknown")
        self.assertIn("steam_entitlement_unknown", result["reason_codes"])
        self.assertEqual(self.classify({})["status"], "unknown")

    def test_rpc_reads_only_diagnostics_and_never_starts_plugin_lifecycle(self):
        module = load_main_module()
        plugin = object.__new__(module.Plugin)
        plugin._api = SimpleNamespace(get_snapshot_report=Mock(return_value=
            SimpleNamespace(snapshot=SimpleNamespace(game_state=GameState.IDLE))))
        plugin.get_snapshot = Mock(side_effect=AssertionError("lifecycle"))
        result = asyncio.run(plugin.classify_offline_details(OBSERVED))
        self.assertEqual(result["reason_codes"], ["update_pending"])
        plugin._api.get_snapshot_report.assert_called_once_with()
        plugin.get_snapshot.assert_not_called()
        plugin._api.get_snapshot_report.side_effect = RuntimeError("private error")
        self.assertEqual(asyncio.run(plugin.classify_offline_details(OBSERVED)), {
            "schema_version": 1, "status": "unknown",
            "reason_codes": ["offline_evidence_game_unknown"],
        })


if __name__ == "__main__":
    unittest.main()
