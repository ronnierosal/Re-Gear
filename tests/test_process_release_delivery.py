from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.guarded_process_release import (  # noqa: E402
    GuardedProcessReleaseExecution,
    GuardedProcessReleasePreview,
    GuardedProcessReleaseStatus,
)
from regear.application.process_release_replay import (  # noqa: E402
    ProcessReleaseAuditEvent,
    ProcessReleaseReplayResult,
    ProcessReleaseStatus,
    ProcessTargetResult,
)
from regear.domain.control_plane import PlacementState, WorkflowState  # noqa: E402
from regear.domain.models import EgpuResourceKind  # noqa: E402
from regear.domain.process_release import (  # noqa: E402
    ProcessReleasePreview,
    ProcessReleasePreviewRow,
    ReleasePhase,
)
from regear.domain.transition_journal import (  # noqa: E402
    JournalEventKind,
    TransitionJournal,
    append_journal_entry,
)
from regear.delivery.process_release import (  # noqa: E402
    execution_to_payload,
    preview_to_payload,
    status_to_payload,
)


def terminal_journal():
    journal = TransitionJournal("operation-public-1", "operation-public-1")
    for kind, code in (
        (JournalEventKind.REQUESTED, "process_release.requested"),
        (JournalEventKind.OBSERVED, "process_release.observed"),
        (JournalEventKind.VALIDATED, "process_release.validated"),
        (JournalEventKind.PLANNED, "process_release.planned"),
        (JournalEventKind.COMMITTED, "process_release.committed"),
    ):
        journal = append_journal_entry(
            journal,
            kind=kind,
            occurred_at="2026-08-31T12:00:00Z",
            workflow_state=WorkflowState.PREPARING_TO_DISCONNECT,
            placement=PlacementState.PORTABLE,
            code=code,
        )
    return journal


class ProcessReleaseDeliveryTests(unittest.TestCase):
    def test_preview_contains_names_and_categories_but_no_executable_identity(self):
        preview = GuardedProcessReleasePreview(
            ReleasePhase.GRACEFUL,
            ProcessReleasePreview(
                "approval_token_public_1",
                ReleasePhase.GRACEFUL,
                120,
                (
                    ProcessReleasePreviewRow(
                        "ordinary-client", (EgpuResourceKind.DRM_RENDER,)
                    ),
                ),
                2,
            ),
        )
        payload = preview_to_payload(preview)
        self.assertEqual(payload["targets"][0]["name"], "ordinary-client")
        self.assertEqual(payload["targets"][0]["resources"], ["drm_render"])
        self.assertNotIn("pid", json.dumps(payload).lower())
        self.assertNotIn("instance", json.dumps(payload).lower())

    def test_execution_exposes_only_counts_receipts_and_categorical_state(self):
        result = ProcessReleaseReplayResult(
            ProcessReleaseStatus.COMPLETED,
            False,
            False,
            (ProcessTargetResult(1, True, False, "target.remaining"),),
            1,
            (
                ProcessReleaseAuditEvent(
                    1,
                    ReleasePhase.GRACEFUL,
                    "target.signal_requested",
                    1,
                    (EgpuResourceKind.DRM_RENDER,),
                    "graceful_terminate",
                ),
            ),
            terminal_journal(),
            "software_blockers_remain",
        )
        payload = execution_to_payload(
            GuardedProcessReleaseExecution(
                True,
                "software_blockers_remain",
                "operation-public-1",
                result,
                "force_receipt_public_1",
            )
        )
        self.assertEqual(payload["remaining_client_count"], 1)
        self.assertEqual(payload["force_receipt_token"], "force_receipt_public_1")
        self.assertFalse(payload["hardware_removal_authorized"])
        encoded = json.dumps(payload).lower()
        self.assertNotIn("target.signal_requested", encoded)
        self.assertNotIn("drm_render", encoded)

    def test_status_payload_has_only_acknowledgement_identity(self):
        payload = status_to_payload(
            GuardedProcessReleaseStatus(
                "process_release.interrupted",
                acknowledgement_required=True,
                action_required=True,
                operation_id="operation-public-1",
            )
        )
        self.assertTrue(payload["acknowledgement_required"])
        self.assertEqual(payload["acknowledgement_id"], "operation-public-1")


if __name__ == "__main__":
    unittest.main()
