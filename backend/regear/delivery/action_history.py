"""Privacy-safe Decky payload for the existing action-history projection."""

from __future__ import annotations

from ..application.action_history import ActionHistoryEntry


def action_history_to_payload(
    entries: tuple[ActionHistoryEntry, ...],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "entries": [
            {
                "occurred_at": entry.occurred_at,
                "kind": entry.kind.value,
                "outcome": entry.outcome.value,
                "code": entry.code,
            }
            for entry in entries
        ],
    }
