"""Observation and mechanism boundaries for guarded game close."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from ..domain.game_session import ActiveGameIdentity


@dataclass(frozen=True, slots=True)
class GameCloseMechanismResult:
    accepted: bool
    code: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9_.-]{1,64}", self.code):
            raise ValueError("game-close result code must be categorical")


class GameCloseMechanismPort(Protocol):
    def request_close(
        self, identity: ActiveGameIdentity
    ) -> GameCloseMechanismResult:
        """Request graceful close of one exact active game identity."""
