"""Offline, journaled migration of the managed Gamescope identity file."""

from __future__ import annotations

import json
import os
import secrets
import stat
from contextlib import contextmanager
from pathlib import Path

from .gamescope_integration import GamescopeIntegrationStore, MAX_DROPIN_BYTES
from .identity_migration import IdentityMigrationError
from .user_directory import UserDirectory


SCHEMA = 1
PHASES = frozenset(("prepared", "current_published", "committed", "rolling_back", "rolled_back"))


class ManagedDropinMigration:
    """Replace one exact former drop-in without accepting edited files.

    The external journal retains the exact prior bytes needed for rollback. A
    crash may leave both filenames briefly present; that state is accepted only
    when the journal and both byte strings match this transaction.
    """

    def __init__(self, store: GamescopeIntegrationStore, journal: Path) -> None:
        if not journal.is_absolute() or journal.parent == journal:
            raise ValueError("drop-in migration journal must be a narrow absolute path")
        self._store = store
        self._journal = journal
        self._lock = journal.with_name(journal.name + ".lock")

    def inspect(self) -> dict[str, str | None]:
        document = self._load_journal()
        current, legacy = self._read_files()
        return {
            "current": self._classify_current(current),
            "former": self._classify_legacy(legacy),
            "journal_phase": None if document is None else document["phase"],
        }

    def preflight_apply(self) -> bool:
        """Validate an apply without publishing or removing either drop-in.

        The return value records whether this component owns a reversible
        migration.  A current-only or absent installation is already a no-op;
        an exact former file, or an existing forward journal, participates.
        """
        with self._hold_lock():
            document = self._load_journal()
            current, legacy = self._read_files()
            if document is None:
                if current is not None and legacy is not None:
                    raise IdentityMigrationError("both managed drop-in identities exist")
                if current is not None:
                    self._require_current(current)
                    return False
                if legacy is None:
                    return False
                self._require_legacy(legacy)
                return True

            self._validate_document(document)
            if document["phase"] in ("rolling_back", "rolled_back"):
                raise IdentityMigrationError(
                    "managed drop-in journal records rollback; apply is refused"
                )
            expected_current = document["current"]
            expected_legacy = document["legacy"]
            if current is None:
                if legacy != expected_legacy:
                    raise IdentityMigrationError(
                        "former managed drop-in changed during migration"
                    )
                self._require_legacy(legacy)
            else:
                if current != expected_current or not self._store._managed_file_safe(
                    self._store.target
                ):
                    raise IdentityMigrationError(
                        "current managed drop-in changed during migration"
                    )
                if legacy is not None:
                    if legacy != expected_legacy:
                        raise IdentityMigrationError(
                            "former managed drop-in changed during migration"
                        )
                    self._require_legacy(legacy)
            return True

    def apply(self) -> dict[str, str | None]:
        with self._hold_lock():
            document = self._load_journal()
            current, legacy = self._read_files()
            if document is None:
                if current is not None and legacy is not None:
                    raise IdentityMigrationError("both managed drop-in identities exist")
                if current is not None:
                    self._require_current(current)
                    return self.inspect()
                if legacy is None:
                    return self.inspect()
                self._require_legacy(legacy)
                document = {
                    "schema": SCHEMA,
                    "operation_id": secrets.token_hex(16),
                    "phase": "prepared",
                    "legacy": legacy,
                    "current": self._store.expected_text(),
                }
                self._write_journal(document)
            else:
                self._validate_document(document)
                if document["phase"] in ("rolling_back", "rolled_back"):
                    raise IdentityMigrationError(
                        "managed drop-in journal records rollback; apply is refused"
                    )

            current, legacy = self._read_files()
            expected_current = document["current"]
            expected_legacy = document["legacy"]
            if current is None:
                if legacy != expected_legacy:
                    raise IdentityMigrationError("former managed drop-in changed during migration")
                self._publish(self._store.DROPIN_NAME, expected_current.encode("utf-8"))
                current = expected_current
            elif current != expected_current:
                raise IdentityMigrationError("current managed drop-in changed during migration")

            document["phase"] = "current_published"
            self._write_journal(document)
            if legacy is not None:
                if legacy != expected_legacy:
                    raise IdentityMigrationError("former managed drop-in changed during migration")
                self._remove(self._store.legacy_target.name, expected_legacy.encode("utf-8"))
            document["phase"] = "committed"
            self._write_journal(document)
            result = self.inspect()
            if result["current"] != "current" or result["former"] != "absent":
                raise IdentityMigrationError("managed drop-in migration did not converge")
            return result

    def rollback(self) -> dict[str, str | None]:
        with self._hold_lock():
            document = self._load_journal()
            if document is None:
                raise IdentityMigrationError("no managed drop-in migration journal exists")
            self._validate_document(document)
            current, legacy = self._read_files()
            expected_current = document["current"]
            expected_legacy = document["legacy"]
            if document["phase"] == "rolled_back":
                if current is not None or legacy != expected_legacy:
                    raise IdentityMigrationError("rolled-back managed drop-in state changed")
                return self.inspect()
            document["phase"] = "rolling_back"
            self._write_journal(document)
            if legacy is None:
                if current != expected_current:
                    raise IdentityMigrationError("current managed drop-in changed before rollback")
                self._publish(self._store.legacy_target.name, expected_legacy.encode("utf-8"))
                legacy = expected_legacy
            elif legacy != expected_legacy:
                raise IdentityMigrationError("former managed drop-in changed before rollback")
            if current is not None:
                if current != expected_current:
                    raise IdentityMigrationError("current managed drop-in changed before rollback")
                self._remove(self._store.DROPIN_NAME, expected_current.encode("utf-8"))
            document["phase"] = "rolled_back"
            self._write_journal(document)
            result = self.inspect()
            if result["current"] != "absent" or result["former"] != "former":
                raise IdentityMigrationError("managed drop-in rollback did not converge")
            return result

    def _read_files(self) -> tuple[str | None, str | None]:
        try:
            current = self._store._read_optional(self._store.target)
            legacy = self._store._read_optional(self._store.legacy_target)
        except (OSError, UnicodeDecodeError, ValueError) as error:
            raise IdentityMigrationError("managed drop-in inspection failed") from error
        return current, legacy

    def _classify_current(self, value: str | None) -> str:
        if value is None:
            return "absent"
        return "current" if value == self._store.expected_text() else "modified"

    def _classify_legacy(self, value: str | None) -> str:
        if value is None:
            return "absent"
        return "former" if value in self._store._superseded_renderings() else "modified"

    def _require_current(self, value: str) -> None:
        if value != self._store.expected_text() or not self._store._managed_file_safe(self._store.target):
            raise IdentityMigrationError("current managed drop-in is not exact and safe")

    def _require_legacy(self, value: str) -> None:
        if value not in self._store._superseded_renderings() or not self._store._managed_file_safe(self._store.legacy_target):
            raise IdentityMigrationError("former managed drop-in is not exact and safe")

    def _publish(self, name: str, value: bytes) -> None:
        try:
            with UserDirectory(
                self._store.target.parent,
                self._store.user.uid,
                self._store.user.gid,
                create_from=self._store.user.home,
            ) as directory:
                directory.publish(name, value, 0o644)
        except (OSError, ValueError) as error:
            raise IdentityMigrationError("managed drop-in publication failed") from error

    def _remove(self, name: str, value: bytes) -> None:
        try:
            with UserDirectory(
                self._store.target.parent,
                self._store.user.uid,
                self._store.user.gid,
                create_from=self._store.user.home,
            ) as directory:
                directory.remove_matching(name, value, MAX_DROPIN_BYTES)
        except (OSError, ValueError) as error:
            raise IdentityMigrationError("managed drop-in removal failed") from error

    def _validate_document(self, document: dict[str, object]) -> None:
        if set(document) != {"schema", "operation_id", "phase", "legacy", "current"}:
            raise IdentityMigrationError("managed drop-in migration journal has unknown fields")
        if document["schema"] != SCHEMA or document["phase"] not in PHASES:
            raise IdentityMigrationError("managed drop-in migration journal is incompatible")
        if not isinstance(document["operation_id"], str) or len(document["operation_id"]) != 32:
            raise IdentityMigrationError("managed drop-in migration operation identity is invalid")
        if document["current"] != self._store.expected_text():
            raise IdentityMigrationError("managed drop-in migration current bytes changed")
        if document["legacy"] not in self._store._superseded_renderings():
            raise IdentityMigrationError("managed drop-in migration former bytes are unknown")

    def _load_journal(self) -> dict[str, object] | None:
        try:
            metadata = self._journal.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise IdentityMigrationError("managed drop-in migration journal is unsafe")
        if len(self._journal.read_bytes()) > MAX_DROPIN_BYTES:
            raise IdentityMigrationError("managed drop-in migration journal is oversized")
        try:
            value = json.loads(self._journal.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise IdentityMigrationError("managed drop-in migration journal is unreadable") from error
        if not isinstance(value, dict):
            raise IdentityMigrationError("managed drop-in migration journal is invalid")
        self._validate_document(value)
        return value

    def _write_journal(self, document: dict[str, object]) -> None:
        self._validate_document(document)
        self._ensure_journal_parent()
        temporary = self._journal.with_name("." + self._journal.name + "." + secrets.token_hex(8))
        payload = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            offset = 0
            while offset < len(payload):
                written = os.write(descriptor, payload[offset:])
                if written <= 0:
                    raise OSError("journal write made no progress")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, self._journal)
        if os.name == "posix":
            directory = os.open(self._journal.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)

    def _ensure_journal_parent(self) -> None:
        self._journal.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = self._journal.parent.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise IdentityMigrationError("managed drop-in migration parent is unsafe")
        if os.name == "posix" and (
            metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise IdentityMigrationError(
                "managed drop-in migration parent must be authority-owned mode 0700"
            )

    @contextmanager
    def _hold_lock(self):
        self._ensure_journal_parent()
        descriptor = os.open(
            self._lock,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            if os.name == "posix":
                import fcntl
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise IdentityMigrationError("managed drop-in migration lock is held") from error
            yield
        finally:
            os.close(descriptor)
