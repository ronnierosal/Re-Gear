from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.hardware_compatibility import (  # noqa: E402
    HardwareCapability,
    HardwareCatalogStatus,
    HardwareCompatibilityRecord,
    HardwareEvidence,
    HardwareEvidenceKind,
    promote_hardware_capability,
    promote_hardware_combination,
)


def record() -> HardwareCompatibilityRecord:
    return HardwareCompatibilityRecord(
        catalog_id="ally-x-gpd-g1",
        host_profile_id="asus-rog-ally-x",
        egpu_profile_id="gpd-g1-rx7600mxt-titan-ridge",
    )


def evidence(
    capability: HardwareCapability,
    outcome: HardwareCatalogStatus,
    **changes,
) -> HardwareEvidence:
    value = HardwareEvidence(
        evidence_id=f"evidence-{capability.value}",
        capability=capability,
        outcome=outcome,
        kind=HardwareEvidenceKind.SUPERVISED_HARDWARE_TEST,
        intentional_test=True,
        reviewed=True,
        host_profile_id="asus-rog-ally-x",
        egpu_profile_id="gpd-g1-rx7600mxt-titan-ridge",
        regear_version="0.2.0",
        steamos_version="20260831",
        tested_at="2026-08-31T12:00:00Z",
        rollback_or_recovery_verified=True,
    )
    return dataclasses.replace(value, **changes)


class HardwareCompatibilityTests(unittest.TestCase):
    def test_combination_certification_does_not_promote_any_capability(self):
        certified = promote_hardware_combination(
            record(),
            HardwareCatalogStatus.CERTIFIED,
            evidence(
                HardwareCapability.COMBINATION,
                HardwareCatalogStatus.CERTIFIED,
            ),
        )
        self.assertEqual(
            certified.combination_status,
            HardwareCatalogStatus.CERTIFIED,
        )
        self.assertEqual(
            certified.status_for(HardwareCapability.LIVE_REMOVAL),
            HardwareCatalogStatus.UNTESTED,
        )
        self.assertEqual(
            certified.status_for(HardwareCapability.CONTROLLER_HANDOFF),
            HardwareCatalogStatus.UNTESTED,
        )

    def test_simulation_passive_or_unreviewed_evidence_cannot_promote(self):
        cases = (
            evidence(
                HardwareCapability.PROFILE_IDENTITY,
                HardwareCatalogStatus.VERIFIED,
                kind=HardwareEvidenceKind.SIMULATION,
            ),
            evidence(
                HardwareCapability.PROFILE_IDENTITY,
                HardwareCatalogStatus.VERIFIED,
                intentional_test=False,
            ),
            evidence(
                HardwareCapability.PROFILE_IDENTITY,
                HardwareCatalogStatus.VERIFIED,
                reviewed=False,
            ),
        )
        for index, item in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaises(ValueError):
                    promote_hardware_capability(
                        record(),
                        HardwareCapability.PROFILE_IDENTITY,
                        HardwareCatalogStatus.VERIFIED,
                        item,
                    )

    def test_read_only_evidence_can_verify_identity_but_not_mutation(self):
        identity = promote_hardware_capability(
            record(),
            HardwareCapability.PROFILE_IDENTITY,
            HardwareCatalogStatus.VERIFIED,
            evidence(
                HardwareCapability.PROFILE_IDENTITY,
                HardwareCatalogStatus.VERIFIED,
                kind=HardwareEvidenceKind.READ_ONLY_HARDWARE_TEST,
                rollback_or_recovery_verified=False,
            ),
        )
        self.assertEqual(
            identity.status_for(HardwareCapability.PROFILE_IDENTITY),
            HardwareCatalogStatus.VERIFIED,
        )
        with self.assertRaisesRegex(ValueError, "supervised"):
            promote_hardware_capability(
                identity,
                HardwareCapability.DISPLAY_HANDOFF,
                HardwareCatalogStatus.VERIFIED,
                evidence(
                    HardwareCapability.DISPLAY_HANDOFF,
                    HardwareCatalogStatus.VERIFIED,
                    kind=HardwareEvidenceKind.READ_ONLY_HARDWARE_TEST,
                ),
            )

    def test_verified_mutation_requires_recovery_evidence(self):
        with self.assertRaisesRegex(ValueError, "recovery"):
            promote_hardware_capability(
                record(),
                HardwareCapability.AUDIO_HANDOFF,
                HardwareCatalogStatus.VERIFIED,
                evidence(
                    HardwareCapability.AUDIO_HANDOFF,
                    HardwareCatalogStatus.VERIFIED,
                    rollback_or_recovery_verified=False,
                ),
            )

    def test_live_removal_has_additional_fail_closed_evidence_gate(self):
        base = evidence(
            HardwareCapability.LIVE_REMOVAL,
            HardwareCatalogStatus.VERIFIED,
        )
        for changes in (
            {"expected_removal_verified": False, "portable_recovery_verified": True, "kernel_errors_absent": True},
            {"expected_removal_verified": True, "portable_recovery_verified": False, "kernel_errors_absent": True},
            {"expected_removal_verified": True, "portable_recovery_verified": True, "kernel_errors_absent": False},
        ):
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(ValueError, "live removal"):
                    promote_hardware_capability(
                        record(),
                        HardwareCapability.LIVE_REMOVAL,
                        HardwareCatalogStatus.VERIFIED,
                        dataclasses.replace(base, **changes),
                    )
        verified = promote_hardware_capability(
            record(),
            HardwareCapability.LIVE_REMOVAL,
            HardwareCatalogStatus.VERIFIED,
            dataclasses.replace(
                base,
                expected_removal_verified=True,
                portable_recovery_verified=True,
                kernel_errors_absent=True,
            ),
        )
        self.assertEqual(
            verified.status_for(HardwareCapability.LIVE_REMOVAL),
            HardwareCatalogStatus.VERIFIED,
        )

    def test_known_issue_is_recorded_without_becoming_verified(self):
        issue = promote_hardware_capability(
            record(),
            HardwareCapability.LIVE_REMOVAL,
            HardwareCatalogStatus.KNOWN_ISSUE,
            evidence(
                HardwareCapability.LIVE_REMOVAL,
                HardwareCatalogStatus.KNOWN_ISSUE,
                rollback_or_recovery_verified=False,
            ),
        )
        self.assertEqual(
            issue.status_for(HardwareCapability.LIVE_REMOVAL),
            HardwareCatalogStatus.KNOWN_ISSUE,
        )

    def test_profile_mismatch_outcome_mismatch_and_reuse_fail_closed(self):
        item = evidence(
            HardwareCapability.PROFILE_IDENTITY,
            HardwareCatalogStatus.VERIFIED,
        )
        with self.assertRaisesRegex(ValueError, "profile"):
            promote_hardware_capability(
                record(),
                HardwareCapability.PROFILE_IDENTITY,
                HardwareCatalogStatus.VERIFIED,
                dataclasses.replace(item, host_profile_id="different-host"),
            )
        with self.assertRaisesRegex(ValueError, "does not match"):
            promote_hardware_capability(
                record(),
                HardwareCapability.PROFILE_IDENTITY,
                HardwareCatalogStatus.KNOWN_ISSUE,
                item,
            )
        promoted = promote_hardware_capability(
            record(),
            HardwareCapability.PROFILE_IDENTITY,
            HardwareCatalogStatus.VERIFIED,
            item,
        )
        with self.assertRaisesRegex(ValueError, "already used"):
            promote_hardware_capability(
                promoted,
                HardwareCapability.PROFILE_IDENTITY,
                HardwareCatalogStatus.VERIFIED,
                item,
            )

    def test_direct_claims_without_contiguous_promotion_history_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "promotion history"):
            dataclasses.replace(
                record(),
                combination_status=HardwareCatalogStatus.CERTIFIED,
            )
        verified = promote_hardware_capability(
            record(),
            HardwareCapability.PROFILE_IDENTITY,
            HardwareCatalogStatus.VERIFIED,
            evidence(
                HardwareCapability.PROFILE_IDENTITY,
                HardwareCatalogStatus.VERIFIED,
            ),
        )
        with self.assertRaisesRegex(ValueError, "promotion history"):
            dataclasses.replace(verified, promotions=())


if __name__ == "__main__":
    unittest.main()
