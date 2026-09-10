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
)
from regear.delivery.action_history import action_history_to_payload  # noqa: E402


class ActionHistoryDeliveryTests(unittest.TestCase):
    def test_payload_is_categorical_and_contains_only_public_fields(self):
        payload = action_history_to_payload(
            (
                ActionHistoryEntry(
                    "2026-08-31T12:00:00Z",
                    ActionHistoryKind.RECOVERY,
                    ActionHistoryOutcome.RECOVERED,
                    "recovery.portable_restored",
                ),
            )
        )

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(
            payload["entries"],
            [
                {
                    "occurred_at": "2026-08-31T12:00:00Z",
                    "kind": "recovery",
                    "outcome": "recovered",
                    "code": "recovery.portable_restored",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
