"""Port for detaching and re-enumerating an exact eGPU PCI function.

Separated from the planner so the decision to remove and the act of removing
stay reviewable apart from one another. An implementation writes to sysfs; the
domain never does.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class RemovalOutcome(StrEnum):
    REMOVED = "removed"
    STILL_PRESENT = "still_present"
    NOT_PRESENT = "not_present"
    REFUSED = "refused"
    FAILED = "failed"


class RescanOutcome(StrEnum):
    RESTORED = "restored"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RemovalResult:
    """The outcome of detaching one function, with the code that explains it."""

    address: str
    outcome: RemovalOutcome
    code: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome is RemovalOutcome.REMOVED


@dataclass(frozen=True, slots=True)
class RescanResult:
    """The outcome of asking the bus to re-enumerate."""

    outcome: RescanOutcome
    restored: tuple[str, ...] = ()
    code: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome is RescanOutcome.RESTORED


class DeviceRemovalPort(Protocol):
    """Detach an exact PCI function, and restore devices by bus rescan."""

    def remove(self, address: str) -> RemovalResult:
        """Detach exactly `address`, verifying it is gone afterwards."""

    def rescan(self, expected: tuple[str, ...]) -> RescanResult:
        """Re-enumerate the bus and report whether `expected` came back."""
