"""Read-only discovery boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..domain.models import ObservedSnapshot


@dataclass(frozen=True, slots=True)
class DiscoveryTiming:
    stage: str
    duration_ms: float


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    snapshot: ObservedSnapshot
    timings: tuple[DiscoveryTiming, ...] = field(default_factory=tuple)


class DiscoveryPort(Protocol):
    def collect_snapshot(self) -> ObservedSnapshot:
        """Return one internally consistent observation snapshot."""


class TimedDiscoveryPort(DiscoveryPort, Protocol):
    def collect_snapshot_with_timings(self) -> DiscoveryResult:
        """Return one snapshot plus privacy-safe stage durations."""
