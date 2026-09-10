from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.canonical_sleep import CanonicalSleepResult  # noqa: E402
from regear.application.canonical_sleep_process_release import (  # noqa: E402
    CanonicalSleepProcessReleaseCoordinator,
)
from regear.application.guarded_process_release import (  # noqa: E402
    GuardedProcessReleaseExecution,
    GuardedProcessReleasePreview,
)
from regear.domain.process_release import ReleasePhase  # noqa: E402
from regear.domain.sleep_workflow import SleepFlowEvent  # noqa: E402


class Sleep:
    def __init__(self, parent="sleep-operation-0001"):
        self.parent = parent
        self.advances = []

    def release_parent_operation_id(self, request_id):
        return self.parent if request_id == "sleep-request-0001" else ""

    def advance(self, request_id, event):
        self.advances.append((request_id, event))
        return CanonicalSleepResult(True, "disconnect.shutdown_required")


class Process:
    def __init__(self, *, cleared=True, action_required=False):
        self.cleared = cleared
        self.action_required = action_required
        self.previews = []
        self.executions = []

    def preview(self, phase, **kwargs):
        self.previews.append((phase, kwargs))
        return GuardedProcessReleasePreview(phase)

    def execute(self, token):
        self.executions.append(token)
        return GuardedProcessReleaseExecution(
            True,
            "process_release.completed",
            "process-operation-0001",
            SimpleNamespace(software_blockers_cleared=self.cleared),
            action_required=self.action_required,
        )


class CanonicalSleepProcessReleaseCoordinatorTests(unittest.TestCase):
    def test_preview_injects_backend_parent_and_never_accepts_one_from_caller(self):
        sleep = Sleep()
        process = Process()
        value = CanonicalSleepProcessReleaseCoordinator(sleep, process)
        value.preview(
            "sleep-request-0001",
            ReleasePhase.GRACEFUL,
            user_confirmed=True,
        )
        self.assertEqual(
            process.previews[0][1]["parent_operation_id"],
            "sleep-operation-0001",
        )

    def test_cleared_clients_advance_the_same_sleep_request(self):
        sleep = Sleep()
        process = Process(cleared=True)
        result = CanonicalSleepProcessReleaseCoordinator(sleep, process).execute(
            "sleep-request-0001", "approval-token-0001"
        )
        self.assertIsNotNone(result.sleep)
        self.assertEqual(
            sleep.advances,
            [
                (
                    "sleep-request-0001",
                    SleepFlowEvent.SOFTWARE_CLIENTS_RELEASED,
                )
            ],
        )

    def test_remaining_or_action_required_process_result_does_not_advance_sleep(self):
        for process in (
            Process(cleared=False),
            Process(cleared=True, action_required=True),
        ):
            with self.subTest(action_required=process.action_required):
                sleep = Sleep()
                result = CanonicalSleepProcessReleaseCoordinator(
                    sleep, process
                ).execute("sleep-request-0001", "approval-token-0001")
                self.assertIsNone(result.sleep)
                self.assertEqual(sleep.advances, [])

    def test_inactive_sleep_step_cannot_preview_or_execute(self):
        sleep = Sleep(parent="")
        process = Process()
        value = CanonicalSleepProcessReleaseCoordinator(sleep, process)
        preview = value.preview(
            "sleep-request-0001",
            ReleasePhase.GRACEFUL,
            user_confirmed=False,
        )
        execution = value.execute(
            "sleep-request-0001", "approval-token-0001"
        )
        self.assertEqual(
            preview.blockers, ("sleep.client_release_step_inactive",)
        )
        self.assertFalse(execution.process.accepted)
        self.assertEqual(process.previews, [])
        self.assertEqual(process.executions, [])


if __name__ == "__main__":
    unittest.main()
