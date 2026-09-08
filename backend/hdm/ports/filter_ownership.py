"""Port for durably storing one device-filter ownership record.

Separated from the domain so composing or reconciling a record cannot write to
the live system, matching how the transition journal is arranged.

An implementation must survive the death of the process that wrote it -- that
is the entire purpose. A store that lives in memory, or under a path cleared on
reboot, satisfies the type and defeats the point: the record exists so a later
reader can tell a crashed filter apart from one that was never armed.

`load` returning None means no record, which is a different thing from a record
that reconciles as released. Callers must not collapse the two: the first says
nothing was ever claimed, the second says an owner ended its claim deliberately.
"""

from __future__ import annotations

from typing import Protocol

from ..domain.filter_ownership import FilterOwnership


class FilterOwnershipStore(Protocol):
    """Durably hold at most one ownership record."""

    def load(self) -> FilterOwnership | None:
        """Return the stored record, or None when nothing is stored."""

    def save(self, record: FilterOwnership) -> None:
        """Persist `record`, replacing any earlier one.

        Must be durable before returning. A caller writes the claim before
        attaching a filter, so a save that is still buffered when the process
        dies produces exactly the silent gap this record exists to close.
        """

    def clear(self) -> None:
        """Remove the stored record.

        Only for a record whose lifecycle has genuinely ended. Clearing an
        armed record discards the evidence that a filter is attached, leaving
        an attached filter nothing describes.
        """
