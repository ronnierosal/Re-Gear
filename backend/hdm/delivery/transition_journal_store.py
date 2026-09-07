"""Atomic fixed-path persistence for one validated transition journal.

The Decky runtime constructs this adapter only under HDM's fixed root-owned
state directory. It accepts no path from the frontend and refuses
cross-operation overwrite or history regression.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
from collections.abc import Callable
from pathlib import Path

from ..domain.control_plane import PlacementState
from ..domain.transition_journal import (
    JournalEventKind,
    TransitionJournal,
    journal_from_dict,
    journal_to_dict,
)


MAX_JOURNAL_BYTES = 128 * 1024
JOURNAL_FILENAME = "active-transition.json"
COMPLETED_FILENAME = "completed-presentation.json"
TEMP_TOKEN_RE = re.compile(r"^[a-zA-Z0-9_-]{8,48}$")


class FileTransitionJournalStore:
    def __init__(
        self,
        state_root: Path,
        *,
        replace: Callable[[str | os.PathLike[str], str | os.PathLike[str]], None] = os.replace,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        if not state_root.is_absolute():
            raise ValueError("transition journal state root must be absolute")
        self._root = state_root
        self._target = state_root / JOURNAL_FILENAME
        self._completed = state_root / COMPLETED_FILENAME
        self._replace = replace
        self._token_factory = token_factory or (lambda: secrets.token_hex(8))
        self._lock = threading.Lock()

    def load_current(self) -> TransitionJournal | None:
        return self._load(self._target)

    def load_completed(self) -> TransitionJournal | None:
        with self._lock:
            journal = self._load(self._completed)
            if journal is not None:
                self._validate_completed(journal)
            return journal

    def _load(self, path: Path) -> TransitionJournal | None:
        self._validate_root()
        if path.is_symlink():
            raise ValueError("transition journal target cannot be a symlink")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError:
            return None
        with os.fdopen(descriptor, "rb") as source:
            data = source.read(MAX_JOURNAL_BYTES + 1)
        if len(data) > MAX_JOURNAL_BYTES:
            raise ValueError("transition journal exceeds its byte bound")
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("transition journal JSON is invalid") from error
        if not isinstance(value, dict):
            raise ValueError("transition journal root must be an object")
        return journal_from_dict(value)

    def save(self, journal: TransitionJournal) -> None:
        with self._lock:
            self._save_locked(journal)

    def _save_locked(self, journal: TransitionJournal) -> None:
        self._validate_root()
        current = self.load_current()
        if current == journal:
            return
        if current is not None:
            self._validate_progress(current, journal)
        self._write(journal, self._target)

    def _write(self, journal: TransitionJournal, path: Path) -> None:
        self._validate_root()
        if path.is_symlink():
            raise ValueError("transition journal target cannot be a symlink")
        data = (
            json.dumps(
                journal_to_dict(journal),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
            + "\n"
        ).encode("utf-8")
        if len(data) > MAX_JOURNAL_BYTES:
            raise ValueError("transition journal exceeds its byte bound")

        token = self._token_factory()
        if not TEMP_TOKEN_RE.fullmatch(token):
            raise ValueError("transition journal temporary token is invalid")
        temporary = self._root / f".{path.name}.{token}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as target:
                target.write(data)
                target.flush()
                os.fsync(target.fileno())
            self._replace(temporary, path)
            self._sync_directory(strict=path == self._completed)
        except Exception:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def retire_committed(self, operation_id: str) -> None:
        """Durably keep one presentation receipt before removing its active copy."""
        with self._lock:
            current = self.load_current()
            if current is None:
                completed = self._load(self._completed)
                if completed is None or completed.operation_id != operation_id:
                    raise ValueError("transition journal operation ID does not match")
                self._validate_completed(completed)
                return
            if current.operation_id != operation_id:
                raise ValueError("transition journal operation ID does not match")
            self._validate_completed(current)
            # Rewriting an identical receipt also repairs durability after a crash
            # between archive replacement and active removal.
            self._write(current, self._completed)
            self._target.unlink()
            self._sync_directory()

    def clear_completed(self, operation_id: str) -> None:
        with self._lock:
            completed = self._load(self._completed)
            if completed is None:
                return
            if completed.operation_id != operation_id:
                raise ValueError("transition journal operation ID does not match")
            self._validate_completed(completed)
            self._completed.unlink()
            self._sync_directory()

    @staticmethod
    def _validate_completed(journal: TransitionJournal) -> None:
        if not journal.terminal or journal.entries[-1].kind is not JournalEventKind.COMMITTED:
            raise ValueError("completed presentation must be committed")
        if (
            journal.entries[0].code != "request.accepted"
            or journal.entries[-1].code not in {"transition.committed", "transition.no_op"}
        ):
            raise ValueError("completed presentation codes are invalid")
        details = dict(journal.entries[0].details)
        target = details.get("target_placement")
        if details.get("capability") != "presentation_transition":
            raise ValueError("completed presentation capability is required")
        if target not in (PlacementState.PORTABLE.value, PlacementState.DOCKED_EGPU.value):
            raise ValueError("completed presentation target is invalid")
        if journal.entries[-1].placement.value != target:
            raise ValueError("completed presentation target does not match final placement")

    def clear_terminal(self, operation_id: str) -> None:
        with self._lock:
            self._clear_terminal_locked(operation_id)

    def _clear_terminal_locked(self, operation_id: str) -> None:
        current = self.load_current()
        if current is None:
            return
        if current.operation_id != operation_id:
            raise ValueError("transition journal operation ID does not match")
        if not current.terminal:
            raise ValueError("an incomplete transition journal cannot be cleared")
        self._target.unlink()
        self._sync_directory()

    def _validate_root(self) -> None:
        try:
            metadata = self._root.lstat()
        except OSError as error:
            raise ValueError("transition journal state root is unavailable") from error
        if self._root.is_symlink() or not self._root.is_dir():
            raise ValueError("transition journal state root must be a real directory")
        if not metadata:
            raise ValueError("transition journal state root is unavailable")

    @staticmethod
    def _validate_progress(
        current: TransitionJournal, replacement: TransitionJournal
    ) -> None:
        if current.operation_id != replacement.operation_id:
            raise ValueError("cannot overwrite a different transition operation")
        if current.request_id != replacement.request_id:
            raise ValueError("transition journal request identity changed")
        if current.terminal:
            raise ValueError("cannot overwrite a terminal transition journal")
        if len(replacement.entries) < len(current.entries):
            raise ValueError("transition journal history cannot regress")
        if replacement.entries[: len(current.entries)] != current.entries:
            raise ValueError("transition journal history cannot diverge")

    def _sync_directory(self, *, strict: bool = False) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            descriptor = os.open(self._root, flags)
        except OSError:
            if strict and os.name != "nt":
                raise
            return
        try:
            os.fsync(descriptor)
        except OSError:
            if strict and os.name != "nt":
                raise
            pass
        finally:
            os.close(descriptor)
