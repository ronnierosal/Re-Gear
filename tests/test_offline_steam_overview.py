"""Synthetic upstream-shape tests, not evidence of a live Steam client."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from hdm.adapters.steamos.offline_steam_overview import project_local_steam_overview
from hdm.domain.offline_readiness import (
    CloudSaveState, DownloadState, InstallState, OfflineReadinessEvidence,
    OfflineReadinessStatus, classify_offline_readiness,
    offline_readiness_to_public_dict,
)


def overview(**local_changes):
    return {
        "appid": 123, "app_type": 1, "display_name": "private title",
        "owner_account_id": 999,
        "local_per_client_data": {
            "installed": True, "display_status": 11, "cloud_status": 3,
            "is_available_on_current_platform": True,
            "client_name": "private hostname", **local_changes,
        },
    }


class OfflineSteamOverviewTests(unittest.TestCase):
    def project(self, value):
        return project_local_steam_overview(value, expected_app_id=123)

    def test_favorable_overview_never_proves_offline_readiness(self):
        evidence = self.project(overview())
        self.assertEqual(evidence.install, InstallState.INSTALLED)
        self.assertEqual(evidence.cloud_save, CloudSaveState.SYNCED)
        self.assertEqual(evidence.download, DownloadState.UNKNOWN)
        result = classify_offline_readiness(evidence)
        self.assertEqual(result.status, OfflineReadinessStatus.UNKNOWN)
        self.assertIn("steam_entitlement_unknown", result.reason_codes)

    def test_explicit_update_and_download_blockers(self):
        for states, expected in [
            ([6, 18, 19, 20, 21, 39], DownloadState.PENDING_UPDATE),
            ([3, 7, 22, 23, 24, 25, 38], DownloadState.PENDING_DOWNLOAD),
        ]:
            for state in states:
                with self.subTest(state=state):
                    evidence = self.project(overview(display_status=state))
                    self.assertEqual(evidence.download, expected)
                    self.assertEqual(classify_offline_readiness(evidence).status,
                                     OfflineReadinessStatus.NEEDS_ATTENTION)

    def test_cloud_conflict_pending_and_unknown_are_distinct(self):
        for state, expected in [
            (9, CloudSaveState.CONFLICT),
            *[(s, CloudSaveState.PENDING) for s in [4, 5, 6, 7, 10]],
            *[(s, CloudSaveState.UNKNOWN) for s in [0, 1, 2, 8, 11, "3", True, None]],
        ]:
            with self.subTest(state=state):
                self.assertEqual(self.project(overview(cloud_status=state)).cloud_save,
                                 expected)

    def test_remote_install_does_not_substitute_for_local(self):
        value = overview(installed=False)
        value["selected_per_client_data"] = {"installed": True, "cloud_status": 3}
        value["most_available_per_client_data"] = value["selected_per_client_data"]
        self.assertEqual(self.project(value).install, InstallState.NOT_INSTALLED)
        del value["local_per_client_data"]
        self.assertEqual(self.project(value), OfflineReadinessEvidence())

    def test_wrong_game_shortcuts_and_malformed_records_fail_closed(self):
        for value in [None, [], {}, {**overview(), "appid": 124},
                      {**overview(), "appid": "123"},
                      {**overview(), "app_type": 1073741824},
                      {**overview(), "app_type": True},
                      {**overview(), "local_per_client_data": []}]:
            with self.subTest(value=value):
                self.assertEqual(self.project(value), OfflineReadinessEvidence())
        for app_id in [True, 0, -1, 2**32, "123"]:
            self.assertEqual(project_local_steam_overview(overview(), expected_app_id=app_id),
                             OfflineReadinessEvidence())

    def test_missing_and_coerced_fields_are_not_positive_evidence(self):
        for value in [1, "true", None]:
            self.assertEqual(self.project(overview(installed=value)).install,
                             InstallState.UNKNOWN)
        for value in [True, "6", 999, None]:
            self.assertEqual(self.project(overview(display_status=value)).download,
                             DownloadState.UNKNOWN)
        for fields in [{"is_available_on_current_platform": None},
                       {"is_invalid_os_type": True},
                       {"streaming_to_local_client": True},
                       {"streaming_to_local_client": "false"}]:
            self.assertEqual(self.project(overview(**fields)), OfflineReadinessEvidence())

    def test_identity_is_not_retained_or_serialized(self):
        value = overview(cloud_status=9)
        evidence = self.project(value)
        public = offline_readiness_to_public_dict(classify_offline_readiness(evidence))
        self.assertEqual(public, {"schema_version": 1, "status": "needs_attention",
                                  "reason_codes": ["cloud_save_conflict"]})
        self.assertNotIn("private", repr(evidence))
        self.assertEqual(value["display_name"], "private title")


if __name__ == "__main__":
    unittest.main()
