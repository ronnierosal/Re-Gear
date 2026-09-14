"""Private seams for the offline iGPU-on-TV lifecycle.

Collectors must bracket these observations into one coherent fresh sample.
The presenter owns only its own resources and must never restart Gamescope,
close/relaunch a game, or change the game's renderer. No native implementation
is currently supplied. These ports are not frontend RPC contracts.
"""
from dataclasses import dataclass
from typing import Protocol

from ..domain.game_session import GameSessionObservation
from ..domain.gamescope_session import GamescopeSessionObservation
from ..domain.igpu_tv_evidence import GameSessionEvidence, IgpuTvBinding
from .transition import MechanismResult, VersionedObservation


@dataclass(frozen=True, slots=True)
class IgpuTvObservation:
    current: VersionedObservation
    rendering: GameSessionEvidence
    game: GameSessionObservation
    gamescope: GamescopeSessionObservation


class IgpuTvObservationPort(Protocol):
    def observe(self) -> IgpuTvObservation | None: ...


class IgpuTvPresenterPort(Protocol):
    def present(self, binding: IgpuTvBinding, *, expected_generation: str) -> MechanismResult:
        """Success requires actual fresh original-session frames on this TV.

        An active connector alone is not proof of content. A real implementation
        must verify stream ownership and frame delivery, bound acquisition by a
        lease, and stop on frame stalls. Caller guards supplement this evidence.
        """
        ...

    def release(self, binding: IgpuTvBinding) -> MechanismResult:
        """Release only this presenter's resources; never tear down the game/session."""
        ...


class UnsupportedIgpuTvPresenter:
    def present(self, binding: IgpuTvBinding, *, expected_generation: str) -> MechanismResult:
        return MechanismResult(False, "igpu_tv.presenter_unavailable")

    def release(self, binding: IgpuTvBinding) -> MechanismResult:
        return MechanismResult(True, "igpu_tv.no_resources")
