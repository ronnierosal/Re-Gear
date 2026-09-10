"""Controller-friendly action-history projection over the existing event log.

This module intentionally stores nothing. It turns already bounded Re-Gear support
events into a smaller, user-facing categorical timeline without forwarding
event details, correlation IDs, or any hardware/process identity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .support_bundle import SupportEvent


MAX_ACTION_HISTORY_ENTRIES = 20
ACTION_CODE_RE = re.compile(r"^[a-z0-9_.-]{1,96}$")


class ActionHistoryKind(StrEnum):
    TOPOLOGY = "topology"
    TRANSITION = "transition"
    RECOVERY = "recovery"
    SLEEP = "sleep"
    PROCESS_RELEASE = "process_release"
    PERIPHERAL = "peripheral"
    PRESENTATION = "presentation"


class ActionHistoryOutcome(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    RECOVERED = "recovered"
    BLOCKED = "blocked"
    FAILED = "failed"
    ATTENTION_REQUIRED = "attention_required"


_COMPONENTS = {
    "topology": ActionHistoryKind.TOPOLOGY,
    "transition": ActionHistoryKind.TRANSITION,
    "recovery": ActionHistoryKind.RECOVERY,
    "sleep": ActionHistoryKind.SLEEP,
    "process_release": ActionHistoryKind.PROCESS_RELEASE,
    "peripheral": ActionHistoryKind.PERIPHERAL,
    "presentation": ActionHistoryKind.PRESENTATION,
}


@dataclass(frozen=True, slots=True)
class ActionHistoryEntry:
    occurred_at: str
    kind: ActionHistoryKind
    outcome: ActionHistoryOutcome
    code: str

    def __post_init__(self) -> None:
        if not self.occurred_at or not self.code:
            raise ValueError("action-history time and code are required")
        if not ACTION_CODE_RE.fullmatch(self.code):
            raise ValueError("action-history code is invalid")


def project_action_history(
    events: Iterable[SupportEvent], *, max_entries: int = MAX_ACTION_HISTORY_ENTRIES
) -> tuple[ActionHistoryEntry, ...]:
    """Project recent action events newest-first without creating a second log."""
    if max_entries < 1 or max_entries > MAX_ACTION_HISTORY_ENTRIES:
        raise ValueError("action-history entry bound is invalid")
    rows: list[ActionHistoryEntry] = []
    for event in events:
        kind = _COMPONENTS.get(event.component)
        if kind is None:
            continue
        entry = ActionHistoryEntry(
            event.timestamp,
            kind,
            _outcome(event.code, event.severity),
            event.code,
        )
        if rows and rows[-1] == entry:
            continue
        rows.append(entry)
    return tuple(reversed(rows[-max_entries:]))


def _outcome(code: str, severity: str) -> ActionHistoryOutcome:
    tokens = set(code.split("."))
    if "action_required" in tokens or "attention_required" in tokens:
        return ActionHistoryOutcome.ATTENTION_REQUIRED
    if "blocked" in tokens:
        return ActionHistoryOutcome.BLOCKED
    if "recovered" in tokens or "rollback" in tokens:
        return ActionHistoryOutcome.RECOVERED
    if "failed" in tokens or severity in {"error", "critical"}:
        return ActionHistoryOutcome.FAILED
    if "started" in tokens or "requested" in tokens or "preparing" in tokens:
        return ActionHistoryOutcome.STARTED
    return ActionHistoryOutcome.SUCCEEDED
