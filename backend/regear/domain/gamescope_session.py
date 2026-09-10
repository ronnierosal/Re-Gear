"""Exact, privacy-safe identity for one Gamescope session generation."""

from __future__ import annotations

import re
from dataclasses import dataclass


CODE_RE = re.compile(r"^[a-z0-9_.-]{1,96}$")
GENERATION_RE = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True, slots=True)
class GamescopeSessionObservation:
    exact: bool
    code: str
    generation: str = ""

    def __post_init__(self) -> None:
        if not CODE_RE.fullmatch(self.code):
            raise ValueError("Gamescope session code must be categorical")
        if self.exact != bool(GENERATION_RE.fullmatch(self.generation)):
            raise ValueError("Gamescope session identity is inconsistent")
