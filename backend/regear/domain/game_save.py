"""Pure contracts for an intentionally verified, game-specific save action."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .game_compatibility import STEAM_APP_ID_RE


TOKEN_RE = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")


class GameSaveProofState(StrEnum):
    UNKNOWN = "unknown"
    UNVERIFIED = "unverified"
    VERIFIED = "verified"


@dataclass(frozen=True, slots=True)
class VerifiedGameSaveRecipe:
    """Backend-owned recipe identity backed by reviewed hardware evidence."""

    recipe_id: str
    evidence_id: str
    steam_app_id: str
    host_profile_id: str
    egpu_profile_id: str

    def __post_init__(self) -> None:
        if not STEAM_APP_ID_RE.fullmatch(self.steam_app_id):
            raise ValueError("verified save recipe Steam AppID is invalid")
        if any(
            not TOKEN_RE.fullmatch(value)
            for value in (
                self.recipe_id,
                self.evidence_id,
                self.host_profile_id,
                self.egpu_profile_id,
            )
        ):
            raise ValueError("verified save recipe identity is invalid")


@dataclass(frozen=True, slots=True)
class GameSaveProofObservation:
    state: GameSaveProofState
    generation: str
    sample_id: str

    def __post_init__(self) -> None:
        if not self.generation or not self.sample_id:
            raise ValueError("game-save proof identity is required")

    @property
    def exact(self) -> bool:
        return self.state is not GameSaveProofState.UNKNOWN
