"""Read-only exact internal-render baseline capture for Compatibility Test Mode."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from ..domain.compatibility_test import CompatibilityBaseline
from ..domain.control_plane import PlacementState
from ..domain.game_compatibility import ObservedRenderGpu
from ..domain.game_render_activity import (
    GameRenderActivityEvidence,
    GameRenderActivityStatus,
)
from ..domain.game_session import ActiveGameIdentity, GameSessionObservation
from ..domain.models import GameState


CODE_RE = re.compile(r"^[a-z0-9_.-]{1,96}$")
_INTERNAL_PLACEMENTS = {
    PlacementState.PORTABLE,
    PlacementState.BOOSTED_HANDHELD,
    PlacementState.DOCKED_IGPU,
}


class GameSessionPort(Protocol):
    def observe(self) -> GameSessionObservation: ...


class InternalRenderEvidencePort(Protocol):
    def observe(
        self, identity: ActiveGameIdentity, *, user_uid: int
    ) -> GameRenderActivityEvidence: ...


@dataclass(frozen=True, slots=True)
class CompatibilityBaselineCapture:
    """Private application result; no delivery mapper may expose its identity."""

    accepted: bool
    code: str
    baseline: CompatibilityBaseline | None = None

    def __post_init__(self) -> None:
        if not CODE_RE.fullmatch(self.code):
            raise ValueError("compatibility baseline capture code is invalid")
        if self.accepted != (self.baseline is not None):
            raise ValueError("compatibility baseline capture state is invalid")


class CompatibilityBaselineCollector:
    """Collect one exact internal-render baseline without changing system state."""

    def __init__(
        self, *, sessions: GameSessionPort, internal_renderer: InternalRenderEvidencePort
    ) -> None:
        self._sessions = sessions
        self._internal_renderer = internal_renderer

    def capture(self, *, user_uid: int) -> CompatibilityBaselineCapture:
        if user_uid <= 0 or user_uid > 2_147_483_647:
            return self._rejected("compatibility.baseline_user_unverified")
        before = self._session()
        if not self._exact_running(before):
            return self._rejected("compatibility.baseline_game_unverified")
        assert before is not None and before.identity is not None
        evidence = self._render(before.identity, user_uid)
        if (
            evidence is None
            or evidence.status is not GameRenderActivityStatus.ACTIVE
            or not evidence.evidence_generation
        ):
            return self._rejected("compatibility.baseline_internal_render_unverified")
        if evidence.placement not in _INTERNAL_PLACEMENTS:
            return self._rejected("compatibility.baseline_internal_placement_unverified")
        after = self._session()
        if not self._same_session(before, after):
            return self._rejected("compatibility.baseline_game_changed")
        return CompatibilityBaselineCapture(
            True,
            "compatibility.baseline_captured",
            CompatibilityBaseline(
                evidence.evidence_generation,
                evidence.placement,
                GameState.RUNNING,
                before.identity.steam_app_id,
                ObservedRenderGpu.INTERNAL,
            ),
        )

    def _session(self) -> GameSessionObservation | None:
        try:
            return self._sessions.observe()
        except Exception:
            return None

    def _render(
        self, identity: ActiveGameIdentity, user_uid: int
    ) -> GameRenderActivityEvidence | None:
        try:
            return self._internal_renderer.observe(identity, user_uid=user_uid)
        except Exception:
            return None

    @staticmethod
    def _exact_running(session: GameSessionObservation | None) -> bool:
        return bool(
            session is not None
            and session.state is GameState.RUNNING
            and session.exact
            and session.identity is not None
        )

    @staticmethod
    def _same_session(
        before: GameSessionObservation, after: GameSessionObservation | None
    ) -> bool:
        return bool(
            after is not None
            and after.exact
            and after.state is GameState.RUNNING
            and after.identity == before.identity
            and after.generation == before.generation
            and after.sample_id != before.sample_id
        )

    @staticmethod
    def _rejected(code: str) -> CompatibilityBaselineCapture:
        return CompatibilityBaselineCapture(False, code)
