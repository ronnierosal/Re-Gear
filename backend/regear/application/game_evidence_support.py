"""One-shot privacy-safe composition of exact running-game GPU evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from collections.abc import Callable
from typing import Protocol

from ..domain.control_plane import PlacementState
from ..domain.game_gpu_client import (
    GameEgpuClientEvidence,
    GameEgpuClientStatus,
)
from ..domain.game_render_activity import (
    MAX_ENGINE_CLIENTS,
    MAX_ENGINES_PER_CLIENT,
    GameRenderActivityEvidence,
    GameRenderActivityStatus,
)
from ..domain.game_runtime import GameRuntimeKind
from ..domain.game_session import GameSessionObservation
from ..domain.models import GameState
from .game_render_activity import GameRenderActivityComparison


REASON_RE = re.compile(r"^[a-z0-9_.-]{1,96}$")


class GameSessionPort(Protocol):
    def observe(self) -> GameSessionObservation: ...


class GameEgpuClientEvidencePort(Protocol):
    def observe(self, identity, *, user_uid: int) -> GameEgpuClientEvidence: ...


class GameRenderActivityComparisonPort(Protocol):
    def observe(self, identity, *, user_uid: int) -> GameRenderActivityComparison: ...


@dataclass(frozen=True, slots=True)
class SupportRenderEvidence:
    status: GameRenderActivityStatus
    runtime_kind: GameRuntimeKind
    active_engine_count: int
    reason_code: str
    placement: PlacementState

    def __post_init__(self) -> None:
        if not 0 <= self.active_engine_count <= (
            MAX_ENGINE_CLIENTS * MAX_ENGINES_PER_CLIENT
        ) or not REASON_RE.fullmatch(self.reason_code):
            raise ValueError("support render evidence is invalid")


@dataclass(frozen=True, slots=True)
class SupportGameEvidence:
    game_state: GameState
    identity_exact: bool
    egpu_client_status: GameEgpuClientStatus
    egpu_client_count: int
    egpu_client_reason: str
    internal_render: SupportRenderEvidence
    external_render: SupportRenderEvidence

    def __post_init__(self) -> None:
        if not 0 <= self.egpu_client_count <= 128 or not REASON_RE.fullmatch(
            self.egpu_client_reason
        ):
            raise ValueError("support game evidence is invalid")
        if self.identity_exact and self.game_state is not GameState.RUNNING:
            raise ValueError("exact support game identity requires a running game")


class SupportGameEvidenceService:
    """Collect bounded evidence only after one exact game identity is observed."""

    def __init__(
        self,
        *,
        sessions: GameSessionPort,
        egpu_clients: GameEgpuClientEvidencePort,
        render_comparison: GameRenderActivityComparisonPort,
        user_uid: int,
        verify_user: Callable[[int], bool],
    ) -> None:
        self._sessions = sessions
        self._egpu_clients = egpu_clients
        self._render_comparison = render_comparison
        self._user_uid = user_uid
        self._verify_user = verify_user

    def observe(self) -> SupportGameEvidence:
        try:
            session = self._sessions.observe()
        except Exception:
            return self._unavailable(GameState.UNKNOWN, "game_evidence.session_unavailable")
        if session.state is not GameState.RUNNING or session.identity is None:
            code = (
                "game_evidence.game_idle"
                if session.state is GameState.IDLE
                else "game_evidence.identity_unverified"
            )
            return self._unavailable(session.state, code)
        if self._user_uid <= 0 or self._user_uid > 2_147_483_647:
            return self._unavailable(
                GameState.RUNNING, "game_evidence.user_unverified"
            )
        if not self._user_is_current():
            return self._unavailable(
                GameState.RUNNING, "game_evidence.user_unverified"
            )
        identity = session.identity
        clients = self._client_evidence(identity)
        comparison = self._render_evidence(identity)
        internal = comparison.internal
        external = comparison.external
        if not self._session_is_stable(session):
            return self._unavailable(
                GameState.RUNNING, "game_evidence.game_changed"
            )
        if not self._user_is_current():
            return self._unavailable(
                GameState.RUNNING, "game_evidence.user_changed"
            )
        known_placements = {
            value.placement
            for value in (internal, external)
            if value.status is not GameRenderActivityStatus.UNKNOWN
        }
        if len(known_placements) > 1:
            return self._unavailable(
                GameState.RUNNING, "game_evidence.placement_changed"
            )
        runtime_kinds = {
            value
            for value in (
                clients.runtime_kind,
                internal.runtime_kind,
                external.runtime_kind,
            )
            if value is not GameRuntimeKind.UNKNOWN
        }
        if len(runtime_kinds) > 1:
            return self._unavailable(
                GameState.RUNNING, "game_evidence.runtime_changed"
            )
        return SupportGameEvidence(
            game_state=GameState.RUNNING,
            identity_exact=True,
            egpu_client_status=clients.status,
            egpu_client_count=clients.matched_process_count,
            egpu_client_reason=clients.reason_code,
            internal_render=self._support_render(internal),
            external_render=self._support_render(external),
        )

    def _user_is_current(self) -> bool:
        try:
            return self._verify_user(self._user_uid) is True
        except Exception:
            return False

    def _session_is_stable(self, before: GameSessionObservation) -> bool:
        try:
            after = self._sessions.observe()
        except Exception:
            return False
        return bool(
            after.exact
            and after.identity == before.identity
            and after.generation == before.generation
            and after.sample_id != before.sample_id
        )

    def _client_evidence(self, identity) -> GameEgpuClientEvidence:
        try:
            return self._egpu_clients.observe(identity, user_uid=self._user_uid)
        except Exception:
            return GameEgpuClientEvidence(
                GameEgpuClientStatus.UNKNOWN,
                GameRuntimeKind.UNKNOWN,
                0,
                "game_evidence.egpu_client_unavailable",
            )

    def _render_evidence(self, identity) -> GameRenderActivityComparison:
        try:
            return self._render_comparison.observe(
                identity, user_uid=self._user_uid
            )
        except Exception:
            unknown = GameRenderActivityEvidence(
                GameRenderActivityStatus.UNKNOWN,
                GameRuntimeKind.UNKNOWN,
                0,
                "game_evidence.render_unavailable",
            )
            return GameRenderActivityComparison(unknown, unknown)

    @staticmethod
    def _support_render(value: GameRenderActivityEvidence) -> SupportRenderEvidence:
        return SupportRenderEvidence(
            status=value.status,
            runtime_kind=value.runtime_kind,
            active_engine_count=value.active_engine_count,
            reason_code=value.reason_code,
            placement=value.placement,
        )

    @classmethod
    def _unavailable(cls, state: GameState, code: str) -> SupportGameEvidence:
        unknown = SupportRenderEvidence(
            GameRenderActivityStatus.UNKNOWN,
            GameRuntimeKind.UNKNOWN,
            0,
            code,
            PlacementState.UNKNOWN,
        )
        return SupportGameEvidence(
            game_state=state,
            identity_exact=False,
            egpu_client_status=GameEgpuClientStatus.UNKNOWN,
            egpu_client_count=0,
            egpu_client_reason=code,
            internal_render=unknown,
            external_render=unknown,
        )
