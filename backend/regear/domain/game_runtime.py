"""Pure private runtime identity for one exact active Steam game."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .game_compatibility import STEAM_APP_ID_RE
from .game_session import SCOPE_RE


GENERATION_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_GAME_PROCESSES = 128


class GameRuntimeKind(StrEnum):
    NATIVE = "native"
    PROTON = "proton"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class GameProcessInstance:
    """PID-reuse-resistant private process identity."""

    pid: int
    start_time_ticks: int
    parent_pid: int
    executable_name: str
    proton_marker: bool

    def __post_init__(self) -> None:
        if self.pid <= 0 or self.parent_pid < 0 or self.start_time_ticks <= 0:
            raise ValueError("game process identity is invalid")
        if (
            not self.executable_name
            or len(self.executable_name) > 255
            or any(value in self.executable_name for value in ("\0", "/", "\\"))
            or any(ord(value) < 32 for value in self.executable_name)
        ):
            raise ValueError("game executable name is invalid")


@dataclass(frozen=True, slots=True)
class ActiveGameRuntimeObservation:
    """Exact private process graph, or one categorical fail-closed result."""

    steam_app_id: str
    scopes: tuple[str, ...]
    processes: tuple[GameProcessInstance, ...]
    runtime_kind: GameRuntimeKind
    generation: str
    sample_id: str
    complete: bool
    error_code: str = ""

    def __post_init__(self) -> None:
        if not STEAM_APP_ID_RE.fullmatch(self.steam_app_id):
            raise ValueError("game runtime Steam AppID is invalid")
        if (
            not self.scopes
            or len(self.scopes) > 16
            or len(self.scopes) != len(set(self.scopes))
            or any(not SCOPE_RE.fullmatch(scope) for scope in self.scopes)
        ):
            raise ValueError("game runtime scopes are invalid")
        if len(self.processes) > MAX_GAME_PROCESSES:
            raise ValueError("game runtime process count is invalid")
        identities = tuple(
            (process.pid, process.start_time_ticks) for process in self.processes
        )
        if len(identities) != len(set(identities)):
            raise ValueError("game runtime process identity is duplicated")
        if not GENERATION_RE.fullmatch(self.generation) or not GENERATION_RE.fullmatch(
            self.sample_id
        ):
            raise ValueError("game runtime observation identity is invalid")
        if self.complete:
            if not self.processes or self.error_code:
                raise ValueError("complete game runtime evidence is inconsistent")
            expected = (
                GameRuntimeKind.PROTON
                if any(process.proton_marker for process in self.processes)
                else GameRuntimeKind.NATIVE
            )
            if self.runtime_kind is not expected:
                raise ValueError("game runtime classification conflicts with evidence")
        elif (
            self.processes
            or self.runtime_kind is not GameRuntimeKind.UNKNOWN
            or not self.error_code
        ):
            raise ValueError("incomplete game runtime evidence must fail closed")

    @property
    def exact(self) -> bool:
        return self.complete and bool(self.processes)

    @property
    def root_processes(self) -> tuple[GameProcessInstance, ...]:
        pids = {process.pid for process in self.processes}
        return tuple(
            process for process in self.processes if process.parent_pid not in pids
        )
