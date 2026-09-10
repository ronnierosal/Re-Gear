"""Dormant compatibility-test consumer of exact DRM activity evidence."""

from __future__ import annotations

from typing import Protocol

from ..domain.compatibility_test import (
    CompatibilityTestSession,
    CompatibilityTestStage,
    record_egpu_handoff_result,
    require_compatibility_action,
)
from ..domain.control_plane import PlacementState
from ..domain.game_compatibility import EgpuHandoffStatus, ObservedRenderGpu
from ..domain.game_render_activity import (
    GameRenderActivityEvidence,
    GameRenderActivityStatus,
)
from ..domain.game_session import ActiveGameIdentity, GameSessionObservation
from ..domain.models import GameState


class RenderEvidencePort(Protocol):
    def observe(
        self, identity: ActiveGameIdentity, *, user_uid: int
    ) -> GameRenderActivityEvidence: ...


class GameSessionPort(Protocol):
    def observe(self) -> GameSessionObservation: ...


class CompatibilityRenderEvidenceCollector:
    """Record evidence only; catalog promotion still requires explicit review."""

    def __init__(self, renderer: RenderEvidencePort) -> None:
        self._renderer = renderer

    def record_external_handoff(
        self,
        session: CompatibilityTestSession,
        identity: ActiveGameIdentity,
        *,
        user_uid: int,
        now_ms: int,
    ) -> CompatibilityTestSession:
        baseline = session.baseline
        if (
            baseline is None
            or baseline.steam_app_id != identity.steam_app_id
            or baseline.render_gpu is not ObservedRenderGpu.INTERNAL
        ):
            return require_compatibility_action(
                session,
                "compatibility.render_baseline_mismatch",
                now_ms=now_ms,
            )
        try:
            evidence = self._renderer.observe(identity, user_uid=user_uid)
        except Exception:
            evidence = None
        if evidence is None or evidence.status is not GameRenderActivityStatus.ACTIVE:
            return require_compatibility_action(
                session,
                "compatibility.external_render_unverified",
                now_ms=now_ms,
            )
        if evidence.placement is not PlacementState.DOCKED_EGPU:
            return require_compatibility_action(
                session,
                "compatibility.external_placement_unverified",
                now_ms=now_ms,
            )
        return record_egpu_handoff_result(
            session,
            status=EgpuHandoffStatus.VERIFIED,
            observed_render_gpu=ObservedRenderGpu.EXTERNAL,
            observation_generation=evidence.evidence_generation,
            now_ms=now_ms,
        )


class CompatibilityExternalHandoffCollector:
    """Bracket an external-render sample with one exact stable Steam session."""

    def __init__(
        self,
        *,
        sessions: GameSessionPort,
        render_collector: CompatibilityRenderEvidenceCollector,
    ) -> None:
        self._sessions = sessions
        self._render_collector = render_collector

    def capture_external_handoff(
        self,
        session: CompatibilityTestSession,
        *,
        user_uid: int,
        now_ms: int,
    ) -> CompatibilityTestSession:
        if user_uid <= 0 or user_uid > 2_147_483_647:
            return require_compatibility_action(
                session, "compatibility.external_user_unverified", now_ms=now_ms
            )
        before = self._session()
        if not self._exact_running(before):
            return require_compatibility_action(
                session, "compatibility.external_game_unverified", now_ms=now_ms
            )
        assert before is not None and before.identity is not None
        result = self._render_collector.record_external_handoff(
            session, before.identity, user_uid=user_uid, now_ms=now_ms
        )
        if result.stage is CompatibilityTestStage.ACTION_REQUIRED:
            return result
        after = self._session()
        if not self._same_session(before, after):
            return require_compatibility_action(
                result, "compatibility.external_game_changed", now_ms=now_ms
            )
        return result

    def _session(self) -> GameSessionObservation | None:
        try:
            return self._sessions.observe()
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
