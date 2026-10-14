"""Frozen strict decoder from immutable173 source51ba506; body unchanged."""
from typing import Any
from regear.domain.control_plane import PlacementState, WorkflowState
from regear.domain.transition_journal import JournalEntry, JournalEventKind, TransitionJournal

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
