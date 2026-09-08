import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from hdm.adapters.steamos.offline_steam_details import project_steam_app_details
from hdm.domain.offline_readiness import (
    CloudSaveState, DownloadState, InstallState, OfflineReadinessStatus,
    classify_offline_readiness, offline_readiness_to_public_dict,
)


class SteamDetailsTests(unittest.TestCase):
    def test_redacted_shape_observed_on_ally_reports_update_without_cloud_claim(self):
        evidence = project_steam_app_details({
            "iInstallFolder": 0, "eDisplayStatus": 19, "eCloudStatus": 1,
            "bCloudAvailable": False, "bCloudEnabledForAccount": True,
            "bCloudEnabledForApp": False, "bIsThirdPartyUpdater": False,
        })
        self.assertEqual(evidence.download, DownloadState.PENDING_UPDATE)
        self.assertEqual(evidence.cloud_save, CloudSaveState.UNKNOWN)
        self.assertEqual(evidence.install, InstallState.UNKNOWN)
        self.assertEqual(offline_readiness_to_public_dict(classify_offline_readiness(evidence)),
                         {"schema_version": 1, "status": "needs_attention",
                          "reason_codes": ["update_pending"]})

    def test_install_license_and_cloud_blockers_are_explained(self):
        for fields, status, reason in [
            ({"eDisplayStatus": 9}, "needs_attention", "game_not_installed"),
            ({"eDisplayStatus": 10, "iInstallFolder": -1}, "needs_attention", "game_not_installed"),
            ({"eDisplayStatus": 26}, "online_check_needed", "steam_authorization_required"),
            ({"eDisplayStatus": 27}, "online_check_needed", "steam_authorization_required"),
            ({"eCloudStatus": 8}, "needs_attention", "cloud_save_failed"),
            ({"eDisplayStatus": 34}, "needs_attention", "cloud_save_failed"),
            ({"eDisplayStatus": 35}, "needs_attention", "cloud_save_failed"),
        ]:
            with self.subTest(fields=fields):
                result = offline_readiness_to_public_dict(classify_offline_readiness(project_steam_app_details(fields)))
                self.assertEqual(result["status"], status)
                self.assertIn(reason, result["reason_codes"])
        self.assertEqual(project_steam_app_details({"eDisplayStatus": 9, "iInstallFolder": 0}).install, InstallState.UNKNOWN)
        evidence = project_steam_app_details({"eDisplayStatus": 27, "bIsThirdPartyUpdater": True})
        self.assertEqual(len(evidence.online_check_requirements), 2)

    def test_sync_requires_affirmative_consistent_cloud_fields(self):
        fields = dict(eCloudStatus=3, bCloudAvailable=True,
                      bCloudEnabledForAccount=True, bCloudEnabledForApp=True)
        self.assertEqual(project_steam_app_details(fields).cloud_save, CloudSaveState.SYNCED)
        for key in ("bCloudAvailable", "bCloudEnabledForAccount", "bCloudEnabledForApp"):
            for value in (False, None, 1, "true"):
                self.assertEqual(project_steam_app_details(fields | {key: value}).cloud_save,
                                 CloudSaveState.UNKNOWN)

    def test_favorable_details_cannot_prove_offline_readiness(self):
        evidence = project_steam_app_details(dict(iInstallFolder=0, eDisplayStatus=11,
            eCloudStatus=3, bCloudAvailable=True, bCloudEnabledForAccount=True,
            bCloudEnabledForApp=True, bIsSubscribedTo=True))
        self.assertEqual(classify_offline_readiness(evidence).status, OfflineReadinessStatus.UNKNOWN)

    def test_private_and_malformed_values_do_not_leak_or_become_positive(self):
        evidence = project_steam_app_details(dict(iInstallFolder="0", eDisplayStatus="19",
            eCloudStatus=True, strDisplayName="private", account="private"))
        self.assertEqual(evidence.download, DownloadState.UNKNOWN)
        self.assertEqual(evidence.cloud_save, CloudSaveState.UNKNOWN)
        self.assertNotIn("private", repr(evidence))
        self.assertEqual(project_steam_app_details({"iInstallFolder": -1}).install,
                         InstallState.NOT_INSTALLED)


if __name__ == "__main__":
    unittest.main()
