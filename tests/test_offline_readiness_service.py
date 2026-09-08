from dataclasses import replace
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from hdm.adapters.steamos.offline_steam_overview import project_local_steam_overview
from hdm.application.offline_readiness import (
    OfflineCheckContext, OfflineCheckSample, OfflineReadinessService,
)
from hdm.domain.models import GameState
from hdm.domain.offline_readiness import (
    OfflineEvidenceCollectionContract, OfflineEvidenceSourceDeclaration,
    OfflineEvidenceSourceKind, OfflineEvidenceField, OfflineReadinessObservation,
    OfflineReadinessEvidence, InstallState, DownloadState, CloudSaveState,
    SteamEntitlementState,
)


class OfflineReadinessServiceTests(unittest.TestCase):
    def setUp(self):
        self.context = OfflineCheckContext(1, GameState.IDLE)
        self.declaration = OfflineEvidenceSourceDeclaration(
            OfflineEvidenceSourceKind.LOCAL_STEAM_METADATA, True, False, False,
            True, (OfflineEvidenceField.INSTALL, OfflineEvidenceField.DOWNLOAD,
                   OfflineEvidenceField.CLOUD_SAVE),
        )
        self.contract = OfflineEvidenceCollectionContract(
            True, True, True, 1_000, 20, True, 1_000,
        )
        self.time = 1_000
        self.reads = 0
        self.sample = OfflineCheckSample(self.context, OfflineReadinessObservation(
            1_000, project_local_steam_overview({
                "appid": 123, "app_type": 1,
                "local_per_client_data": {"installed": True,
                    "is_available_on_current_platform": True,
                    "display_status": 20, "cloud_status": 9},
                "display_name": "PRIVATE GAME",
            }, expected_app_id=123),
        ))

    def read(self, context):
        self.reads += 1
        self.assertEqual(context.generation, 1)
        return self.sample

    def service(self, **changes):
        args = dict(declaration=self.declaration, contract=self.contract,
                    current_context=lambda: self.context, read_local=self.read,
                    monotonic_ms=lambda: self.time)
        return OfflineReadinessService(**(args | changes))

    def assert_unknown(self, result, reason):
        self.assertEqual(result, {"schema_version": 1, "status": "unknown",
                                  "reason_codes": [reason]})

    def test_projection_to_public_delivery_has_actionable_categorical_reasons(self):
        self.assertEqual(self.service().check(), {
            "schema_version": 1, "status": "needs_attention",
            "reason_codes": ["update_pending", "cloud_save_conflict"],
        })
        self.assertEqual(self.reads, 1)

    def test_source_rejection_precedes_reader(self):
        for changes, reason in [
            ({"reviewed": False}, "offline_evidence_source_unreviewed"),
            ({"benchmarked": False}, "offline_evidence_cost_unbenchmarked"),
            ({"local_only": False}, "offline_evidence_privacy_unreviewed"),
            ({"measured_collection_cost_ms": 101}, "offline_evidence_cost_exceeds_budget"),
        ]:
            self.assert_unknown(self.service(contract=replace(self.contract, **changes)).check(), reason)
        self.assert_unknown(self.service(declaration=replace(self.declaration, uses_network=True)).check(),
                            "offline_evidence_privacy_unreviewed")
        self.assertEqual(self.reads, 0)

    def test_game_running_or_unknown_does_not_read(self):
        for state, reason in [(GameState.RUNNING, "offline_evidence_game_active"),
                              (GameState.UNKNOWN, "offline_evidence_game_unknown")]:
            self.context = OfflineCheckContext(1, state)
            self.assert_unknown(self.service().check(), reason)
        self.assertEqual(self.reads, 0)

    def test_no_selected_context_does_not_read(self):
        self.context = None
        self.assert_unknown(self.service().check(), "offline_evidence_context_changed")
        self.assertEqual(self.reads, 0)

    def test_selection_session_or_game_change_discards_sample(self):
        for new_context in [None, OfflineCheckContext(2, GameState.IDLE),
                            OfflineCheckContext(1, GameState.RUNNING)]:
            self.context = self.sample.context
            def read(context):
                self.context = new_context
                return self.sample
            self.assert_unknown(self.service(read_local=read).check(),
                                "offline_evidence_context_changed")

    def test_sample_from_previous_context_is_rejected(self):
        self.sample = replace(self.sample, context=OfflineCheckContext(0, GameState.IDLE))
        self.assert_unknown(self.service().check(), "offline_evidence_context_changed")

    def test_cache_read_does_not_refresh_stale_timestamp(self):
        self.time = 2_001
        self.assert_unknown(self.service().check(), "offline_evidence_stale")
        self.assertEqual(self.sample.observation.observed_at_monotonic_ms, 1_000)

    def test_future_timestamp_or_backwards_clock_is_rejected(self):
        self.time = 999
        self.assert_unknown(self.service().check(), "offline_evidence_stale")
        times = iter([1_001, 1_000])
        self.assert_unknown(self.service(monotonic_ms=lambda: next(times)).check(),
                            "offline_evidence_stale")

    def test_measured_cost_is_enforced_at_exact_boundary(self):
        for elapsed, rejected in [(20, False), (21, True)]:
            times = iter([1_000, 1_000 + elapsed])
            result = self.service(monotonic_ms=lambda: next(times)).check()
            if rejected:
                self.assert_unknown(result, "offline_evidence_cost_exceeds_budget")
            else:
                self.assertEqual(result["status"], "needs_attention")

    def test_source_exceptions_and_malformed_samples_are_redacted(self):
        def fail(_):
            raise RuntimeError("PRIVATE ACCOUNT /home/private/title")
        self.assert_unknown(self.service(read_local=fail).check(), "offline_evidence_unavailable")
        for sample in [None, {"private": "title"}, replace(self.sample, observation=None)]:
            self.assert_unknown(self.service(read_local=lambda _: sample).check(),
                                "offline_evidence_unavailable")

    def test_repeated_requests_read_again_without_result_cache(self):
        service = self.service()
        service.check()
        self.time = 2_001
        self.assert_unknown(service.check(), "offline_evidence_stale")
        self.assertEqual(self.reads, 2)

    def test_malformed_categories_cannot_bypass_unknown_classification(self):
        values = dict(install=InstallState.INSTALLED, download=DownloadState.CURRENT,
                      steam_entitlement=SteamEntitlementState.RECENT_SIGN_IN_AND_LICENSE,
                      cloud_save=CloudSaveState.SYNCED)
        for field in values:
            with self.subTest(field=field), self.assertRaises(ValueError):
                OfflineReadinessEvidence(**(values | {field: "unknown"}))
        with self.assertRaises(ValueError):
            OfflineReadinessEvidence(local_blockers=["private"])

    def test_observation_rejects_duck_typed_evidence_that_could_look_ready(self):
        forged = SimpleNamespace(
            install="unknown", download="unknown", cloud_save="unknown",
            steam_entitlement=SteamEntitlementState.RECENT_SIGN_IN_AND_LICENSE,
            local_blockers=(), online_check_requirements=(),
        )
        with self.assertRaises(ValueError):
            OfflineReadinessObservation(1_000, forged)
        def read(_):
            return OfflineCheckSample(self.context, OfflineReadinessObservation(1_000, forged))
        self.assert_unknown(self.service(read_local=read).check(), "offline_evidence_unavailable")


if __name__ == "__main__":
    unittest.main()
