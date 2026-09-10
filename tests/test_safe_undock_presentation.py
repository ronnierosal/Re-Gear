from __future__ import annotations

import unittest
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.safe_undock_presentation import (
    SafeUndockPresentationCategory,
    present_safe_undock_result,
)
from regear.domain.safe_undock_readiness import (
    SafeUndockReadiness,
    SafeUndockReadinessState,
    SafeUndockRevalidation,
)


class SafeUndockPresentationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.revalidation = SafeUndockRevalidation(
            attachment_binding="g1-binding",
            observed_generation="generation-7",
            observed_sample_id="sample-9",
        )
        self.ready = SafeUndockReadiness(
            state=SafeUndockReadinessState.READY_FOR_REVALIDATION,
            code="safe_undock.ready_for_revalidation",
            revalidation=self.revalidation,
        )

    def test_evidence_insufficient_is_presented_without_authority(self) -> None:
        result = present_safe_undock_result(
            SafeUndockReadiness(
                state=SafeUndockReadinessState.EVIDENCE_INSUFFICIENT,
                code="safe_undock.game_state_unknown",
            ),
            current_revalidation=None,
            acknowledged=True,
        )

        self.assertEqual(
            SafeUndockPresentationCategory.EVIDENCE_INSUFFICIENT, result.category
        )
        self.assertEqual("safe_undock.game_state_unknown", result.code)
        self.assertIsNone(result.revalidation)

    def test_not_ready_is_presented_without_authority(self) -> None:
        result = present_safe_undock_result(
            SafeUndockReadiness(
                state=SafeUndockReadinessState.NOT_READY,
                code="safe_undock.game_running",
            ),
            current_revalidation=None,
            acknowledged=True,
        )

        self.assertEqual(SafeUndockPresentationCategory.NOT_READY, result.category)
        self.assertEqual("safe_undock.game_running", result.code)

    def test_invalidated_stage_one_five_result_requires_revalidation(self) -> None:
        result = present_safe_undock_result(
            SafeUndockReadiness(
                state=SafeUndockReadinessState.INVALIDATED,
                code="safe_undock.attachment_changed",
            ),
            current_revalidation=self.revalidation,
            acknowledged=True,
        )

        self.assertEqual(
            SafeUndockPresentationCategory.REVALIDATE_REQUIRED, result.category
        )
        self.assertEqual(
            "safe_undock_presentation.revalidation_required", result.code
        )

    def test_missing_acknowledgement_requires_revalidation(self) -> None:
        result = present_safe_undock_result(
            self.ready,
            current_revalidation=self.revalidation,
            acknowledged=False,
        )

        self.assertEqual(
            SafeUndockPresentationCategory.REVALIDATE_REQUIRED, result.category
        )
        self.assertEqual(
            "safe_undock_presentation.acknowledgement_required", result.code
        )

    def test_missing_current_revalidation_invalidates_presentation(self) -> None:
        result = present_safe_undock_result(
            self.ready,
            current_revalidation=None,
            acknowledged=True,
        )

        self.assertEqual(
            SafeUndockPresentationCategory.REVALIDATE_REQUIRED, result.category
        )
        self.assertEqual(
            "safe_undock_presentation.revalidation_stale_or_changed", result.code
        )

    def test_changed_binding_generation_or_sample_requires_revalidation(self) -> None:
        for changed in (
            SafeUndockRevalidation("other-binding", "generation-7", "sample-9"),
            SafeUndockRevalidation("g1-binding", "generation-8", "sample-9"),
            SafeUndockRevalidation("g1-binding", "generation-7", "sample-10"),
        ):
            with self.subTest(changed=changed):
                result = present_safe_undock_result(
                    self.ready,
                    current_revalidation=changed,
                    acknowledged=True,
                )

                self.assertEqual(
                    SafeUndockPresentationCategory.REVALIDATE_REQUIRED,
                    result.category,
                )
                self.assertEqual(
                    "safe_undock_presentation.revalidation_stale_or_changed",
                    result.code,
                )

    def test_matching_revalidation_and_acknowledgement_is_supervised_only(self) -> None:
        result = present_safe_undock_result(
            self.ready,
            current_revalidation=self.revalidation,
            acknowledged=True,
        )

        self.assertEqual(
            SafeUndockPresentationCategory.ELIGIBLE_FOR_SUPERVISED_PHYSICAL_VALIDATION,
            result.category,
        )
        self.assertEqual(
            "safe_undock_presentation.supervised_physical_validation_eligible",
            result.code,
        )
        self.assertEqual(self.revalidation, result.revalidation)


if __name__ == "__main__":
    unittest.main()
