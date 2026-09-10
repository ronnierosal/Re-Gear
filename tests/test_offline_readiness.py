from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.offline_readiness import (  # noqa: E402
    CloudSaveState,
    DownloadState,
    InstallState,
    LocalOfflineBlocker,
    OfflineReadinessEvidence,
    OfflineReadinessObservation,
    OfflineEvidenceAdmissionKind,
    OfflineEvidenceCollectionContract,
    OfflineEvidenceField,
    OfflineEvidenceSourceDeclaration,
    OfflineEvidenceSourceKind,
    OfflineEvidenceSourceReviewKind,
    OfflineReadinessAssessment,
    OfflineReadinessStatus,
    OnlineCheckRequirement,
    SteamEntitlementState,
    admit_offline_evidence_collection,
    admit_reviewed_offline_evidence_source,
    classify_fresh_offline_readiness,
    classify_offline_readiness,
    offline_readiness_to_public_dict,
    review_offline_evidence_source,
)
from regear.domain.models import GameState  # noqa: E402


def ready_evidence(**changes) -> OfflineReadinessEvidence:
    value = OfflineReadinessEvidence(
        install=InstallState.INSTALLED,
        download=DownloadState.CURRENT,
        steam_entitlement=SteamEntitlementState.RECENT_SIGN_IN_AND_LICENSE,
        cloud_save=CloudSaveState.SYNCED,
    )
    return replace(value, **changes)


def contract(**changes) -> OfflineEvidenceCollectionContract:
    value = OfflineEvidenceCollectionContract(
        reviewed=True,
        local_only=True,
        identity_minimized=True,
        interval_ms=60_000,
        measured_collection_cost_ms=20,
        benchmarked=True,
        max_evidence_age_ms=10 * 60_000,
    )
    return replace(value, **changes)


def source(**changes) -> OfflineEvidenceSourceDeclaration:
    values = {
        "kind": OfflineEvidenceSourceKind.LOCAL_STEAM_METADATA,
        "read_only": True,
        "uses_network": False,
        "persists_data": False,
        "identity_minimized": True,
        "fields": (
            OfflineEvidenceField.INSTALL,
            OfflineEvidenceField.DOWNLOAD,
            OfflineEvidenceField.ENTITLEMENT,
            OfflineEvidenceField.CLOUD_SAVE,
        ),
    }
    values.update(changes)
    return OfflineEvidenceSourceDeclaration(**values)


class OfflineReadinessTests(unittest.TestCase):
    def test_source_review_approves_only_local_read_only_minimized_declarations(self):
        review = review_offline_evidence_source(source())
        self.assertEqual(review.kind, OfflineEvidenceSourceReviewKind.APPROVED)
        self.assertEqual(review.reason_code, "local_readiness_confirmed")
        for changes in (
            {"read_only": False},
            {"uses_network": True},
            {"persists_data": True},
            {"identity_minimized": False},
        ):
            with self.subTest(changes=changes):
                rejected = review_offline_evidence_source(source(**changes))
                self.assertEqual(rejected.kind, OfflineEvidenceSourceReviewKind.REJECTED)
                self.assertEqual(rejected.reason_code, "offline_evidence_privacy_unreviewed")

    def test_source_review_composes_with_cost_and_game_admission_without_collecting(self):
        admitted = admit_reviewed_offline_evidence_source(source(), contract(), GameState.IDLE)
        self.assertEqual(admitted.kind, OfflineEvidenceAdmissionKind.ADMIT)
        deferred = admit_reviewed_offline_evidence_source(source(), contract(), GameState.RUNNING)
        self.assertEqual(deferred.kind, OfflineEvidenceAdmissionKind.DEFER)
        rejected = admit_reviewed_offline_evidence_source(
            source(uses_network=True), contract(), GameState.IDLE
        )
        self.assertEqual(rejected.kind, OfflineEvidenceAdmissionKind.REJECT)
        self.assertEqual(rejected.reason_code, "offline_evidence_privacy_unreviewed")

    def test_complete_local_evidence_is_ready_to_try_not_a_guarantee(self):
        assessment = classify_offline_readiness(ready_evidence())
        self.assertEqual(assessment.status, OfflineReadinessStatus.READY_TO_TRY_OFFLINE)
        self.assertEqual(assessment.reason_codes, ("local_readiness_confirmed",))

    def test_local_blockers_and_pending_data_need_attention(self):
        assessment = classify_offline_readiness(
            ready_evidence(
                download=DownloadState.PENDING_UPDATE,
                cloud_save=CloudSaveState.CONFLICT,
                local_blockers=(LocalOfflineBlocker.LOCAL_STORAGE_UNAVAILABLE,),
            )
        )
        self.assertEqual(assessment.status, OfflineReadinessStatus.NEEDS_ATTENTION)
        self.assertEqual(
            assessment.reason_codes,
            ("local_storage_unavailable", "update_pending", "cloud_save_conflict"),
        )

    def test_launcher_drm_anticheat_and_game_owned_requirements_need_online_check(self):
        assessment = classify_offline_readiness(
            ready_evidence(
                online_check_requirements=(
                    OnlineCheckRequirement.THIRD_PARTY_LAUNCHER,
                    OnlineCheckRequirement.DRM,
                    OnlineCheckRequirement.ANTI_CHEAT,
                    OnlineCheckRequirement.GAME_OWNED_ONLINE_REQUIREMENT,
                )
            )
        )
        self.assertEqual(assessment.status, OfflineReadinessStatus.ONLINE_CHECK_NEEDED)
        self.assertEqual(
            assessment.reason_codes,
            ("third_party_launcher", "drm", "anti_cheat", "game_owned_online_requirement"),
        )

    def test_unknown_or_unconfirmed_evidence_fails_closed(self):
        assessment = classify_offline_readiness(OfflineReadinessEvidence())
        self.assertEqual(assessment.status, OfflineReadinessStatus.UNKNOWN)
        self.assertIn("steam_entitlement_unknown", assessment.reason_codes)

    def test_attention_wins_over_online_check_and_unknown_evidence(self):
        assessment = classify_offline_readiness(
            OfflineReadinessEvidence(
                install=InstallState.NOT_INSTALLED,
                online_check_requirements=(OnlineCheckRequirement.DRM,),
            )
        )
        self.assertEqual(assessment.status, OfflineReadinessStatus.NEEDS_ATTENTION)
        self.assertEqual(assessment.reason_codes, ("game_not_installed",))

    def test_public_serialization_exposes_only_categorical_guidance(self):
        payload = offline_readiness_to_public_dict(classify_offline_readiness(ready_evidence()))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["status"], "ready_to_try_offline")
        self.assertNotIn("steam_app_id", payload)
        self.assertNotIn("title", payload)
        self.assertNotIn("path", payload)

    def test_every_public_status_remains_identity_minimized(self):
        for status, reason in (
            (OfflineReadinessStatus.READY_TO_TRY_OFFLINE, "local_readiness_confirmed"),
            (OfflineReadinessStatus.NEEDS_ATTENTION, "update_pending"),
            (OfflineReadinessStatus.ONLINE_CHECK_NEEDED, "drm"),
            (OfflineReadinessStatus.UNKNOWN, "offline_evidence_stale"),
        ):
            with self.subTest(status=status):
                payload = offline_readiness_to_public_dict(
                    OfflineReadinessAssessment(status, (reason,))
                )
                self.assertEqual(payload["status"], status.value)
                self.assertEqual(payload["reason_codes"], [reason])
                rendered = repr(payload)
                for private in ("appid", "account", "title", "path", "observed_at"):
                    self.assertNotIn(private, rendered)

    def test_duplicate_evidence_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicated"):
            OfflineReadinessEvidence(
                local_blockers=(
                    LocalOfflineBlocker.MISSING_LOCAL_CONTENT,
                    LocalOfflineBlocker.MISSING_LOCAL_CONTENT,
                )
            )

    def test_assessment_rejects_non_public_reason_text(self):
        with self.assertRaisesRegex(ValueError, "not public"):
            OfflineReadinessAssessment(
                OfflineReadinessStatus.UNKNOWN,
                ("account-name-or-private-path",),
            )

    def test_reviewed_local_benchmarked_fresh_evidence_can_be_classified(self):
        admission = admit_offline_evidence_collection(contract(), GameState.IDLE)
        self.assertEqual(admission.kind, OfflineEvidenceAdmissionKind.ADMIT)
        assessment = classify_fresh_offline_readiness(
            OfflineReadinessObservation(100, ready_evidence()),
            contract(),
            now_monotonic_ms=101,
        )
        self.assertEqual(assessment.status, OfflineReadinessStatus.READY_TO_TRY_OFFLINE)

    def test_unreviewed_privacy_or_cost_failure_stays_unknown(self):
        for changes, reason in (
            ({"reviewed": False}, "offline_evidence_source_unreviewed"),
            ({"local_only": False}, "offline_evidence_privacy_unreviewed"),
            ({"identity_minimized": False}, "offline_evidence_privacy_unreviewed"),
            ({"benchmarked": False}, "offline_evidence_cost_unbenchmarked"),
            ({"interval_ms": 1_000, "measured_collection_cost_ms": 101}, "offline_evidence_cost_exceeds_budget"),
        ):
            with self.subTest(reason=reason):
                assessment = classify_fresh_offline_readiness(
                    OfflineReadinessObservation(100, ready_evidence()),
                    contract(**changes),
                    now_monotonic_ms=101,
                )
                self.assertEqual(assessment.status, OfflineReadinessStatus.UNKNOWN)
                self.assertEqual(assessment.reason_codes, (reason,))

    def test_game_active_or_unknown_defers_optional_evidence_collection(self):
        for game_state, delay in ((GameState.RUNNING, 30_000), (GameState.UNKNOWN, 15_000)):
            with self.subTest(game_state=game_state):
                admission = admit_offline_evidence_collection(contract(), game_state)
                self.assertEqual(admission.kind, OfflineEvidenceAdmissionKind.DEFER)
                self.assertEqual(admission.defer_for_ms, delay)

    def test_stale_or_future_observation_never_appears_ready(self):
        for now in (99, 100 + contract().max_evidence_age_ms + 1):
            with self.subTest(now=now):
                assessment = classify_fresh_offline_readiness(
                    OfflineReadinessObservation(100, ready_evidence()),
                    contract(),
                    now_monotonic_ms=now,
                )
                self.assertEqual(assessment.status, OfflineReadinessStatus.UNKNOWN)
                self.assertEqual(assessment.reason_codes, ("offline_evidence_stale",))


if __name__ == "__main__":
    unittest.main()
