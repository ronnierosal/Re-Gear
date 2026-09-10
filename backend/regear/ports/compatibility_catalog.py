"""Private persistence port for reviewed compatibility records."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol

from ..domain.game_compatibility import GameCompatibilityRecord
from ..domain.hardware_compatibility import HardwareCompatibilityRecord


class CompatibilityCatalogPort(Protocol):
    def update_games(
        self,
        update: Callable[
            [tuple[GameCompatibilityRecord, ...]], Iterable[GameCompatibilityRecord]
        ],
    ) -> tuple[GameCompatibilityRecord, ...]: ...

    def update_hardware(
        self,
        update: Callable[
            [tuple[HardwareCompatibilityRecord, ...]], Iterable[HardwareCompatibilityRecord]
        ],
    ) -> tuple[HardwareCompatibilityRecord, ...]: ...
