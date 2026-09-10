from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.action_history import (  # noqa: E402
    ActionHistoryEntry,
    ActionHistoryKind,
    ActionHistoryOutcome,
    project_action_history,
)
from regear.application.support_bundle import SupportEvent  # noqa: E402


def event(
    code: str,
    component: str,
    *,
    severity: str = "info",
    timestamp: str = "2026-08-31T12:00:00Z",
    details: dict[str, object] | None = None,
) -> SupportEvent:
    return SupportEvent(timestamp, severity, code, component, "stage", "secret", details or {})


class ActionHistoryTests(unittest.TestCase):
    def test_public_action_code_is_bounded_and_categorical(self):
        with self.assertRaisesRegex(ValueError, "code is invalid"):
            ActionHistoryEntry(
                "time", ActionHistoryKind.SLEEP, ActionHistoryOutcome.BLOCKED,
                "sleep blocked / private path",
            )

    def test_projects_action_events_newest_first_with_categorical_outcomes(self):
        history = project_action_history(
            (
                event("transition.requested", "transition", timestamp="one"),
                event("transition.blocked", "transition", timestamp="two"),
                event("recovery.rollback", "recovery", timestamp="three"),
                event("logging.enabled", "diagnostics", timestamp="four"),
            )
        )
        self.assertEqual([row.occurred_at for row in history], ["three", "two", "one"])
        self.assertEqual(history[0].kind, ActionHistoryKind.RECOVERY)
        self.assertEqual(history[0].outcome, ActionHistoryOutcome.RECOVERED)
        self.assertEqual(history[1].outcome, ActionHistoryOutcome.BLOCKED)

    def test_private_details_and_correlation_never_reach_history(self):
        history = project_action_history(
            (
                event(
                    "process_release.failed",
                    "process_release",
                    severity="error",
                    details={"pid": 123, "path": "/home/deck/private", "bdf": "0000:01:00.0"},
                ),
            )
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].outcome, ActionHistoryOutcome.FAILED)
        rendered = repr(history)
        self.assertNotIn("123", rendered)
        self.assertNotIn("private", rendered)
        self.assertNotIn("0000:01:00.0", rendered)
        self.assertNotIn("secret", rendered)

    def test_projects_verified_topology_events_without_details(self):
        entry = project_action_history(
            (event("topology.egpu_attached", "topology"),)
        )[0]
        self.assertEqual(entry.kind, ActionHistoryKind.TOPOLOGY)
        self.assertEqual(entry.outcome, ActionHistoryOutcome.SUCCEEDED)

    def test_history_is_bounded_and_adjacent_duplicates_do_not_spam(self):
        rows = tuple(
            event("sleep.started", "sleep", timestamp=str(index))
            for index in range(25)
        )
        history = project_action_history(rows, max_entries=3)
        self.assertEqual([row.occurred_at for row in history], ["24", "23", "22"])
        duplicate = event("sleep.started", "sleep", timestamp="same")
        deduplicated = project_action_history((duplicate, duplicate))
        self.assertEqual(len(deduplicated), 1)
        with self.assertRaisesRegex(ValueError, "bound"):
            project_action_history(rows, max_entries=21)

    def test_attention_and_failed_codes_take_precedence_over_success(self):
        attention = project_action_history(
            (event("sleep.action_required", "sleep", severity="error"),)
        )[0]
        self.assertEqual(attention.outcome, ActionHistoryOutcome.ATTENTION_REQUIRED)


if __name__ == "__main__":
    unittest.main()
