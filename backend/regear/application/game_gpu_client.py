"""Bracketed read-only correlation of a game with exact eGPU render clients."""

from __future__ import annotations

from ..domain.game_gpu_client import (
    GameEgpuClientEvidence,
    GameEgpuClientStatus,
)
from ..domain.game_runtime import GameRuntimeKind
from ..domain.game_session import ActiveGameIdentity
from ..domain.models import EgpuClientKind, EgpuResourceKind, GameState
from ..ports.game_runtime import GameRuntimeObservationPort
from ..ports.transition import TransitionObservationPort
from ..profiles.registry import resolve_runtime_profiles


class GameEgpuClientEvidenceService:
    """Require a stable process graph before and after one client snapshot."""

    def __init__(
        self,
        *,
        runtime: GameRuntimeObservationPort,
        snapshots: TransitionObservationPort,
    ) -> None:
        self._runtime = runtime
        self._snapshots = snapshots

    def observe(
        self, identity: ActiveGameIdentity, *, user_uid: int
    ) -> GameEgpuClientEvidence:
        if user_uid <= 0 or user_uid > 2_147_483_647:
            return self._unknown("game_gpu.user_invalid")
        before = self._observe_runtime(identity, user_uid)
        if before is None or not before.exact or not self._matches(identity, before):
            return self._unknown("game_gpu.runtime_unavailable")
        try:
            snapshot_observation = self._snapshots.observe()
        except Exception:
            snapshot_observation = None
        if snapshot_observation is None:
            return self._unknown("game_gpu.snapshot_unavailable")
        after = self._observe_runtime(identity, user_uid)
        if after is None or not after.exact or not self._matches(identity, after):
            return self._unknown("game_gpu.runtime_unavailable")
        if (
            before.generation != after.generation
            or before.sample_id == after.sample_id
        ):
            return self._unknown("game_gpu.runtime_changed")

        snapshot = snapshot_observation.snapshot
        if snapshot.game_state is not GameState.RUNNING:
            return self._unknown("game_gpu.game_state_changed")
        profiles = resolve_runtime_profiles(snapshot)
        readiness = snapshot.disconnect_readiness
        if (
            not profiles.exact_host
            or not profiles.exact_egpu
            or not readiness.applicable
            or not readiness.scan_complete
            or readiness.error
            or readiness.egpu_stable_id != profiles.egpu_stable_id
        ):
            return self._unknown("game_gpu.egpu_scan_unverified")

        instances = {
            (process.pid, str(process.start_time_ticks))
            for process in after.processes
        }
        same_pid_changed = any(
            client.pid in {pid for pid, _start in instances}
            and (client.pid, client.process_start_time) not in instances
            for client in readiness.clients
        )
        if same_pid_changed:
            return self._unknown("game_gpu.process_identity_changed")

        matching = tuple(
            client
            for client in readiness.clients
            if (client.pid, client.process_start_time) in instances
            and EgpuResourceKind.DRM_RENDER in client.resources
        )
        if any(client.kind is not EgpuClientKind.GAME for client in matching):
            return self._unknown("game_gpu.client_classification_conflict")
        if matching:
            return GameEgpuClientEvidence(
                GameEgpuClientStatus.PRESENT,
                after.runtime_kind,
                len(matching),
                "game_gpu.egpu_render_client_present",
            )
        return GameEgpuClientEvidence(
            GameEgpuClientStatus.ABSENT,
            after.runtime_kind,
            0,
            "game_gpu.egpu_render_client_absent",
        )

    def _observe_runtime(self, identity, user_uid):
        try:
            return self._runtime.observe(identity, user_uid=user_uid)
        except Exception:
            return None

    @staticmethod
    def _matches(identity, observation):
        return bool(
            observation.steam_app_id == identity.steam_app_id
            and observation.scopes == identity.scopes
        )

    @staticmethod
    def _unknown(reason: str) -> GameEgpuClientEvidence:
        return GameEgpuClientEvidence(
            GameEgpuClientStatus.UNKNOWN,
            GameRuntimeKind.UNKNOWN,
            0,
            reason,
        )
