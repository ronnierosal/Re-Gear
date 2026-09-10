from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.domain.game_compatibility import (  # noqa: E402
    CompatibilityEvidence,
    CompatibilityEvidenceKind,
    EgpuHandoffStatus,
    GameCompatibilityRecord,
    GameSaveCapability,
    ObservedRenderGpu,
    SaveTestOutcome,
    promote_egpu_handoff,
    promote_save_sleep,
)


def record() -> GameCompatibilityRecord:
    return GameCompatibilityRecord(
        catalog_id="steam-1234",
        steam_app_id="1234",
        title="Test Game",
        host_profile_id="asus-rog-ally-x",
        egpu_profile_id="gpd-g1-rx7600m-xt",
    )


def evidence(**changes) -> CompatibilityEvidence:
    value = CompatibilityEvidence(
        evidence_id="test-report-1",
        game_catalog_id="steam-1234",
        steam_app_id="1234",
        kind=CompatibilityEvidenceKind.HARDWARE_TEST,
        intentional_test=True,
        reviewed=True,
        host_profile_id="asus-rog-ally-x",
        egpu_profile_id="gpd-g1-rx7600m-xt",
        regear_version="0.2.0",
        steamos_version="20260831",
        tested_at="2026-08-31T12:00:00Z",
        observed_render_gpu=ObservedRenderGpu.EXTERNAL,
        save_outcome=SaveTestOutcome.NOT_TESTED,
    )
    return dataclasses.replace(value, **changes)


class GameCompatibilityTests(unittest.TestCase):
    def test_dimensions_promote_independently_with_distinct_evidence(self):
        handoff = promote_egpu_handoff(
            record(), EgpuHandoffStatus.VERIFIED, evidence()
        )
        self.assertEqual(handoff.egpu_handoff, EgpuHandoffStatus.VERIFIED)
        self.assertEqual(handoff.save_sleep, GameSaveCapability.UNTESTED)
        saved = promote_save_sleep(
            handoff,
            GameSaveCapability.VERIFIED_SAVE_ON_EXIT,
            evidence(
                evidence_id="test-report-2",
                save_outcome=SaveTestOutcome.SAVE_ON_EXIT_VERIFIED,
            ),
        )
        self.assertEqual(saved.save_sleep, GameSaveCapability.VERIFIED_SAVE_ON_EXIT)
        self.assertEqual(len(saved.promotions), 2)

    def test_simulation_or_passive_telemetry_cannot_promote(self):
        cases = (
            evidence(kind=CompatibilityEvidenceKind.SIMULATION),
            evidence(intentional_test=False),
            evidence(reviewed=False),
        )
        for index, item in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaises(ValueError):
                    promote_egpu_handoff(
                        record(), EgpuHandoffStatus.VERIFIED, item
                    )

    def test_verified_handoff_requires_observed_external_rendering(self):
        with self.assertRaisesRegex(ValueError, "external rendering"):
            promote_egpu_handoff(
                record(),
                EgpuHandoffStatus.VERIFIED,
                evidence(observed_render_gpu=ObservedRenderGpu.UNKNOWN),
            )
        fallback = promote_egpu_handoff(
            record(),
            EgpuHandoffStatus.FALLS_BACK_TO_IGPU,
            evidence(observed_render_gpu=ObservedRenderGpu.INTERNAL),
        )
        self.assertEqual(
            fallback.egpu_handoff,
            EgpuHandoffStatus.FALLS_BACK_TO_IGPU,
        )

    def test_save_claim_must_match_the_reviewed_outcome(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            promote_save_sleep(
                record(),
                GameSaveCapability.VERIFIED_TRIGGERABLE_AUTOSAVE,
                evidence(save_outcome=SaveTestOutcome.GRACEFUL_EXIT_VERIFIED),
            )

    def test_profile_mismatch_and_duplicate_dimension_reuse_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "profile"):
            promote_egpu_handoff(
                record(),
                EgpuHandoffStatus.VERIFIED,
                evidence(host_profile_id="different-host"),
            )
        with self.assertRaisesRegex(ValueError, "game identity"):
            promote_egpu_handoff(
                record(),
                EgpuHandoffStatus.VERIFIED,
                evidence(game_catalog_id="steam-5678", steam_app_id="5678"),
            )
        promoted = promote_egpu_handoff(
            record(), EgpuHandoffStatus.VERIFIED, evidence()
        )
        with self.assertRaisesRegex(ValueError, "already used"):
            promote_egpu_handoff(
                promoted,
                EgpuHandoffStatus.VERIFIED_WITH_WORKAROUND,
                evidence(),
            )

    def test_one_report_may_support_each_independent_dimension_once(self):
        item = evidence(save_outcome=SaveTestOutcome.SAVE_ON_EXIT_VERIFIED)
        handoff = promote_egpu_handoff(
            record(), EgpuHandoffStatus.VERIFIED, item
        )
        saved = promote_save_sleep(
            handoff,
            GameSaveCapability.VERIFIED_SAVE_ON_EXIT,
            item,
        )
        self.assertEqual(len(saved.promotions), 2)

    def test_record_rejects_invalid_appid_and_multiline_title(self):
        with self.assertRaisesRegex(ValueError, "AppID"):
            dataclasses.replace(record(), steam_app_id="../../1")
        with self.assertRaisesRegex(ValueError, "title"):
            dataclasses.replace(record(), title="unsafe\nvalue")

    def test_direct_verified_status_without_promotion_history_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "promotion history"):
            dataclasses.replace(record(), egpu_handoff=EgpuHandoffStatus.VERIFIED)
        with self.assertRaisesRegex(ValueError, "promotion history"):
            dataclasses.replace(
                record(),
                save_sleep=GameSaveCapability.GRACEFUL_EXIT_VERIFIED,
            )


if __name__ == "__main__":
    unittest.main()
