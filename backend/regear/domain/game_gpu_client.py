"""Pure categorical evidence that an exact game holds an eGPU render node."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .game_runtime import GameRuntimeKind


REASON_RE = re.compile(r"^[a-z0-9_.-]{1,96}$")


class GameEgpuClientStatus(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class GameEgpuClientEvidence:
    status: GameEgpuClientStatus
    runtime_kind: GameRuntimeKind
    matched_process_count: int
    reason_code: str

    def __post_init__(self) -> None:
        if not 0 <= self.matched_process_count <= 128:
            raise ValueError("game eGPU client match count is invalid")
        if not REASON_RE.fullmatch(self.reason_code):
            raise ValueError("game eGPU client reason must be categorical")
        if self.status is GameEgpuClientStatus.PRESENT:
            if self.matched_process_count <= 0:
                raise ValueError("present eGPU client evidence requires a match")
            if self.runtime_kind is GameRuntimeKind.UNKNOWN:
                raise ValueError("present eGPU client evidence requires exact runtime")
        elif self.matched_process_count:
            raise ValueError("non-present eGPU client evidence cannot carry matches")
        if (
            self.status is GameEgpuClientStatus.ABSENT
            and self.runtime_kind is GameRuntimeKind.UNKNOWN
        ):
            raise ValueError("absent eGPU client evidence requires exact runtime")

    @property
    def proves_rendering_gpu(self) -> bool:
        """Holding a render node never proves active rendering."""
        return False
