"""Port for durably storing one in-progress eGPU removal transaction.

Separated from the domain so composing or reconciling a transaction cannot
write to the live system, matching `regear.ports.filter_ownership` and the
transition journal.

Durability is the whole point, and the ordering requirement is stricter here
than for a filter lease. The record must be on stable storage **before** the
first `remove` write is issued, and each function's outcome must be persisted
before the next function is attempted. A save still buffered when the process
dies leaves precisely the untracked half-attached device this record exists to
make recoverable.

`load` returning None means no transaction was recorded. That is not the same
as a transaction that reconciles as not-started: the first says nothing was ever
planned, the second says a plan exists and the device is still whole.
"""

from __future__ import annotations

from typing import Protocol

from ..domain.removal_transaction import RemovalTransaction


class RemovalTransactionStore(Protocol):
    """Durably hold at most one in-progress removal transaction."""

    def load(self) -> RemovalTransaction | None:
        """Return the stored transaction, or None when nothing is stored."""

    def save(self, record: RemovalTransaction) -> None:
        """Persist `record`, replacing any earlier one.

        Must be durable before returning, and must be called before the write
        it describes rather than after it.
        """

    def clear(self) -> None:
        """Remove the stored transaction.

        Only once the device is known whole again or the removal is confirmed
        complete. Clearing a partially detached transaction discards the only
        evidence that the device is in a state it has never been in.
        """
