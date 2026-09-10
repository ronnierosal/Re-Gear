"""Ports for read-only peripheral observations."""

from __future__ import annotations

from typing import Protocol

from ..domain.peripheral_handoff import PeripheralObservation


class PeripheralObservationPort(Protocol):
    def observe(self) -> PeripheralObservation: ...
