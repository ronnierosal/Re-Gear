"""Bounded read-only watcher for natural exit from exact Docked-iGPU play."""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum

from ..domain.control_plane import PlacementState
from ..domain.game_session import ActiveGameIdentity, GameSessionObservation
from ..domain.gamescope_session import GamescopeSessionObservation
from ..domain.inference import infer_placement
from ..domain.models import GameState
from ..ports.game_session import GameSessionObservationPort
from ..ports.gamescope_session import GamescopeSessionObservationPort
from ..ports.transition import MonotonicClockPort, TransitionObservationPort
from ..profiles.registry import resolve_runtime_profiles


WATCH_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{8,96}$")
REASON_RE = re.compile(r"^[a-z0-9_.-]{1,96}$")
MAX_WATCH_TTL_MS = 24 * 60 * 60 * 1000


class DockedIgpuExitStage(StrEnum):
    WATCHING = "watching"
    PROMOTION_READY = "promotion_ready"
    CANCELLED = "cancelled"
    ACTION_REQUIRED = "action_required"


@dataclass(frozen=True, slots=True)
class DockedIgpuExitWatch:
    watch_id: str
    stage: DockedIgpuExitStage
    game: ActiveGameIdentity
    host_profile_id: str
    egpu_profile_id: str
    egpu_stable_id: str
    armed_snapshot_generation: str
    armed_snapshot_sample_id: str
    armed_game_generation: str
    gamescope_session_generation: str
    armed_at_ms: int
    expires_at_ms: int
    reason_code: str
    ready_snapshot_generation: str = ""

    def __post_init__(self) -> None:
        if not WATCH_ID_RE.fullmatch(self.watch_id):
            raise ValueError("Docked-iGPU watch ID is invalid")
        if not all(
            (
                self.host_profile_id,
                self.egpu_profile_id,
                self.egpu_stable_id,
                self.armed_snapshot_generation,
                self.armed_snapshot_sample_id,
                self.armed_game_generation,
                self.gamescope_session_generation,
            )
        ):
            raise ValueError("Docked-iGPU watch evidence is incomplete")
        if not REASON_RE.fullmatch(self.reason_code):
            raise ValueError("Docked-iGPU watch reason must be categorical")
        if self.armed_at_ms < 0 or self.expires_at_ms <= self.armed_at_ms:
            raise ValueError("Docked-iGPU watch deadline is invalid")
        if self.stage is DockedIgpuExitStage.PROMOTION_READY:
            if not self.ready_snapshot_generation:
                raise ValueError("ready Docked-iGPU watch lacks fresh evidence")
        elif self.ready_snapshot_generation:
            raise ValueError("non-ready Docked-iGPU watch carries ready evidence")

    @property
    def terminal(self) -> bool:
        return self.stage is not DockedIgpuExitStage.WATCHING

    @property
    def target(self) -> PlacementState | None:
        return (
            PlacementState.DOCKED_EGPU
            if self.stage is DockedIgpuExitStage.PROMOTION_READY
            else None
        )


@dataclass(frozen=True, slots=True)
class DockedIgpuExitArmResult:
    accepted: bool
    code: str
    watch: DockedIgpuExitWatch | None = None

    def __post_init__(self) -> None:
        if not REASON_RE.fullmatch(self.code):
            raise ValueError("Docked-iGPU arm result code must be categorical")
        if self.accepted != (self.watch is not None):
            raise ValueError("Docked-iGPU arm result is inconsistent")


class DockedIgpuGameExitWatcher:
    def __init__(
        self,
        *,
        snapshots: TransitionObservationPort,
        games: GameSessionObservationPort,
        gamescope_sessions: GamescopeSessionObservationPort,
        clock: MonotonicClockPort,
        ttl_ms: int = 12 * 60 * 60 * 1000,
        watch_id_factory: Callable[[], str] | None = None,
    ) -> None:
        if ttl_ms <= 0 or ttl_ms > MAX_WATCH_TTL_MS:
            raise ValueError("Docked-iGPU watch TTL is invalid")
        self._snapshots = snapshots
        self._games = games
        self._gamescope_sessions = gamescope_sessions
        self._clock = clock
        self._ttl_ms = ttl_ms
        self._watch_id_factory = watch_id_factory or (
            lambda: f"docked-igpu-watch-{secrets.token_hex(8)}"
        )

    def arm(self) -> DockedIgpuExitArmResult:
        game = self._game()
        now = self._now()
        if game is None or now is None:
            return DockedIgpuExitArmResult(False, "docked_igpu.observation_unavailable")
        if not game.exact:
            return DockedIgpuExitArmResult(False, "docked_igpu.game_identity_unverified")
        if game.state is GameState.IDLE:
            return DockedIgpuExitArmResult(False, "docked_igpu.game_not_running")
        if game.state is not GameState.RUNNING or game.identity is None:
            return DockedIgpuExitArmResult(False, "docked_igpu.game_identity_unverified")
        gamescope_session = self._gamescope_session()
        snapshot = self._snapshot()
        game_after = self._game()
        gamescope_session_after = self._gamescope_session()
        if (
            snapshot is None
            or game_after is None
            or gamescope_session is None
            or gamescope_session_after is None
        ):
            return DockedIgpuExitArmResult(False, "docked_igpu.observation_unavailable")
        if not gamescope_session.exact or not gamescope_session_after.exact:
            return DockedIgpuExitArmResult(
                False, "docked_igpu.gamescope_identity_unverified"
            )
        if gamescope_session.generation != gamescope_session_after.generation:
            return DockedIgpuExitArmResult(False, "docked_igpu.gamescope_changed")
        if not snapshot.generation or not snapshot.sample_id:
            return DockedIgpuExitArmResult(False, "docked_igpu.snapshot_unavailable")
        if (
            not game.exact
            or not game_after.exact
            or game.generation != game_after.generation
            or game.sample_id == game_after.sample_id
            or game.identity != game_after.identity
        ):
            return DockedIgpuExitArmResult(False, "docked_igpu.game_identity_changed")
        if infer_placement(snapshot.snapshot) is not PlacementState.DOCKED_IGPU:
            return DockedIgpuExitArmResult(False, "docked_igpu.placement_unverified")
        if snapshot.snapshot.game_state is not GameState.RUNNING:
            return DockedIgpuExitArmResult(False, "docked_igpu.game_not_running")
        profiles = resolve_runtime_profiles(snapshot.snapshot)
        if not profiles.exact_host or not profiles.exact_egpu:
            return DockedIgpuExitArmResult(False, "docked_igpu.profile_unverified")
        watch_id = self._watch_id_factory()
        if not WATCH_ID_RE.fullmatch(watch_id):
            return DockedIgpuExitArmResult(False, "docked_igpu.watch_identity_invalid")
        watch = DockedIgpuExitWatch(
            watch_id=watch_id,
            stage=DockedIgpuExitStage.WATCHING,
            game=game.identity,
            host_profile_id=profiles.capabilities.host_profile_id,
            egpu_profile_id=profiles.capabilities.egpu_profile_id,
            egpu_stable_id=profiles.egpu_stable_id,
            armed_snapshot_generation=snapshot.generation,
            armed_snapshot_sample_id=snapshot.sample_id,
            armed_game_generation=game.generation,
            gamescope_session_generation=gamescope_session.generation,
            armed_at_ms=now,
            expires_at_ms=now + self._ttl_ms,
            reason_code="docked_igpu.watching_game_exit",
        )
        return DockedIgpuExitArmResult(True, "docked_igpu.watch_armed", watch)

    def poll(self, watch: DockedIgpuExitWatch) -> DockedIgpuExitWatch:
        if watch.terminal:
            return watch
        now = self._now()
        if now is None:
            return self._action(watch, "docked_igpu.clock_unavailable")
        if now >= watch.expires_at_ms:
            return self._cancel(watch, "docked_igpu.watch_expired")
        gamescope_session = self._gamescope_session()
        if gamescope_session is None or not gamescope_session.exact:
            return self._action(watch, "docked_igpu.gamescope_identity_unverified")
        if gamescope_session.generation != watch.gamescope_session_generation:
            return self._cancel(watch, "docked_igpu.gamescope_changed")
        game = self._game()
        if game is None or not game.exact:
            return self._action(watch, "docked_igpu.game_identity_unverified")
        if game.state is GameState.RUNNING:
            if game.identity != watch.game:
                return self._cancel(watch, "docked_igpu.different_game_started")
            return replace(watch, reason_code="docked_igpu.watching_game_exit")
        if game.state is not GameState.IDLE:
            return self._action(watch, "docked_igpu.game_state_unknown")

        snapshot = self._snapshot()
        if snapshot is None:
            return self._action(watch, "docked_igpu.snapshot_unavailable")
        if (
            snapshot.sample_id == watch.armed_snapshot_sample_id
            or snapshot.generation == watch.armed_snapshot_generation
            or snapshot.snapshot.game_state is GameState.RUNNING
        ):
            return replace(
                watch, reason_code="docked_igpu.exit_seen_waiting_snapshot"
            )
        if snapshot.snapshot.game_state is not GameState.IDLE:
            return self._action(watch, "docked_igpu.game_state_unknown")
        if infer_placement(snapshot.snapshot) is not PlacementState.DOCKED_IGPU:
            return self._cancel(watch, "docked_igpu.placement_changed")
        game_after = self._game()
        gamescope_session_after = self._gamescope_session()
        if (
            game_after is None
            or not game_after.exact
            or game_after.state is not GameState.IDLE
            or game_after.generation != game.generation
            or game_after.sample_id == game.sample_id
        ):
            return self._action(watch, "docked_igpu.game_identity_changed")
        if gamescope_session_after is None or not gamescope_session_after.exact:
            return self._action(watch, "docked_igpu.gamescope_identity_unverified")
        if gamescope_session_after.generation != watch.gamescope_session_generation:
            return self._cancel(watch, "docked_igpu.gamescope_changed")
        profiles = resolve_runtime_profiles(snapshot.snapshot)
        if (
            not profiles.exact_host
            or not profiles.exact_egpu
            or profiles.capabilities.host_profile_id != watch.host_profile_id
            or profiles.capabilities.egpu_profile_id != watch.egpu_profile_id
            or profiles.egpu_stable_id != watch.egpu_stable_id
        ):
            return self._action(watch, "docked_igpu.profile_changed")
        return replace(
            watch,
            stage=DockedIgpuExitStage.PROMOTION_READY,
            reason_code="docked_igpu.promotion_ready",
            ready_snapshot_generation=snapshot.generation,
        )

    def _snapshot(self):
        try:
            return self._snapshots.observe()
        except Exception:
            return None

    def _game(self) -> GameSessionObservation | None:
        try:
            return self._games.observe()
        except Exception:
            return None

    def _gamescope_session(self) -> GamescopeSessionObservation | None:
        try:
            return self._gamescope_sessions.observe()
        except Exception:
            return None

    def _now(self) -> int | None:
        try:
            value = self._clock.now_ms()
            return value if value >= 0 else None
        except Exception:
            return None

    @staticmethod
    def _action(watch, code):
        return replace(
            watch,
            stage=DockedIgpuExitStage.ACTION_REQUIRED,
            reason_code=code,
        )

    @staticmethod
    def _cancel(watch, code):
        return replace(
            watch,
            stage=DockedIgpuExitStage.CANCELLED,
            reason_code=code,
        )
