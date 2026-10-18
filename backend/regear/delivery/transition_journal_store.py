"""Atomic fixed-path persistence for one validated transition journal.

The Decky runtime constructs this adapter only under Re-Gear's fixed root-owned
state directory. It accepts no path from the frontend and refuses
cross-operation overwrite or history regression.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import hashlib
import stat
from collections.abc import Callable
from pathlib import Path
from dataclasses import replace as replace_journal

from ..domain.control_plane import PlacementState
from ..domain.transition_journal import (
    JournalEventKind,
    TransitionJournal,
    journal_from_dict,
    journal_to_dict,
    valid_boot_id,
)
from ..application.presentation_boot_retirement import eligible_boot_result


MAX_JOURNAL_BYTES = 128 * 1024
JOURNAL_FILENAME = "active-transition.json"
COMPLETED_FILENAME = "completed-presentation.json"
BOOT_RETIRED_FILENAME = "boot-retired-presentation.json"
BOOT_ORIGIN_FILENAME = "presentation-origin-boot.json"
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
        self._origin = state_root / BOOT_ORIGIN_FILENAME
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
        value = self._read_payload(path)
        if value is None:
            return None
        journal = journal_from_dict(value)
        # Active/receipt schema stays readable by immutable older candidates.
        # A separate bounded record is authority only for this exact operation,
        # request and first persisted entry; it never retrofits another journal.
        origin = self._read_payload(self._origin)
        if origin is not None:
            if (set(origin) != {"schema_version", "operation_id", "request_id", "started_at", "origin_boot_id"}
                    or type(origin["schema_version"]) is not int or origin["schema_version"] != 1
                    or not valid_boot_id(origin["origin_boot_id"])):
                raise ValueError("presentation origin boot record is invalid")
            if (journal.entries and origin["operation_id"] == journal.operation_id
                    and origin["request_id"] == journal.request_id
                    and origin["started_at"] == journal.entries[0].occurred_at):
                journal = replace_journal(journal, origin_boot_id=origin["origin_boot_id"])
        return journal

    def _read_payload(self, path: Path) -> dict | None:
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
        return value

    def save(self, journal: TransitionJournal) -> None:
        with self._lock:
            self._save_locked(journal)

    def persist_admitted(self, journal: TransitionJournal, *, admission,
                         generation: str):
        """Strict optional save/readback while normal dock admission is held.

        No caller, engine or native effect uses this interface yet. Failure
        before durable intent may leave no replay inhibition: it is uncertainty,
        never permission. Existing save/retirement callers remain unchanged.
        """
        from .dock_mutation_gate import DockMutationAdmission
        if type(admission) is not DockMutationAdmission:
            raise ValueError("normal admission required")
        if (type(journal) is not TransitionJournal or not journal.entries
                or journal.operation_id != handoff_operation_id(
                    journal.request_id, journal.origin_boot_id, generation)):
            raise ValueError("handoff journal binding mismatch")
        with admission.borrow(self._root) as directory:
            pinned = _PinnedJournal(self._root, directory, admission._gate.owner_uid,
                                    token_factory=self._token_factory)
            with self._lock:
                current = pinned.load_current()
                if current is None and pinned._read_payload(pinned._origin) is not None:
                    raise ValueError("orphan presentation origin requires reconciliation")
                pinned.save(journal)
                # Identical prior values also require fresh mandatory durability.
                pinned._sync_file(pinned._origin)
                pinned._sync_file(pinned._target)
                os.fsync(directory)
                if pinned.load_current() != journal:
                    raise ValueError("handoff journal readback mismatch")
        return AdmittedJournalEvidence(self, admission, journal, generation)

    def _save_locked(self, journal: TransitionJournal) -> None:
        self._validate_root()
        current = self.load_current()
        if current == journal:
            return
        if current is not None:
            self._validate_progress(current, journal)
        elif journal.origin_boot_id:
            if not journal.entries:
                raise ValueError("origin boot requires persisted request history")
            self._write_payload({"schema_version": 1, "operation_id": journal.operation_id,
                "request_id": journal.request_id, "started_at": journal.entries[0].occurred_at,
                "origin_boot_id": journal.origin_boot_id}, self._origin, strict=True)
        self._write(journal, self._target)

    def _write(self, journal: TransitionJournal, path: Path) -> None:
        self._write_payload(journal_to_dict(journal), path, strict=path == self._completed)

    def _write_payload(self, payload: dict, path: Path, *, strict: bool) -> None:
        self._validate_root()
        if path.is_symlink():
            raise ValueError("transition journal target cannot be a symlink")
        data = (
            json.dumps(
                payload,
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
            self._sync_directory(strict=strict)
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

    def retire_after_boot(self, operation_id: str, origin_boot_id: str, current_boot_id: str) -> None:
        """Bounded audit precedes exact removal; no other safety store is erased."""
        with self._lock:
            current = self.load_current()
            if (current is None or current.operation_id != operation_id
                    or current.origin_boot_id != origin_boot_id
                    or not valid_boot_id(current_boot_id) or current_boot_id == origin_boot_id
                    or not eligible_boot_result(current)):
                raise ValueError("boot retirement identity or result is unverified")
            self._write_payload({
                "schema_version": 1,
                "reason": "presentation.new_boot_acknowledgement_retired",
                "current_boot_id": current_boot_id,
                "origin_boot_id": current.origin_boot_id,
                "journal": journal_to_dict(current),
            }, self._root / BOOT_RETIRED_FILENAME, strict=True)
            try:
                self._target.unlink()
            except FileNotFoundError:
                # A separately locked acknowledgement already removed it.
                # This call did not unlink, so it must never resurrect it.
                return
            try:
                self._sync_directory(strict=True)
            except Exception:
                # A post-unlink directory failure must not report retirement.
                # Restore the active evidence when removal is already visible.
                if self.load_current() is None:
                    self._write_payload(journal_to_dict(current), self._target, strict=True)
                raise

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
        if current.origin_boot_id != replacement.origin_boot_id:
            raise ValueError("transition journal origin boot identity changed")
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


def handoff_operation_id(request_id: str, boot_id: str, generation: str) -> str:
    """Versioned canonical binding; not caller authentication or a new record."""
    from ..domain.transition_journal import SAFE_TOKEN
    if (type(request_id) is not str or SAFE_TOKEN.fullmatch(request_id) is None
            or type(boot_id) is not str or not valid_boot_id(boot_id)
            or type(generation) is not str or re.fullmatch(r"[0-9a-f]{64}", generation) is None):
        raise ValueError("invalid handoff journal identity")
    data = json.dumps(["regear-handoff-journal", 1, request_id, boot_id, generation],
                      separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(data).hexdigest()


class AdmittedJournalEvidence:
    """Ephemeral exact-readback evidence, unusable after admission release.

    This does not authorize a native effect; a future consumer must recheck it
    under the same normal admission and immutable approval binding.
    """
    def __init__(self, store, admission, journal, generation):
        self._store, self._admission = store, admission
        self._journal, self._generation = journal, generation

    def is_current(self) -> bool:
        try:
            with self._admission.borrow(self._store._root) as directory:
                pinned = _PinnedJournal(self._store._root, directory,
                                        self._admission._gate.owner_uid)
                return (self._journal.operation_id == handoff_operation_id(
                    self._journal.request_id, self._journal.origin_boot_id, self._generation)
                    and pinned.load_current() == self._journal)
        except Exception:
            return False


class _PinnedJournal(FileTransitionJournalStore):
    """Reuse progression/sidecar schema through secure relative I/O only.

    Instances exist only within admission.borrow(). No path-based retirement or
    acknowledgement operation is exposed by the optional persistence interface.
    """
    def __init__(self, root, directory, owner_uid, **kwargs):
        super().__init__(root, **kwargs)
        self._directory, self._owner_uid = directory, owner_uid

    def _secure(self, descriptor):
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != self._owner_uid
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
                or info.st_size > MAX_JOURNAL_BYTES):
            raise ValueError("unsafe admitted journal object")

    def _validate_root(self):
        info = os.fstat(self._directory)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != self._owner_uid
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise ValueError("unsafe admitted journal root")

    def _sync_directory(self, *, strict=False):
        self._validate_root()
        os.fsync(self._directory)

    def _read_payload(self, path):
        self._validate_root()
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=self._directory)
        except FileNotFoundError:
            return None
        try:
            self._secure(fd)
            data = bytearray()
            while len(data) <= MAX_JOURNAL_BYTES:
                chunk = os.read(fd, min(4096, MAX_JOURNAL_BYTES + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            if len(data) > MAX_JOURNAL_BYTES:
                raise ValueError("admitted journal too large")
            self._secure(fd)
            value = json.loads(data.decode("utf-8"))
            if type(value) is not dict:
                raise ValueError("admitted journal root must be an object")
            return value
        finally:
            os.close(fd)

    def _write_payload(self, payload, path, *, strict):
        self._validate_root()
        data = (json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True) + "\n").encode("utf-8")
        if len(data) > MAX_JOURNAL_BYTES:
            raise ValueError("admitted journal too large")
        # Refuse unsafe existing targets before any replacement.
        self._read_payload(path)
        token = self._token_factory()
        if type(token) is not str or TEMP_TOKEN_RE.fullmatch(token) is None:
            raise ValueError("invalid temporary token")
        temporary = f".{path.name}.{token}.tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=self._directory)
        try:
            self._secure(fd)
            remaining = memoryview(data)
            while remaining:
                count = os.write(fd, remaining)
                if count <= 0:
                    raise OSError("journal write did not advance")
                remaining = remaining[count:]
            os.fsync(fd)
            os.replace(temporary, path.name, src_dir_fd=self._directory,
                       dst_dir_fd=self._directory)
            os.fsync(self._directory)
        finally:
            os.close(fd)
            try:
                os.unlink(temporary, dir_fd=self._directory)
            except FileNotFoundError:
                pass

    def _sync_file(self, path):
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=self._directory)
        try:
            self._secure(fd)
            os.fsync(fd)
        finally:
            os.close(fd)
