"""Pure exact game-session identity for guarded close workflows."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .game_compatibility import STEAM_APP_ID_RE
from .models import GameState


SCOPE_RE = re.compile(r"^[A-Za-z0-9_.:@\\-]{1,200}\.scope$")


@dataclass(frozen=True, slots=True)
class ActiveGameIdentity:
    steam_app_id: str
    scopes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not STEAM_APP_ID_RE.fullmatch(self.steam_app_id):
            raise ValueError("active game Steam AppID is invalid")
        if not self.scopes or len(self.scopes) > 16:
            raise ValueError("active game scope count is invalid")
        if len(self.scopes) != len(set(self.scopes)) or any(
            not SCOPE_RE.fullmatch(scope) for scope in self.scopes
        ):
            raise ValueError("active game scope identity is invalid")


@dataclass(frozen=True, slots=True)
class GameSessionObservation:
    state: GameState
    generation: str
    sample_id: str
    identity: ActiveGameIdentity | None = None

    def __post_init__(self) -> None:
        if not self.generation or not self.sample_id:
            raise ValueError("game-session observation identity is required")
        if self.identity is not None and self.state is not GameState.RUNNING:
            raise ValueError("game-session state and identity conflict")

    @property
    def exact(self) -> bool:
        return self.state is not GameState.UNKNOWN and (
            self.state is GameState.IDLE or self.identity is not None
        )
