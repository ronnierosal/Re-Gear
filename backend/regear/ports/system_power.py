"""Narrow system-power boundary for the shutdown-before-disconnect workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PowerOffResult:
    requested: bool
    code: str


class SystemPowerPort(Protocol):
    def request_poweroff(self) -> PowerOffResult:
        """Queue one ordinary system power-off request without waiting for exit."""
