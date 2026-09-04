"""Shared manual/automatic TDP provider and recovery-journal boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


TdpDispatchGuard = Callable[[], bool]


class TdpDispatchRejected(Exception):
    """Raised only before invoking the power-setting subprocess."""


@dataclass(frozen=True, slots=True)
class TdpRegister:
    current: int
    minimum: int
    maximum: int

    def __post_init__(self) -> None:
        if any(type(v) is not int or not 0 < v <= 0xFFFFFFFF for v in (self.current, self.minimum, self.maximum)):
            raise ValueError("TDP register must contain positive unsigned integers")
        if not self.minimum <= self.current <= self.maximum:
            raise ValueError("TDP register is outside reported bounds")


@dataclass(frozen=True, slots=True)
class TdpReading:
    binding: str
    sustained: TdpRegister
    slow: TdpRegister
    fast: TdpRegister

    def __post_init__(self) -> None:
        if not isinstance(self.binding, str) or not self.binding:
            raise ValueError("TDP reading needs an opaque provider binding")

    @property
    def values(self) -> tuple[int, int, int]:
        return self.sustained.current, self.slow.current, self.fast.current

    def target_values(self, watts: int) -> tuple[int, int, int]:
        """SteamOS Manager ASUS mapping, including distinct boost minimums."""
        if type(watts) is not int or not self.sustained.minimum <= watts <= self.sustained.maximum:
            raise ValueError("TDP request outside sustained range")
        slow = max(watts, self.slow.minimum)
        fast = max(watts, self.fast.minimum)
        if slow > self.slow.maximum or fast > self.fast.maximum:
            raise ValueError("TDP request outside boost ranges")
        return watts, slow, fast

    def same_context(self, other: TdpReading) -> bool:
        return self.binding == other.binding and all(
            (a.minimum, a.maximum) == (b.minimum, b.maximum)
            for a, b in zip((self.sustained, self.slow, self.fast), (other.sustained, other.slow, other.fast))
        )


@dataclass(frozen=True, slots=True)
class TdpObservation:
    code: str
    reading: TdpReading | None = None


@dataclass(frozen=True, slots=True)
class TdpWriteOutcome:
    attempted: bool
    accepted: bool
    code: str


class TdpProvider(Protocol):
    def observe(self) -> TdpObservation: ...
    def set_limit(self, expected: TdpReading, watts: int, *, dispatch_guard: TdpDispatchGuard | None = None) -> TdpWriteOutcome:
        """Freshly revalidate the expected reading and ownership before enqueueing."""
        ...


@dataclass(frozen=True, slots=True)
class TdpSessionRecord:
    baseline: TdpReading
    applied: TdpReading
    phase: str = "active"
    pending_watts: int | None = None

    def __post_init__(self) -> None:
        if not self.baseline.same_context(self.applied):
            raise ValueError("TDP journal contexts differ")
        if self.phase not in ("active", "pending"):
            raise ValueError("TDP journal phase is invalid")
        if self.phase == "active" and self.pending_watts is not None:
            raise ValueError("Active TDP journal cannot carry a pending write")
        if self.phase == "pending":
            self.applied.target_values(self.pending_watts)


class TdpJournal(Protocol):
    """Production implementations must persist atomically before a write attempt."""
    def load(self) -> TdpSessionRecord | None: ...
    def save(self, record: TdpSessionRecord | None) -> None: ...
