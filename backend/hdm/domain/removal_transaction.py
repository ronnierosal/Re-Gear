"""Durable record of an eGPU removal in progress, and its recovery verdict.

A removal detaches the audio function, then the GPU function, verifying each is
gone. Between those two writes the device is **half attached**: audio detached,
GPU still bound and still holding its resources.

`hdm.egpu_remove` handles that correctly while it is alive -- it stops at the
first function that did not go, says the device may be partially detached, and
names the rescan recovery. That behaviour depends entirely on the process still
existing to report it, which is exactly what a player-facing caller cannot
assume.

This is the record that survives the process, so a later reader can tell a
partial removal from a device that merely enumerated oddly.

Why this matters more than the filter lease it follows. An orphaned filter
(`hdm.domain.filter_ownership`) leaves the system unfiltered, which is the
state it started in and knows how to be. An orphaned removal leaves the system
in a state it has never been in: one function of a multi-function device
detached, the other bound, and no record of which of those was intended.

The recovery this module prescribes is always **restore, never continue**.
Completing a removal that a dead process began would act on readiness gathered
before an unknown gap -- during which a game may have launched, a display may
have come back, or the device may have been swapped. Rescanning restores both
functions and forces the sequence to start over from a fresh observation, which
is the only defensible action when the gap cannot be measured.

Pure. It removes nothing, restores nothing, and stores nothing; storage lives
behind `hdm.ports.removal_transaction`. Nothing here is a claim that any device
is safe to unplug.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


PCI_ADDRESS = re.compile(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]")
SAFE_TOKEN = re.compile(r"^[a-zA-Z0-9_.:@/+-]{1,192}$")

REMOVAL_TRANSACTION_SCHEMA_VERSION = 1


class FunctionProgress(StrEnum):
    PENDING = "pending"
    REMOVED = "removed"
    FAILED = "failed"


class RemovalTransactionState(StrEnum):
    #: Recorded before the first write, so a crash before any detach is still
    #: visible as an intention rather than as nothing at all.
    PLANNED = "planned"
    #: At least one write has been attempted.
    IN_PROGRESS = "in_progress"
    #: Every intended function was confirmed absent.
    COMPLETE = "complete"
    #: Recovery ran and the functions were restored.
    RESTORED = "restored"


class RecoveryState(StrEnum):
    #: Nothing was detached; the device is as the record found it.
    NOT_STARTED = "not_started"
    #: Every intended function is confirmed absent.
    COMPLETE = "complete"
    #: Some intended functions are gone and some remain. The device is in a
    #: state it has never been in, and must be restored rather than finished.
    NEEDS_RECOVERY = "needs_recovery"
    #: Recovery already ran.
    RESTORED = "restored"
    #: The record cannot be reconciled with the device now present.
    INCONSISTENT = "inconsistent"


@dataclass(frozen=True, slots=True)
class RemovalFunctionRecord:
    """One PCI function of the removal, and how far it got."""

    address: str
    progress: FunctionProgress

    def __post_init__(self) -> None:
        if not PCI_ADDRESS.fullmatch(self.address):
            raise ValueError("removal transaction address is invalid")


@dataclass(frozen=True, slots=True)
class RemovalTransaction:
    """A removal that was started, with what it intended and what it achieved."""

    schema_version: int
    owner_id: str
    device_set: str
    state: RemovalTransactionState
    functions: tuple[RemovalFunctionRecord, ...]
    started_at_ns: int

    def __post_init__(self) -> None:
        if self.schema_version != REMOVAL_TRANSACTION_SCHEMA_VERSION:
            raise ValueError("removal transaction schema version is unsupported")
        for value in (self.owner_id, self.device_set):
            if not SAFE_TOKEN.fullmatch(value):
                raise ValueError("removal transaction identifiers must be safe tokens")
        if not self.functions:
            raise ValueError("a removal transaction needs at least one function")
        addresses = tuple(item.address.lower() for item in self.functions)
        if len(set(addresses)) != len(addresses):
            raise ValueError("a removal transaction cannot repeat a function")
        if self.started_at_ns < 0:
            raise ValueError("a removal transaction cannot start before time zero")

    @property
    def addresses(self) -> tuple[str, ...]:
        return tuple(item.address for item in self.functions)

    @property
    def intended_removed(self) -> tuple[str, ...]:
        """Addresses this transaction believes it detached."""
        return tuple(
            item.address
            for item in self.functions
            if item.progress is FunctionProgress.REMOVED
        )


@dataclass(frozen=True, slots=True)
class Recovery:
    """What a record and a fresh device observation say when read together."""

    state: RecoveryState
    code: str
    restore: tuple[str, ...] = ()

    @property
    def safe_to_continue(self) -> bool:
        """Whether a caller may proceed with the sequence as it stands.

        Only a not-yet-started transaction qualifies. A partial removal never
        does: continuing would act on readiness gathered before a gap of
        unknown length, during which a game may have launched or a display may
        have returned.
        """
        return self.state is RecoveryState.NOT_STARTED

    @property
    def device_disturbed(self) -> bool:
        """Whether the device was left somewhere it has never been."""
        return self.state is RecoveryState.NEEDS_RECOVERY


def reconcile(
    record: RemovalTransaction | None,
    *,
    present_addresses: tuple[str, ...],
) -> Recovery:
    """Read a durable record against which functions the bus reports now.

    `present_addresses` are the addresses currently enumerated, read fresh. The
    record describes an intention that may have been interrupted, so the device
    is the authority on what actually happened and the record only says what was
    meant to.
    """
    if record is None:
        return Recovery(RecoveryState.INCONSISTENT, "removal_transaction.no_record")
    if type(record) is not RemovalTransaction or type(present_addresses) is not tuple:
        return Recovery(
            RecoveryState.INCONSISTENT, "removal_transaction.input_invalid"
        )
    if any(type(address) is not str for address in present_addresses):
        return Recovery(
            RecoveryState.INCONSISTENT, "removal_transaction.input_invalid"
        )

    if record.state is RemovalTransactionState.RESTORED:
        return Recovery(RecoveryState.RESTORED, "removal_transaction.restored")

    present = {address.lower() for address in present_addresses}
    intended = tuple(item.address for item in record.functions)
    gone = tuple(address for address in intended if address.lower() not in present)
    remaining = tuple(address for address in intended if address.lower() in present)

    if not gone:
        # Nothing detached. Whatever the record's own state says, the device is
        # whole, so the sequence may run from a fresh observation.
        return Recovery(RecoveryState.NOT_STARTED, "removal_transaction.not_started")
    if not remaining:
        return Recovery(RecoveryState.COMPLETE, "removal_transaction.complete")

    # Some gone, some present: the half-attached state. Restore everything the
    # transaction intended, not only what it believes it removed -- its belief
    # was recorded before an interruption of unknown length and the device is
    # the authority here.
    return Recovery(
        RecoveryState.NEEDS_RECOVERY,
        "removal_transaction.partially_detached",
        intended,
    )


def plan(
    *,
    owner_id: str,
    device_set: str,
    addresses: tuple[str, ...],
    now_ns: int,
) -> RemovalTransaction:
    """Record the intended function set before the first write.

    Written first for the same reason the filter claim is: a crash between
    recording and acting leaves a recoverable record, while the reverse order
    detaches a function nothing describes.
    """
    return RemovalTransaction(
        REMOVAL_TRANSACTION_SCHEMA_VERSION,
        owner_id,
        device_set,
        RemovalTransactionState.PLANNED,
        tuple(
            RemovalFunctionRecord(address, FunctionProgress.PENDING)
            for address in addresses
        ),
        now_ns,
    )


def record_progress(
    record: RemovalTransaction, address: str, progress: FunctionProgress
) -> RemovalTransaction:
    """Record how one function fared, without deciding the whole outcome.

    The transaction becomes `complete` only when every intended function is
    marked removed. A caller cannot shortcut that by marking the last one, and
    `reconcile` still checks the claim against the device afterwards.
    """
    if address.lower() not in {item.address.lower() for item in record.functions}:
        raise ValueError("that function is not part of this removal transaction")
    functions = tuple(
        RemovalFunctionRecord(item.address, progress)
        if item.address.lower() == address.lower()
        else item
        for item in record.functions
    )
    everything_removed = all(
        item.progress is FunctionProgress.REMOVED for item in functions
    )
    state = (
        RemovalTransactionState.COMPLETE
        if everything_removed
        else RemovalTransactionState.IN_PROGRESS
    )
    return RemovalTransaction(
        record.schema_version,
        record.owner_id,
        record.device_set,
        state,
        functions,
        record.started_at_ns,
    )


def record_restored(record: RemovalTransaction) -> RemovalTransaction:
    """Record that recovery ran and the bus restored the functions."""
    return RemovalTransaction(
        record.schema_version,
        record.owner_id,
        record.device_set,
        RemovalTransactionState.RESTORED,
        record.functions,
        record.started_at_ns,
    )
