"""Registry, proof, and mechanism boundaries for verified game saves."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from ..domain.game_save import GameSaveProofObservation, VerifiedGameSaveRecipe
from ..domain.game_session import ActiveGameIdentity


@dataclass(frozen=True, slots=True)
class GameSaveMechanismResult:
    accepted: bool
    code: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9_.-]{1,64}", self.code):
            raise ValueError("game-save result code must be categorical")


class VerifiedGameSaveRecipePort(Protocol):
    def resolve(
        self,
        *,
        steam_app_id: str,
        host_profile_id: str,
        egpu_profile_id: str,
    ) -> VerifiedGameSaveRecipe | None:
        """Return one backend-owned reviewed recipe for the exact profile tuple."""


class GameSaveProofObservationPort(Protocol):
    def observe(
        self,
        recipe: VerifiedGameSaveRecipe,
        identity: ActiveGameIdentity,
    ) -> GameSaveProofObservation: ...


class GameSaveMechanismPort(Protocol):
    def request_save(
        self,
        recipe: VerifiedGameSaveRecipe,
        identity: ActiveGameIdentity,
    ) -> GameSaveMechanismResult:
        """Request only the typed recipe selected by the backend registry."""
