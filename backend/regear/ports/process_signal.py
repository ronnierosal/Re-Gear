"""Typed process-signal boundary for guarded release and deterministic replay."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Protocol

from ..domain.process_release import ProcessReleaseTarget


class ProcessSignalAction(StrEnum):
    GRACEFUL_TERMINATE = "graceful_terminate"
    FORCE_TERMINATE = "force_terminate"


@dataclass(frozen=True, slots=True)
class ProcessSignalResult:
    accepted: bool
    code: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9_.-]{1,64}", self.code):
            raise ValueError("process signal result code must be categorical")


class ProcessSignalPort(Protocol):
    def capability_code(self) -> str:
        """Return an empty string when exact-instance signaling is available."""

    def signal(
        self, target: ProcessReleaseTarget, action: ProcessSignalAction
    ) -> ProcessSignalResult:
        """Request one typed signal for one already-approved exact target."""
