"""Narrow runtime boundaries for supervised Gamescope preparation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class UserServiceOperation(StrEnum):
    DAEMON_RELOAD = "daemon_reload"
    VERIFY_GAMESCOPE_UNIT = "verify_gamescope_unit"
    INSPECT_STEAM_UNIT = "inspect_steam_unit"
    OBSERVE_FILTER_GAMESCOPE = "observe_filter_gamescope"
    OBSERVE_FILTER_STEAM = "observe_filter_steam"
    RESTART_GAMESCOPE_SESSION = "restart_gamescope_session"
    #: The audio holders of an eGPU. `gamescope-session.target` does not reach
    #: them -- only the PipeWire sockets are wanted by it, so a session restart
    #: leaves WirePlumber running and still holding its descriptor -- and the
    #: domain already lists both in `APPROVED_EXPLICIT_RESTARTS`. Until these
    #: existed only an operator at a terminal could run them, which is why the
    #: disconnect could not be driven from the backend.
    RESTART_WIREPLUMBER = "restart_wireplumber"
    RESTART_PIPEWIRE = "restart_pipewire"


@dataclass(frozen=True, slots=True)
class GamescopeUserContext:
    username: str
    uid: int
    gid: int
    home: Path
    runtime_directory: Path
    bus_path: Path


@dataclass(frozen=True, slots=True)
class GamescopeUserResolution:
    context: GamescopeUserContext | None
    error_code: str = ""

    @property
    def ok(self) -> bool:
        return self.context is not None and not self.error_code


class CommandOutcome(Protocol):
    ok: bool


class UserServiceCommandPort(Protocol):
    def run(
        self,
        operation: UserServiceOperation,
        *,
        uid: int,
        username: str,
    ) -> CommandOutcome: ...


class IntegrationStatusView(Protocol):
    ready: bool
    shim_ready: bool
    error_code: str


class IntegrationResultView(Protocol):
    ok: bool
    changed: bool


class GamescopeIntegrationPort(Protocol):
    @property
    def user(self) -> GamescopeUserContext: ...

    def status(self) -> IntegrationStatusView: ...

    def activation_fingerprint(self) -> str: ...

    def preparation_fingerprint(self) -> str: ...

    def activate(self) -> IntegrationResultView: ...

    def deactivate(self) -> IntegrationResultView: ...

    def rollback_activation(self) -> IntegrationResultView: ...
