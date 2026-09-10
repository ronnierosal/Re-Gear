"""Port for durably storing the one parent-scope filter record.

Separated from the domain so composing or reconciling a record cannot write to
the live system, the same split `hdm.ports.removal_transaction` and the
transition journal use. `hdm.ports.removal_transaction` already names this
module as the pattern it follows; this is that module.

The ordering requirement is the whole point, and it is the opposite way round
from the removal transaction. There, the record must be on stable storage
before the first detach, because a half-detached device is a state the system
has never been in. Here the record must be on stable storage before the
**attach**, because the failure this exists to prevent is a filter that was
attached with nothing recording it: a crash then returns the system to
unfiltered silently, and no later reader can tell that from a filter that was
never armed.

That is why `save` must be durable before it returns. A save still buffered when
the process dies is worthless: the crash it has to survive is the one between
the record and the `BPF_LINK_CREATE` that follows it.

`load` returning None means nothing is stored. It must never mean the record was
unreadable -- that raises, because "no attempt was ever made" and "an attempt
was made and its record cannot be read" need opposite answers, and collapsing
them lets a caller arm over a scope it knows nothing about.
"""

from __future__ import annotations

from typing import Protocol

from ..domain.filter_ownership import FilterOwnership


class FilterOwnershipStore(Protocol):
    """Durably hold at most one parent-scope filter ownership record."""

    def load(self) -> FilterOwnership | None:
        """Return the stored record, or None when nothing is stored.

        Raises rather than returning None when a record exists and cannot be
        read or decoded.
        """

    def create(self, record: FilterOwnership) -> None:
        """Persist a first claim durably, only when nothing is stored.

        Raises `FileExistsError` when a record already exists. That is how
        ownership is serialized between processes: two that reconciled the same
        abandoned record both try to create, exactly one succeeds, and the other
        is told the scope was claimed underneath it rather than overwriting the
        winner's record. `save` would let both believe they owned the scope.
        """

    def save(self, record: FilterOwnership) -> None:
        """Persist `record`, replacing any earlier one.

        For phase changes to a record this owner created. Must be durable before
        returning, and must be called before the attach or detach it describes
        rather than after it.
        """

    def clear(self) -> None:
        """Remove the stored record.

        Only once the attachment it describes provably cannot exist: a
        deliberate release that was verified, or a reconciliation that
        established the owner is gone. Clearing a record whose owner is still
        running discards the only evidence that the scope is held.
        """
