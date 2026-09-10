"""Owner-aware inspection of Re-Gear's one shared transition journal.

This service does not recover or continue work.  It exposes only categorical
ownership and permits the otherwise-unwired canonical-sleep owner to clear its
exact terminal result after explicit player acknowledgement.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..domain.transition_journal import JournalEventKind, SAFE_TOKEN, TransitionJournal
from ..ports.transition_journal import TransitionJournalPort


class TransitionJournalOwner(StrEnum):
    NONE = "none"
    PRESENTATION = "presentation"
    PROCESS_RELEASE = "process_release"
    SLEEP = "sleep"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SharedTransitionJournalStatus:
    code: str
    owner: TransitionJournalOwner
    acknowledgement_required: bool = False
    action_required: bool = False
    operation_id: str = ""
    durable: bool = True


class SharedTransitionJournalService:
    def __init__(self, journal_store: TransitionJournalPort) -> None:
        self._journal_store = journal_store

    def status(self) -> SharedTransitionJournalStatus:
        try:
            journal = self._journal_store.load_current()
        except Exception:
            return SharedTransitionJournalStatus(
                "journal.unavailable",
                TransitionJournalOwner.UNKNOWN,
                action_required=True,
                durable=False,
            )
        if journal is None:
            return SharedTransitionJournalStatus(
                "journal.idle", TransitionJournalOwner.NONE
            )
        owner = self._owner(journal)
        if owner is TransitionJournalOwner.UNKNOWN:
            return SharedTransitionJournalStatus(
                "journal.unknown_owner",
                owner,
                action_required=True,
            )
        if not journal.terminal:
            return SharedTransitionJournalStatus(
                "journal.recovery_required",
                owner,
                action_required=True,
            )
        terminal = journal.entries[-1]
        return SharedTransitionJournalStatus(
            terminal.code,
            owner,
            acknowledgement_required=True,
            action_required=terminal.kind
            in (JournalEventKind.BLOCKED, JournalEventKind.FAILED),
            operation_id=journal.operation_id,
        )

    def acknowledge_sleep(self, operation_id: str) -> bool:
        """Clear only an exact terminal journal categorically owned by sleep."""
        if not SAFE_TOKEN.fullmatch(operation_id):
            return False
        try:
            journal = self._journal_store.load_current()
            if (
                journal is None
                or not journal.terminal
                or journal.operation_id != operation_id
                or self._owner(journal) is not TransitionJournalOwner.SLEEP
            ):
                return False
            self._journal_store.clear_terminal(operation_id)
            return True
        except (OSError, ValueError):
            return False

    @staticmethod
    def _owner(journal: TransitionJournal) -> TransitionJournalOwner:
        if not journal.entries:
            return TransitionJournalOwner.UNKNOWN
        first = journal.entries[0]
        if first.code == "sleep.requested":
            return TransitionJournalOwner.SLEEP
        if first.code == "process_release.requested":
            return TransitionJournalOwner.PROCESS_RELEASE
        if (
            first.code == "request.accepted"
            and dict(first.details).get("capability")
            in (None, "presentation_transition")
        ):
            return TransitionJournalOwner.PRESENTATION
        return TransitionJournalOwner.UNKNOWN
