"""Read-only private active-game runtime observation boundary."""

from __future__ import annotations

from typing import Protocol

from ..domain.game_runtime import ActiveGameRuntimeObservation
from ..domain.game_session import ActiveGameIdentity


class GameRuntimeObservationPort(Protocol):
    def observe(
        self, identity: ActiveGameIdentity, *, user_uid: int
    ) -> ActiveGameRuntimeObservation: ...
