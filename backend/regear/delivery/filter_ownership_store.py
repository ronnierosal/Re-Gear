"""Durable on-disk record of one parent-scope filter attempt.

`regear.ports.filter_ownership` states the ordering this has to support: the record
must be on stable storage *before* the attach it describes is issued, because a
filter attached with nothing recording it returns the system to unfiltered
silently when its unpinned link dies with its owner. A buffered save is
worthless for that, so every save fsyncs the file and then the directory before
returning. It is the same guarantee, and deliberately the same implementation,
as `regear.delivery.removal_transaction_store`, which sits in the same directory
and survives the same crash.

Two decisions are worth stating, because both are the opposite of what a
convenience store would do.

A record that cannot be parsed raises rather than reading as absent. The port
distinguishes "no attempt was ever made" from "an attempt was made and its
record cannot be read". Returning None for a truncated file would collapse
those, and let a caller take a fresh grant over a scope another process may be
holding.

The file is replaced, never appended or edited in place. Each save writes a
complete record to a temporary file in the same directory, fsyncs it, and
renames it over the target, so a reader sees either the whole previous record or
the whole new one and never part of either.

Stores; decides nothing. Whether a record means the scope is held, abandoned or
finished with is `regear.domain.filter_ownership.reconcile`'s question, and this
module never attaches, detaches or queries a filter.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..domain.filter_authorization import CgroupIdentity, OwnerIdentity
from ..domain.filter_ownership import (
    FILTER_OWNERSHIP_SCHEMA_VERSION,
    AttachedFilter,
    FilterOwnership,
    OwnershipPhase,
)


RECORD_FILENAME = "filter-ownership.json"
#: A record holds three small objects and eight scalars. Anything approaching
#: this is not a record this module wrote.
MAX_BYTES = 4096

_RECORD_FIELDS = frozenset(
    (
        "schema_version",
        "phase",
        "uid",
        "boot_hash",
        "cgroup",
        "owner",
        "attachment_binding",
        "generation",
        "sample_id",
        "deadline",
        "claimed_at_ns",
        "attached",
    )
)
_CGROUP_FIELDS = frozenset(("path", "device", "inode"))
_OWNER_FIELDS = frozenset(("pid", "start_time"))
_ATTACHED_FIELDS = frozenset(("program_id", "link_id", "cgroup_id"))


def encode(record: FilterOwnership) -> bytes:
    """Encode a record deterministically.

    The cgroup path is the only host-shaped string here, and it is the literal
    `user@<uid>.service` path the grant was taken over: no home directory, no
    hostname and no device serial. The boot id is already hashed by
    `regear.adapters.steamos.owner_identity` before it ever reaches a grant.
    """
    if type(record) is not FilterOwnership:
        raise ValueError("only a filter ownership record may be encoded")
    value = {
        "schema_version": record.schema_version,
        "phase": record.phase.value,
        "uid": record.uid,
        "boot_hash": record.boot_hash,
        "cgroup": {
            "path": record.cgroup.path,
            "device": record.cgroup.device,
            "inode": record.cgroup.inode,
        },
        "owner": {"pid": record.owner.pid, "start_time": record.owner.start_time},
        "attachment_binding": record.attachment_binding,
        "generation": record.generation,
        "sample_id": record.sample_id,
        "deadline": record.deadline,
        "claimed_at_ns": record.claimed_at_ns,
        "attached": None
        if record.attached is None
        else {
            "program_id": record.attached.program_id,
            "link_id": record.attached.link_id,
            "cgroup_id": record.attached.cgroup_id,
        },
    }
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _object(value: object, fields: frozenset[str], message: str) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(message)
    return value


def _integers(value: dict, keys: tuple[str, ...], message: str) -> None:
    for key in keys:
        # `bool` is an `int` subclass, so `type(...) is not int` is the check
        # that keeps `true` out of a pid field.
        if type(value[key]) is not int:
            raise ValueError(message)


def decode(data: bytes) -> FilterOwnership:
    """Rebuild a record, refusing anything this module did not write.

    Every refusal is a `ValueError`. A caller that cannot read its own record
    must stop and say so; there is no safe default reading for a scope that may
    be held by a process this record was the only trace of.
    """
    if type(data) is not bytes:
        raise ValueError("filter ownership record is not bytes")
    if len(data) > MAX_BYTES:
        raise ValueError("filter ownership record is too large")
    try:
        value = json.loads(data.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("filter ownership record is not readable") from error
    _object(value, _RECORD_FIELDS, "filter ownership record has an unexpected shape")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != FILTER_OWNERSHIP_SCHEMA_VERSION
    ):
        raise ValueError("filter ownership schema version is unsupported")
    for key in ("boot_hash", "attachment_binding", "generation", "sample_id", "phase"):
        if not isinstance(value[key], str):
            raise ValueError("filter ownership identifiers must be text")
    _integers(value, ("uid", "claimed_at_ns"), "filter ownership counters are invalid")
    if type(value["deadline"]) not in (int, float):
        raise ValueError("filter ownership deadline is invalid")

    cgroup = _object(
        value["cgroup"], _CGROUP_FIELDS, "filter ownership cgroup has an unexpected shape"
    )
    if not isinstance(cgroup["path"], str):
        raise ValueError("filter ownership cgroup path must be text")
    _integers(cgroup, ("device", "inode"), "filter ownership cgroup identity is invalid")
    owner = _object(
        value["owner"], _OWNER_FIELDS, "filter ownership owner has an unexpected shape"
    )
    _integers(owner, ("pid", "start_time"), "filter ownership owner identity is invalid")

    attached = None
    if value["attached"] is not None:
        raw = _object(
            value["attached"],
            _ATTACHED_FIELDS,
            "filter ownership attachment has an unexpected shape",
        )
        _integers(
            raw,
            ("program_id", "link_id", "cgroup_id"),
            "filter ownership attachment identity is invalid",
        )
        # AttachedFilter validates the ranges itself.
        attached = AttachedFilter(raw["program_id"], raw["link_id"], raw["cgroup_id"])

    try:
        phase = OwnershipPhase(value["phase"])
    except ValueError as error:
        raise ValueError("filter ownership phase is unknown") from error

    # The domain types enforce the remaining invariants: a usable cgroup and
    # owner identity, complete binding evidence, a finite positive deadline and
    # a phase consistent with the attachment.
    return FilterOwnership(
        value["schema_version"],
        phase,
        value["uid"],
        value["boot_hash"],
        CgroupIdentity(cgroup["path"], cgroup["device"], cgroup["inode"]),
        OwnerIdentity(owner["pid"], owner["start_time"]),
        value["attachment_binding"],
        value["generation"],
        value["sample_id"],
        float(value["deadline"]),
        value["claimed_at_ns"],
        attached,
    )


def _reject_constant(name: str) -> float:
    """Refuse `NaN` and the infinities rather than decoding them.

    `is_finite_time` already rejects them in the domain, but a deadline that
    decodes to `Infinity` and is refused two frames later is a record that
    reads as corrupt in one place and as a never-expiring lease in another.
    """
    raise ValueError(f"filter ownership record contains {name}")


class FileFilterOwnershipStore:
    """Hold at most one filter ownership record in a root-owned directory."""

    def __init__(self, root: Path) -> None:
        if not root.is_absolute():
            raise ValueError("filter ownership root must be absolute")
        self._root = root
        self._record = root / RECORD_FILENAME

    def load(self) -> FilterOwnership | None:
        """Return the stored record, or None when nothing is stored.

        None means the file is absent. It never means the file was unreadable:
        that raises, because a scope whose record cannot be read is not the same
        situation as one no attempt was ever made against.
        """
        try:
            data = self._record.read_bytes()
        except FileNotFoundError:
            return None
        return decode(data)

    def create(self, record: FilterOwnership) -> None:
        """Persist a first claim durably, refusing to replace an existing one.

        `os.link` is the exclusive step: it is atomic and fails with
        `FileExistsError` rather than replacing, so two processes that reconciled
        the same abandoned record cannot both end up believing they own the
        scope. A leftover temporary is harmless -- `load` reads only the record
        name -- so the link is preferred to a second exclusive create on the
        target, which could not be written durably before being published.
        """
        data = self._prepare(record)
        temporary = self._temporary()
        try:
            self._write_exclusive(temporary, data)
            os.link(temporary, self._record)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            # The record is published. Reporting a failure here would tell the
            # caller its claim did not land when it did, and the claim it then
            # could not take would be refused for the rest of the boot.
            pass
        self._sync_directory()

    def save(self, record: FilterOwnership) -> None:
        """Persist `record` durably, replacing any earlier one.

        For phase changes to a record this owner created. Returns only once the
        bytes and the directory entry are both on stable storage, so a caller may
        issue the attach or detach this record describes as soon as it returns.
        """
        data = self._prepare(record)
        temporary = self._temporary()
        try:
            self._write_exclusive(temporary, data)
            os.replace(temporary, self._record)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        self._sync_directory()

    def clear(self) -> None:
        """Remove the stored record.

        Only once the attachment it describes provably cannot exist. Clearing a
        record whose owner is still running discards the only evidence that the
        scope is held, which is the failure this whole module exists to prevent.
        """
        self._record.unlink(missing_ok=True)
        self._sync_directory()

    def _prepare(self, record: FilterOwnership) -> bytes:
        if type(record) is not FilterOwnership:
            raise ValueError("only a filter ownership record may be stored")
        self._validate_root()
        return encode(record)

    def _temporary(self) -> Path:
        return self._root / f"filter-ownership.{os.urandom(8).hex()}.tmp"

    def _validate_root(self) -> None:
        if self._root.is_symlink() or not self._root.is_dir():
            raise ValueError("filter ownership root must be a real directory")

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
        entry pointing at it is not, which is the same as having no record --
        and having no record is precisely the silent failure being fixed.
        """
        if os.name != "posix":
            return
        descriptor = os.open(self._root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
