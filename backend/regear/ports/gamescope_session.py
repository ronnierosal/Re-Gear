"""Port for exact Gamescope session observations."""

from __future__ import annotations

from typing import Protocol

from ..domain.gamescope_session import GamescopeSessionObservation


class GamescopeSessionObservationPort(Protocol):
    def observe(self) -> GamescopeSessionObservation: ...
