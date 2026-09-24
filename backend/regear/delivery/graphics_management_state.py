"""What Re-Gear last wrote, so it can tell its own writes from the player's.

Without this record, "the file differs from the profile" and "the player
changed their settings" are indistinguishable, and Re-Gear would overwrite an
intentional edit every time the placement changed. So each managed target keeps
the digest of exactly the bytes Re-Gear last left there, the pinned baseline to
restore, and the schema and profile version those bytes were written under.

"Absent" and "unreadable" are not the same answer, and collapsing them into
None is what let a deleted record read as "never managed" and license an
overwrite. `load` therefore returns a tri-state: ABSENT means no record was
ever written here, UNTRUSTED means one exists but cannot be believed, LOADED
means it can. Only ABSENT -- corroborated by there being no backup history for
the target either -- is a first enrollment. The one thing this record never
does is rebaseline itself.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


FILENAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,160}$")
#: Version 2 adds the lifecycle field. A version 1 record is treated as
#: untrusted rather than upgraded in place: this milestone has never shipped, so
#: there are no real v1 records, and guessing a lifecycle for one would be
#: exactly the kind of assumed authorship the rest of this module refuses.
#:
#: The version of *this record's* format. Deliberately not named
#: "schema_version": that belongs to the game's configuration schema, and an
#: earlier revision of this file used one key for both meanings, so the record
#: format version was silently overwritten by the game's and every record read
#: back as unrecognised.
RECORD_VERSION = 2
MAX_BYTES = 8 * 1024


class Lifecycle(StrEnum):
    """What the last completed operation left behind on the target."""

    #: Re-Gear's profile bytes are on disk.
    MANAGED = "management.managed"
    #: An attempt failed and undid itself; the file is the player's again.
    ROLLED_BACK = "management.rolled_back"
    #: Restore My Settings completed; the file is the player's original.
    RESTORED = "management.restored"
    #: The player opted out. Re-enrollment is an explicit act.
    STOPPED = "management.stopped"


@dataclass(frozen=True, slots=True)
class ManagementRecord:
    """The provenance of the bytes Re-Gear last wrote to one target."""

    identity: str
    target_path: str
    managed_digest: str
    baseline_payload_name: str
    baseline_digest: str
    mode: str
    profile_version: int
    schema_id: str
    schema_version: str
    schema_signature: str
    lifecycle: Lifecycle = Lifecycle.MANAGED

    @property
    def managing(self) -> bool:
        return self.lifecycle is Lifecycle.MANAGED

    @property
    def settled(self) -> bool:
        """Whether the recorded digest describes bytes Re-Gear handed back.

        A settled target is one whose last operation completed with the file
        belonging to the player again. It is re-enrollable without a conflict,
        provided the bytes are still the ones that operation left.
        """
        return self.lifecycle in (Lifecycle.ROLLED_BACK, Lifecycle.RESTORED)

    def as_json(self) -> str:
        return json.dumps(
            {
                "record_version": RECORD_VERSION,
                "identity": self.identity,
                "target_path": self.target_path,
                "managed_digest": self.managed_digest,
                "baseline_payload_name": self.baseline_payload_name,
                "baseline_digest": self.baseline_digest,
                "mode": self.mode,
                "profile_version": self.profile_version,
                "schema_id": self.schema_id,
                "schema_version": self.schema_version,
                "schema_signature": self.schema_signature,
                "lifecycle": self.lifecycle.value,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


class ManagementState(StrEnum):
    """Whether a target's provenance is knowable, and whether it is trusted."""

    ABSENT = "management.absent"
    UNTRUSTED = "management.untrusted"
    LOADED = "management.loaded"


@dataclass(frozen=True, slots=True)
class ManagementLookup:
    state: ManagementState
    record: ManagementRecord | None = None
    detail: str = ""

    @property
    def trusted(self) -> bool:
        return self.state is ManagementState.LOADED and self.record is not None


class ManagementStateError(RuntimeError):
    """The record could not be written. Callers turn this into a failure outcome."""


class ManagementStateStore:
    """One durable provenance record per managed target."""

    def __init__(self, state_root: Path) -> None:
        if not state_root.is_absolute():
            raise ValueError("management state root must be absolute")
        self._root = state_root
        self._lock = threading.Lock()

    def load(self, identity: str) -> ManagementLookup:
        """Read this target's provenance, distinguishing absent from unreadable.

        A file that is not there is ABSENT. A file that is there but cannot be
        parsed, is too large, is a symlink, or carries a record version this
        build does not understand is UNTRUSTED -- evidence that something was
        recorded and is now unreliable, which is never the same as evidence
        that nothing was.
        """
        self._require_identity(identity)
        path = self._root / f"{identity}.json"
        try:
            if path.is_symlink():
                return ManagementLookup(
                    ManagementState.UNTRUSTED, None, "management record is a symlink"
                )
            if not path.exists():
                return ManagementLookup(ManagementState.ABSENT)
            if not path.is_file():
                return ManagementLookup(
                    ManagementState.UNTRUSTED, None, "management record is not a file"
                )
            if path.stat().st_size > MAX_BYTES:
                return ManagementLookup(
                    ManagementState.UNTRUSTED, None, "management record is oversized"
                )
            value = json.loads(path.read_text(encoding="utf-8"))
        except OSError as error:
            return ManagementLookup(
                ManagementState.UNTRUSTED, None, f"management record is unreadable: {error}"
            )
        except ValueError as error:
            return ManagementLookup(
                ManagementState.UNTRUSTED, None, f"management record is malformed: {error}"
            )
        if not isinstance(value, dict) or value.get("record_version") != RECORD_VERSION:
            return ManagementLookup(
                ManagementState.UNTRUSTED,
                None,
                "management record version is not one this build wrote",
            )
        try:
            record = ManagementRecord(
                identity=str(value["identity"]),
                target_path=str(value["target_path"]),
                managed_digest=str(value["managed_digest"]),
                baseline_payload_name=str(value["baseline_payload_name"]),
                baseline_digest=str(value["baseline_digest"]),
                mode=str(value["mode"]),
                profile_version=int(value["profile_version"]),
                schema_id=str(value["schema_id"]),
                schema_version=str(value["schema_version"]),
                schema_signature=str(value["schema_signature"]),
                lifecycle=Lifecycle(str(value["lifecycle"])),
            )
        except (KeyError, TypeError, ValueError) as error:
            return ManagementLookup(
                ManagementState.UNTRUSTED, None, f"management record is incomplete: {error}"
            )
        if record.identity != identity:
            return ManagementLookup(
                ManagementState.UNTRUSTED, None, "management record names another target"
            )
        return ManagementLookup(ManagementState.LOADED, record)

    def save(self, record: ManagementRecord) -> None:
        self._require_identity(record.identity)
        payload = (record.as_json() + "\n").encode("utf-8")
        with self._lock:
            self._write_atomic(self._root / f"{record.identity}.json", payload)

    def stop_managing(self, identity: str) -> ManagementRecord | None:
        """Keep the record and the baseline, but stop claiming the bytes.

        Stop Managing is not Restore: it ends Re-Gear's authorship without
        touching the file. The baseline stays, so a later, separately requested
        Restore My Settings is still possible.
        """
        return self._transition(identity, Lifecycle.STOPPED)

    def resume_managing(self, identity: str) -> ManagementRecord | None:
        """Undo an opt-out. Deliberately an explicit act, never inferred."""
        lookup = self.load(identity)
        if lookup.record is None or lookup.record.lifecycle is not Lifecycle.STOPPED:
            return None
        return self._transition(identity, Lifecycle.ROLLED_BACK)

    def settle(
        self, identity: str, lifecycle: Lifecycle, digest: str
    ) -> ManagementRecord | None:
        """Record that an operation completed and handed the file back.

        The digest is of the bytes now on disk, so a later apply can tell "this
        is exactly what we left" from "somebody changed it afterwards".
        """
        return self._transition(identity, lifecycle, digest)

    def _transition(
        self, identity: str, lifecycle: Lifecycle, digest: str | None = None
    ) -> ManagementRecord | None:
        lookup = self.load(identity)
        existing = lookup.record
        if existing is None:
            return None
        updated = ManagementRecord(
            identity=existing.identity,
            target_path=existing.target_path,
            managed_digest=digest if digest is not None else existing.managed_digest,
            baseline_payload_name=existing.baseline_payload_name,
            baseline_digest=existing.baseline_digest,
            mode=existing.mode,
            profile_version=existing.profile_version,
            schema_id=existing.schema_id,
            schema_version=existing.schema_version,
            schema_signature=existing.schema_signature,
            lifecycle=lifecycle,
        )
        self.save(updated)
        return updated

    def forget(self, identity: str) -> None:
        """Drop the provenance record. The baseline backup is not touched."""
        self._require_identity(identity)
        try:
            (self._root / f"{identity}.json").unlink()
        except FileNotFoundError:
            return
        except OSError as error:
            raise ManagementStateError(f"could not clear management state: {error}") from error

    def _write_atomic(self, target: Path, payload: bytes) -> None:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            temporary = self._root / f".{target.name}.{secrets.token_hex(8)}.tmp"
            with open(temporary, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
            handle = os.open(self._root, os.O_RDONLY)
            try:
                os.fsync(handle)
            finally:
                os.close(handle)
        except OSError as error:
            raise ManagementStateError(f"management state write failed: {error}") from error

    @staticmethod
    def _require_identity(identity: str) -> None:
        if not FILENAME_RE.fullmatch(identity):
            raise ValueError("management state identity is invalid")
