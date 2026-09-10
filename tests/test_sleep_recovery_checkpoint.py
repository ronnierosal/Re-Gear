from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.canonical_sleep import CanonicalSleepStatus  # noqa: E402
from regear.application.sleep_recovery_checkpoint import (  # noqa: E402
    SleepRecoveryCheckpointKind,
    project_sleep_recovery_checkpoint,
)
from regear.delivery.canonical_sleep import recovery_checkpoint_to_payload  # noqa: E402
from regear.domain.control_plane import PlacementState, RequestSource  # noqa: E402
from regear.domain.sleep_workflow import SleepFlowStage  # noqa: E402


class SleepRecoveryCheckpointTests(unittest.TestCase):
    def status(self, code: str, *, acknowledgement_required: bool = True):
        return CanonicalSleepStatus(
            code,
            operation_id="sleep-operation-private",
            request_id="sleep-request-private",
            source=RequestSource.PHYSICAL_BUTTON,
            stage=SleepFlowStage.RESTORING_PORTABLE,
            acknowledgement_required=acknowledgement_required,
            action_required=True,
        )

    def test_verified_portable_requires_the_durable_acknowledgement(self):
        checkpoint = project_sleep_recovery_checkpoint(
            self.status("sleep.restart_portable_verified")
        )
        self.assertEqual(checkpoint.kind, SleepRecoveryCheckpointKind.PORTABLE_VERIFIED)
        self.assertTrue(checkpoint.acknowledgement_required)
        self.assertEqual(
            project_sleep_recovery_checkpoint(
                self.status("sleep.restart_portable_verified", acknowledgement_required=False)
            ).kind,
            SleepRecoveryCheckpointKind.NONE,
        )

    def test_incomplete_or_normal_sleep_is_not_an_incident(self):
        for code in ("sleep.idle", "sleep.completed", "sleep.normal_allowed"):
            self.assertEqual(
                project_sleep_recovery_checkpoint(self.status(code)).kind,
                SleepRecoveryCheckpointKind.NONE,
            )

    def test_unverified_and_unavailable_recovery_stay_categorical(self):
        self.assertEqual(
            project_sleep_recovery_checkpoint(
                self.status("sleep.restart_action_required")
            ).kind,
            SleepRecoveryCheckpointKind.ACTION_REQUIRED,
        )
        self.assertEqual(
            project_sleep_recovery_checkpoint(
                self.status("sleep.recovery_observation_unavailable")
            ).kind,
            SleepRecoveryCheckpointKind.UNAVAILABLE,
        )

    def test_delivery_payload_redacts_private_status_fields(self):
        payload = recovery_checkpoint_to_payload(
            project_sleep_recovery_checkpoint(self.status("sleep.restart_action_required"))
        )
        self.assertEqual(set(payload), {"schema_version", "kind", "code", "acknowledgement_required"})
        rendered = repr(payload)
        for private in ("operation", "request", "physical", "restoring", "private"):
            self.assertNotIn(private, rendered)


if __name__ == "__main__":
    unittest.main()
