"""Read-only active game-session observation boundary."""

from __future__ import annotations

from typing import Protocol

from ..domain.game_session import GameSessionObservation


class GameSessionObservationPort(Protocol):
    def observe(self) -> GameSessionObservation: ...
