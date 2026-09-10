from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.domain.compatibility_test import (  # noqa: E402
    CompatibilityBaseline,
    CompatibilityTestDirective,
    CompatibilityTestOptions,
    CompatibilityTestStage,
    finish_compatibility_test,
    record_compatibility_baseline,
    record_egpu_handoff_result,
    record_save_result,
    review_compatibility_test,
    start_compatibility_test,
)
from hdm.domain.control_plane import PlacementState  # noqa: E402
from hdm.domain.game_compatibility import (  # noqa: E402
    CompatibilityEvidenceKind,
    EgpuHandoffStatus,
    GameCompatibilityRecord,
    ObservedRenderGpu,
    SaveTestOutcome,
    promote_egpu_handoff,
)
from hdm.domain.models import GameState  # noqa: E402


def start(*, kind=CompatibilityEvidenceKind.SIMULATION, ttl_ms=1000):
    return start_compatibility_test(
        session_id="compat-session-1",
        options=CompatibilityTestOptions(),
        evidence_kind=kind,
        game_catalog_id="steam-1234",
        host_profile_id="asus-rog-ally-x",
        egpu_profile_id="gpd-g1-rx7600mxt-titan-ridge",
        regear_version="0.2.0",
        steamos_version="20260831",
        user_confirmed=True,
        now_ms=100,
        ttl_ms=ttl_ms,
    )


def baseline(session):
    return record_compatibility_baseline(
        session,
        CompatibilityBaseline(
            generation="generation-1",
            placement=PlacementState.PORTABLE,
            game_state=GameState.RUNNING,
            steam_app_id="1234",
            render_gpu=ObservedRenderGpu.INTERNAL,
        ),
        now_ms=101,
    )


class CompatibilityTestModeTests(unittest.TestCase):
    def test_session_requires_consent_and_enables_temporary_diagnostics(self):
        with self.assertRaisesRegex(ValueError, "confirmation"):
            start_compatibility_test(
                session_id="compat-session-1",
                options=CompatibilityTestOptions(),
                evidence_kind=CompatibilityEvidenceKind.SIMULATION,
                game_catalog_id="steam-1234",
                host_profile_id="host",
                egpu_profile_id="egpu",
                regear_version="0.2.0",
                steamos_version="20260831",
                user_confirmed=False,
            )
        session = start()
        self.assertEqual(session.stage, CompatibilityTestStage.AWAITING_BASELINE)
        self.assertIn(
            CompatibilityTestDirective.ENABLE_TEMP_DIAGNOSTICS,
            session.directives,
        )

    def test_hardware_evidence_kind_requires_trusted_runner_authorization(self):
        with self.assertRaisesRegex(ValueError, "trusted-runner"):
            start(kind=CompatibilityEvidenceKind.HARDWARE_TEST)
        authorized = start_compatibility_test(
            session_id="compat-session-2",
            options=CompatibilityTestOptions(),
            evidence_kind=CompatibilityEvidenceKind.HARDWARE_TEST,
            game_catalog_id="steam-1234",
            host_profile_id="asus-rog-ally-x",
            egpu_profile_id="gpd-g1-rx7600mxt-titan-ridge",
            regear_version="0.2.0",
            steamos_version="20260831",
            user_confirmed=True,
            hardware_test_authorized=True,
            now_ms=100,
            ttl_ms=1000,
        )
        self.assertEqual(
            authorized.evidence_kind,
            CompatibilityEvidenceKind.HARDWARE_TEST,
        )

    def test_fresh_results_finish_with_diagnostics_disabled_and_review_required(self):
        session = baseline(start())
        session = record_egpu_handoff_result(
            session,
            status=EgpuHandoffStatus.VERIFIED,
            observed_render_gpu=ObservedRenderGpu.EXTERNAL,
            observation_generation="generation-2",
            now_ms=102,
        )
        session = record_save_result(
            session,
            outcome=SaveTestOutcome.SAVE_ON_EXIT_VERIFIED,
            observation_generation="generation-3",
            now_ms=103,
        )
        session = finish_compatibility_test(session, now_ms=104)
        self.assertEqual(session.stage, CompatibilityTestStage.AWAITING_REVIEW)
        self.assertEqual(
            session.directives,
            (
                CompatibilityTestDirective.DISABLE_TEMP_DIAGNOSTICS,
                CompatibilityTestDirective.REVIEW_RESULTS,
            ),
        )

    def test_stale_or_mismatched_render_evidence_fails_closed(self):
        session = baseline(start())
        stale = record_egpu_handoff_result(
            session,
            status=EgpuHandoffStatus.VERIFIED,
            observed_render_gpu=ObservedRenderGpu.EXTERNAL,
            observation_generation="generation-1",
            now_ms=102,
        )
        self.assertEqual(stale.stage, CompatibilityTestStage.ACTION_REQUIRED)
        self.assertIn(
            CompatibilityTestDirective.DISABLE_TEMP_DIAGNOSTICS,
            stale.directives,
        )
        mismatch = record_egpu_handoff_result(
            session,
            status=EgpuHandoffStatus.VERIFIED,
            observed_render_gpu=ObservedRenderGpu.INTERNAL,
            observation_generation="generation-2",
            now_ms=102,
        )
        self.assertEqual(mismatch.reason_code, "compatibility.external_render_unverified")

    def test_expiry_always_disables_temporary_diagnostics(self):
        expired = record_compatibility_baseline(
            start(ttl_ms=10),
            CompatibilityBaseline(
                generation="generation-1",
                placement=PlacementState.PORTABLE,
                game_state=GameState.IDLE,
                steam_app_id="",
                render_gpu=ObservedRenderGpu.INTERNAL,
            ),
            now_ms=110,
        )
        self.assertEqual(expired.stage, CompatibilityTestStage.CANCELLED)
        self.assertEqual(
            expired.directives,
            (CompatibilityTestDirective.DISABLE_TEMP_DIAGNOSTICS,),
        )

    def test_simulated_review_cannot_promote_a_catalog_record(self):
        session = baseline(start())
        session = record_egpu_handoff_result(
            session,
            status=EgpuHandoffStatus.VERIFIED,
            observed_render_gpu=ObservedRenderGpu.EXTERNAL,
            observation_generation="generation-2",
            now_ms=102,
        )
        session = record_save_result(
            session,
            outcome=SaveTestOutcome.SAVE_ON_EXIT_VERIFIED,
            observation_generation="generation-3",
            now_ms=103,
        )
        session = finish_compatibility_test(session, now_ms=104)
        review = review_compatibility_test(
            session,
            evidence_id="compat-evidence-1",
            tested_at="2026-08-31T12:00:00Z",
            reviewer_confirmed=True,
            now_ms=105,
        )
        self.assertEqual(review.session.stage, CompatibilityTestStage.COMPLETED)
        self.assertEqual(review.evidence.game_catalog_id, "steam-1234")
        self.assertEqual(review.evidence.steam_app_id, "1234")
        record = GameCompatibilityRecord(
            catalog_id="steam-1234",
            title="Test Game",
            steam_app_id="1234",
            host_profile_id="asus-rog-ally-x",
            egpu_profile_id="gpd-g1-rx7600mxt-titan-ridge",
        )
        with self.assertRaisesRegex(ValueError, "simulation"):
            promote_egpu_handoff(
                record,
                EgpuHandoffStatus.VERIFIED,
                review.evidence,
            )

    def test_review_is_explicit_and_out_of_order_events_stop_session(self):
        with self.assertRaisesRegex(ValueError, "awaiting review"):
            review_compatibility_test(
                start(),
                evidence_id="compat-evidence-1",
                tested_at="2026-08-31T12:00:00Z",
                reviewer_confirmed=True,
                now_ms=101,
            )
        stopped = record_save_result(
            start(),
            outcome=SaveTestOutcome.MANUAL_SAVE_REQUIRED,
            observation_generation="generation-1",
            now_ms=101,
        )
        self.assertEqual(stopped.stage, CompatibilityTestStage.ACTION_REQUIRED)

    def test_reviewable_stage_cannot_be_forged_without_complete_results(self):
        session = start()
        with self.assertRaisesRegex(ValueError, "baseline"):
            session.__class__(
                **{
                    field: getattr(session, field)
                    for field in session.__dataclass_fields__
                    if field != "stage"
                },
                stage=CompatibilityTestStage.AWAITING_REVIEW,
            )


if __name__ == "__main__":
    unittest.main()
