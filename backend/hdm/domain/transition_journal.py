"""Bounded, privacy-safe transaction journal contracts.

The journal is an immutable domain value.  Storage is intentionally left behind
an application port so defining or replaying a journal cannot write to the live
system.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from .control_plane import PlacementState, WorkflowState


JOURNAL_SCHEMA_VERSION = 1
MAX_JOURNAL_ENTRIES = 128
MAX_DETAIL_ITEMS = 8
MAX_CODE_LENGTH = 64
SAFE_TOKEN = re.compile(r"^[a-zA-Z0-9_.:-]{1,96}$")
ALLOWED_DETAIL_KEYS = frozenset(
    {
        "blocker_code",
        "capability",
        "confidence",
        "outcome",
        "reason_code",
        "recovery_code",
        "step_code",
        "support_tier",
        "target_placement",
        "launch_policy",
    }
)


class JournalEventKind(StrEnum):
    REQUESTED = "requested"
    OBSERVED = "observed"
    VALIDATED = "validated"
    PLANNED = "planned"
    STEP_STARTED = "step_started"
    SUBSTEP_STARTED = "substep_started"
    SUBSTEP_VERIFIED = "substep_verified"
    STEP_VERIFIED = "step_verified"
    COMMITTED = "committed"
    BLOCKED = "blocked"
    RECOVERY_STARTED = "recovery_started"
    RECOVERY_VERIFIED = "recovery_verified"
    FAILED = "failed"


TERMINAL_EVENTS = frozenset(
    {
        JournalEventKind.COMMITTED,
        JournalEventKind.BLOCKED,
        JournalEventKind.RECOVERY_VERIFIED,
        JournalEventKind.FAILED,
    }
)

ALLOWED_NEXT: dict[JournalEventKind | None, frozenset[JournalEventKind]] = {
    None: frozenset({JournalEventKind.REQUESTED}),
    JournalEventKind.REQUESTED: frozenset(
        {
            JournalEventKind.OBSERVED,
            JournalEventKind.BLOCKED,
            JournalEventKind.FAILED,
        }
    ),
    JournalEventKind.OBSERVED: frozenset(
        {
            JournalEventKind.VALIDATED,
            JournalEventKind.BLOCKED,
            JournalEventKind.FAILED,
        }
    ),
    JournalEventKind.VALIDATED: frozenset(
        {
            JournalEventKind.PLANNED,
            JournalEventKind.BLOCKED,
            JournalEventKind.FAILED,
        }
    ),
    JournalEventKind.PLANNED: frozenset(
        {
            JournalEventKind.STEP_STARTED,
            JournalEventKind.COMMITTED,
            JournalEventKind.BLOCKED,
            JournalEventKind.RECOVERY_STARTED,
            JournalEventKind.FAILED,
        }
    ),
    JournalEventKind.STEP_STARTED: frozenset(
        {
            JournalEventKind.SUBSTEP_STARTED,
            JournalEventKind.STEP_VERIFIED,
            JournalEventKind.BLOCKED,
            JournalEventKind.RECOVERY_STARTED,
            JournalEventKind.FAILED,
        }
    ),
    JournalEventKind.SUBSTEP_STARTED: frozenset(
        {
            JournalEventKind.SUBSTEP_VERIFIED,
            JournalEventKind.BLOCKED,
            JournalEventKind.RECOVERY_STARTED,
            JournalEventKind.FAILED,
        }
    ),
    JournalEventKind.SUBSTEP_VERIFIED: frozenset(
        {
            JournalEventKind.SUBSTEP_STARTED,
            JournalEventKind.STEP_VERIFIED,
            JournalEventKind.BLOCKED,
            JournalEventKind.RECOVERY_STARTED,
            JournalEventKind.FAILED,
        }
    ),
    JournalEventKind.STEP_VERIFIED: frozenset(
        {
            JournalEventKind.STEP_STARTED,
            JournalEventKind.COMMITTED,
            JournalEventKind.BLOCKED,
            JournalEventKind.RECOVERY_STARTED,
            JournalEventKind.FAILED,
        }
    ),
    JournalEventKind.RECOVERY_STARTED: frozenset(
        {JournalEventKind.RECOVERY_VERIFIED, JournalEventKind.FAILED}
    ),
    JournalEventKind.COMMITTED: frozenset(),
    JournalEventKind.BLOCKED: frozenset(),
    JournalEventKind.RECOVERY_VERIFIED: frozenset(),
    JournalEventKind.FAILED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class JournalEntry:
    sequence: int
    kind: JournalEventKind
    occurred_at: str
    workflow_state: WorkflowState
    placement: PlacementState
    code: str
    details: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.sequence <= 0:
            raise ValueError("journal sequence must be positive")
        if not self.occurred_at:
            raise ValueError("journal timestamp is required")
        if not SAFE_TOKEN.fullmatch(self.code) or len(self.code) > MAX_CODE_LENGTH:
            raise ValueError("journal code must be a bounded categorical token")
        if len(self.details) > MAX_DETAIL_ITEMS:
            raise ValueError("journal details exceed the bounded item count")
        keys = tuple(key for key, _ in self.details)
        if len(keys) != len(set(keys)):
            raise ValueError("journal detail keys must be unique")
        for key, value in self.details:
            if key not in ALLOWED_DETAIL_KEYS:
                raise ValueError(f"journal detail key is not allowlisted: {key}")
            if not SAFE_TOKEN.fullmatch(value):
                raise ValueError("journal detail values must be categorical tokens")


@dataclass(frozen=True, slots=True)
class TransitionJournal:
    operation_id: str
    request_id: str
    entries: tuple[JournalEntry, ...] = field(default_factory=tuple)
    schema_version: int = JOURNAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != JOURNAL_SCHEMA_VERSION:
            raise ValueError("unsupported transition journal schema")
        if not SAFE_TOKEN.fullmatch(self.operation_id):
            raise ValueError("journal operation ID must be a categorical token")
        if not SAFE_TOKEN.fullmatch(self.request_id):
            raise ValueError("journal request ID must be a categorical token")
        if len(self.entries) > MAX_JOURNAL_ENTRIES:
            raise ValueError("transition journal exceeds its entry bound")
        expected = tuple(range(1, len(self.entries) + 1))
        if tuple(entry.sequence for entry in self.entries) != expected:
            raise ValueError("journal sequences must be contiguous")
        previous: JournalEventKind | None = None
        for entry in self.entries:
            if entry.kind not in ALLOWED_NEXT[previous]:
                raise ValueError(
                    f"invalid journal event order: {previous} -> {entry.kind}"
                )
            previous = entry.kind

    @property
    def terminal(self) -> bool:
        return bool(self.entries and self.entries[-1].kind in TERMINAL_EVENTS)


def append_journal_entry(
    journal: TransitionJournal,
    *,
    kind: JournalEventKind,
    occurred_at: str,
    workflow_state: WorkflowState,
    placement: PlacementState,
    code: str,
    details: tuple[tuple[str, str], ...] = (),
) -> TransitionJournal:
    if journal.terminal:
        raise ValueError("cannot append to a terminal transition journal")
    if len(journal.entries) >= MAX_JOURNAL_ENTRIES:
        raise ValueError("transition journal is full")
    entry = JournalEntry(
        sequence=len(journal.entries) + 1,
        kind=kind,
        occurred_at=occurred_at,
        workflow_state=workflow_state,
        placement=placement,
        code=code,
        details=details,
    )
    return replace(journal, entries=(*journal.entries, entry))


def journal_to_dict(journal: TransitionJournal) -> dict[str, Any]:
    return {
        "schema_version": journal.schema_version,
        "operation_id": journal.operation_id,
        "request_id": journal.request_id,
        "entries": [
            {
                "sequence": entry.sequence,
                "kind": entry.kind.value,
                "occurred_at": entry.occurred_at,
                "workflow_state": entry.workflow_state.value,
                "placement": entry.placement.value,
                "code": entry.code,
                "details": {key: value for key, value in entry.details},
            }
            for entry in journal.entries
        ],
    }


def journal_from_dict(value: dict[str, Any]) -> TransitionJournal:
    if set(value) != {"schema_version", "operation_id", "request_id", "entries"}:
        raise ValueError("transition journal contains unknown or missing fields")
    entries_value = value["entries"]
    if not isinstance(entries_value, list):
        raise ValueError("transition journal entries must be a list")
    entries: list[JournalEntry] = []
    for raw in entries_value:
        if not isinstance(raw, dict) or set(raw) != {
            "sequence",
            "kind",
            "occurred_at",
            "workflow_state",
            "placement",
            "code",
            "details",
        }:
            raise ValueError("transition journal entry shape is invalid")
        details = raw["details"]
        if not isinstance(details, dict):
            raise ValueError("transition journal details must be an object")
        entries.append(
            JournalEntry(
                sequence=int(raw["sequence"]),
                kind=JournalEventKind(raw["kind"]),
                occurred_at=str(raw["occurred_at"]),
                workflow_state=WorkflowState(raw["workflow_state"]),
                placement=PlacementState(raw["placement"]),
                code=str(raw["code"]),
                details=tuple((str(key), str(item)) for key, item in details.items()),
            )
        )
    return TransitionJournal(
        schema_version=int(value["schema_version"]),
        operation_id=str(value["operation_id"]),
        request_id=str(value["request_id"]),
        entries=tuple(entries),
    )
