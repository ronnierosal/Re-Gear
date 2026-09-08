"""Persistence boundary for future durable transition journals."""

from __future__ import annotations

from typing import Protocol

from ..domain.transition_journal import TransitionJournal


class TransitionJournalPort(Protocol):
    def load_current(self) -> TransitionJournal | None:
        """Load the one current operation, including a terminal result."""

    def save(self, journal: TransitionJournal) -> None:
        """Atomically persist one validated journal value."""

    def clear_terminal(self, operation_id: str) -> None:
        """Remove only a terminal journal matching the exact operation ID."""

    def retire_committed(self, operation_id: str) -> None:
        """Archive the exact committed presentation before clearing its active copy."""

    def load_completed(self) -> TransitionJournal | None:
        """Load the bounded latest committed presentation receipt, if present."""

    def clear_completed(self, operation_id: str) -> None:
        """Remove only a committed receipt matching the exact operation ID."""
