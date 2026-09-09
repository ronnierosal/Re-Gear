"""Durable on-disk record of one in-progress eGPU removal.

`hdm.ports.removal_transaction` states the ordering this has to support: the
record must be on stable storage *before* the first detach is issued, and each
function's outcome must be persisted before the next function is attempted. A
buffered save is worthless here -- the crash it has to survive is the one that
happens between two writes to the PCI bus -- so every save fsyncs the file and
then the directory before returning.

Two decisions are worth stating, because both are the opposite of what a
convenience store would do.

A record that cannot be parsed raises rather than reading as absent. The port
distinguishes "nothing was ever planned" from "a plan exists": returning None
for a truncated or corrupted file would collapse those into each other and let
a caller start a fresh removal over a device that may already be half detached.

The file is replaced, never appended or edited in place. Each save writes a
complete record to a temporary file in the same directory, fsyncs it, and
renames it over the target, so a reader either sees the whole previous record
or the whole new one and never a partial line of either.

Stores; decides nothing. Whether a record means the device needs recovery is
`hdm.domain.removal_transaction.reconcile`'s question, and this module never
detaches, restores or rescans anything.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..domain.removal_transaction import (
    REMOVAL_TRANSACTION_SCHEMA_VERSION,
    FunctionProgress,
    RemovalFunctionRecord,
    RemovalTransaction,
    RemovalTransactionState,
)


RECORD_FILENAME = "removal-transaction.json"
#: A record holds two functions and six scalars. Anything approaching this is
#: not a record this module wrote.
MAX_BYTES = 8192
_RECORD_FIELDS = frozenset(
    ("schema_version", "owner_id", "device_set", "state", "functions", "started_at_ns")
)
_FUNCTION_FIELDS = frozenset(("address", "progress"))


def encode(record: RemovalTransaction) -> bytes:
    """Encode a record deterministically, with no host or workstation data."""
    return json.dumps(
        {
            "schema_version": record.schema_version,
            "owner_id": record.owner_id,
            "device_set": record.device_set,
            "state": record.state.value,
            "functions": [
                {"address": item.address, "progress": item.progress.value}
                for item in record.functions
            ],
            "started_at_ns": record.started_at_ns,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def decode(data: bytes) -> RemovalTransaction:
    """Rebuild a record, refusing anything this module did not write.

    Every refusal is a `ValueError`. A caller that cannot read its own record
    must stop and say so; there is no safe default reading for a removal that
    may be half finished.
    """
    if len(data) > MAX_BYTES:
        raise ValueError("removal transaction record is too large")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("removal transaction record is not readable") from error
    if not isinstance(value, dict) or set(value) != _RECORD_FIELDS:
        raise ValueError("removal transaction record has an unexpected shape")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != REMOVAL_TRANSACTION_SCHEMA_VERSION
    ):
        raise ValueError("removal transaction schema version is unsupported")
    if type(value["started_at_ns"]) is not int:
        raise ValueError("removal transaction start time is invalid")
    for key in ("owner_id", "device_set"):
        if not isinstance(value[key], str):
            raise ValueError("removal transaction identifiers must be text")
    if not isinstance(value["functions"], list) or not value["functions"]:
        raise ValueError("removal transaction record has no functions")

    functions = []
    for item in value["functions"]:
        if not isinstance(item, dict) or set(item) != _FUNCTION_FIELDS:
            raise ValueError("removal transaction function has an unexpected shape")
        if not isinstance(item["address"], str) or not isinstance(item["progress"], str):
            raise ValueError("removal transaction function fields must be text")
        try:
            progress = FunctionProgress(item["progress"])
        except ValueError as error:
            raise ValueError("removal transaction progress is unknown") from error
        # RemovalFunctionRecord validates the address shape itself.
        functions.append(RemovalFunctionRecord(item["address"], progress))
    try:
        state = RemovalTransactionState(value["state"])
    except ValueError as error:
        raise ValueError("removal transaction state is unknown") from error

    # The domain type enforces the remaining invariants: safe identifiers, no
    # repeated function, a non-negative start.
    return RemovalTransaction(
        value["schema_version"],
        value["owner_id"],
        value["device_set"],
        state,
        tuple(functions),
        value["started_at_ns"],
    )


class FileRemovalTransactionStore:
    """Hold at most one removal transaction in a root-owned directory."""

    def __init__(self, root: Path) -> None:
        if not root.is_absolute():
            raise ValueError("removal transaction root must be absolute")
        self._root = root
        self._record = root / RECORD_FILENAME

    def load(self) -> RemovalTransaction | None:
        """Return the stored transaction, or None when nothing is stored.

        None means the file is absent. It never means the file was unreadable:
        that raises, because a removal that cannot read its own record is not
        the same situation as one that never started.
        """
        try:
            data = self._record.read_bytes()
        except FileNotFoundError:
            return None
        return decode(data)

    def save(self, record: RemovalTransaction) -> None:
        """Persist `record` durably, replacing any earlier one.

        Returns only once the bytes and the directory entry are both on stable
        storage, so a caller may issue the write this record describes as soon
        as it returns.
        """
        if type(record) is not RemovalTransaction:
            raise ValueError("only a removal transaction may be stored")
        self._validate_root()
        data = encode(record)
        temporary = self._root / f"removal-transaction.{os.urandom(8).hex()}.tmp"
        try:
            self._write_exclusive(temporary, data)
            os.replace(temporary, self._record)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        self._sync_directory()

    def clear(self) -> None:
        """Remove the stored transaction.

        Only once the device is known whole again or the removal is confirmed
        complete: clearing a partially detached transaction discards the only
        evidence that the device is in a state it has never been in.
        """
        self._record.unlink(missing_ok=True)
        self._sync_directory()

    def _validate_root(self) -> None:
        if self._root.is_symlink() or not self._root.is_dir():
            raise ValueError("removal transaction root must be a real directory")

    def _write_exclusive(self, path: Path, data: bytes) -> None:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as output:
            if os.name == "posix":
                os.fchmod(output.fileno(), 0o600)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())

    def _sync_directory(self) -> None:
        """Make the rename or unlink itself durable, not only the bytes.

        Without this the record can be complete on disk while the directory
        entry pointing at it is not, which is the same as having no record.
        """
        if os.name != "posix":
            return
        descriptor = os.open(self._root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
