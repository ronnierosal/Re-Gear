"""Bounded read-only proof of game activity on one exact DRM GPU."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ..domain.game_render_activity import (
    DrmEngineCounterSample,
    GameRenderActivityEvidence,
    GameRenderActivityStatus,
)
from ..domain.control_plane import PlacementState
from ..domain.game_runtime import GameRuntimeKind
from ..domain.game_session import ActiveGameIdentity
from ..domain.models import GameState
from ..domain.models import Confidence, GpuRole
from ..domain.inference import infer_placement
from ..ports.game_render_activity import (
    DrmEngineCounterPort,
    DrmRenderBindingPort,
)
from ..ports.game_runtime import GameRuntimeObservationPort
from ..ports.runtime_transition import DeadlineWaitPort
from ..ports.transition import TransitionObservationPort
from ..profiles.registry import resolve_runtime_profiles


MIN_SAMPLE_INTERVAL_MS = 50
MAX_SAMPLE_INTERVAL_MS = 250


@dataclass(frozen=True, slots=True)
class GameRenderActivityComparison:
    internal: GameRenderActivityEvidence
    external: GameRenderActivityEvidence


class GameRenderActivityEvidenceService:
    def __init__(
        self,
        *,
        runtime: GameRuntimeObservationPort,
        snapshots: TransitionObservationPort,
        bindings: DrmRenderBindingPort,
        counters: DrmEngineCounterPort,
        waiter: DeadlineWaitPort,
        target_role: GpuRole,
        sample_interval_ms: int = 250,
    ) -> None:
        if not MIN_SAMPLE_INTERVAL_MS <= sample_interval_ms <= MAX_SAMPLE_INTERVAL_MS:
            raise ValueError("render activity sample interval is invalid")
        self._runtime = runtime
        self._snapshots = snapshots
        self._bindings = bindings
        self._counters = counters
        self._waiter = waiter
        if target_role not in {GpuRole.INTERNAL, GpuRole.EXTERNAL}:
            raise ValueError("render activity target role is invalid")
        self._target_role = target_role
        self._sample_interval_ms = sample_interval_ms

    def observe(
        self, identity: ActiveGameIdentity, *, user_uid: int
    ) -> GameRenderActivityEvidence:
        if user_uid <= 0 or user_uid > 2_147_483_647:
            return self._unknown("render_activity.user_invalid")
        before = self._runtime_observation(identity, user_uid)
        if not self._runtime_matches(identity, before):
            return self._unknown("render_activity.runtime_unavailable")
        try:
            snapshot_observation = self._snapshots.observe()
        except Exception:
            snapshot_observation = None
        if snapshot_observation is None:
            return self._unknown("render_activity.snapshot_unavailable")
        if not snapshot_observation.generation:
            return self._unknown("render_activity.snapshot_unavailable")
        snapshot = snapshot_observation.snapshot
        if snapshot.game_state is not GameState.RUNNING:
            return self._unknown("render_activity.game_state_changed")
        profiles = resolve_runtime_profiles(snapshot)
        expected_gpu_id = self._expected_gpu_id(snapshot, profiles)
        if not expected_gpu_id:
            return self._unknown(
                "render_activity.egpu_unverified"
                if self._target_role is GpuRole.EXTERNAL
                else "render_activity.internal_gpu_unverified"
            )
        placement = infer_placement(snapshot)
        if placement in {PlacementState.UNKNOWN, PlacementState.DEGRADED}:
            return self._unknown("render_activity.placement_unverified")
        try:
            binding = self._bindings.resolve(snapshot)
        except Exception:
            binding = None
        if binding is None or binding.gpu_stable_id != expected_gpu_id:
            return self._unknown("render_activity.binding_unverified")

        first = self._counter_sample(before.processes, binding)
        if first is None or not first.complete:
            return self._unknown("render_activity.counter_unavailable")
        try:
            self._waiter.wait_ms(self._sample_interval_ms)
        except Exception:
            return self._unknown("render_activity.wait_failed")
        second = self._counter_sample(before.processes, binding)
        if second is None or not second.complete:
            return self._unknown("render_activity.counter_unavailable")
        after = self._runtime_observation(identity, user_uid)
        if (
            not self._runtime_matches(identity, after)
            or before.generation != after.generation
            or before.sample_id == after.sample_id
        ):
            return self._unknown("render_activity.runtime_changed")
        generation = self._evidence_generation(
            before.generation,
            snapshot_observation.generation,
            binding,
            first,
            second,
            after.generation,
        )
        return self._compare(
            first, second, after.runtime_kind, generation, placement
        )

    def _expected_gpu_id(self, snapshot, profiles) -> str:
        if not profiles.exact_host:
            return ""
        if self._target_role is GpuRole.INTERNAL:
            internal = tuple(
                gpu
                for gpu in snapshot.gpus
                if gpu.present
                and gpu.role is GpuRole.INTERNAL
                and gpu.confidence is Confidence.VERIFIED
            )
            return internal[0].stable_id if len(internal) == 1 else ""
        readiness = snapshot.disconnect_readiness
        if (
            not profiles.exact_egpu
            or not readiness.applicable
            or not readiness.scan_complete
            or readiness.error
            or readiness.egpu_stable_id != profiles.egpu_stable_id
        ):
            return ""
        return profiles.egpu_stable_id

    def _runtime_observation(self, identity, user_uid):
        try:
            return self._runtime.observe(identity, user_uid=user_uid)
        except Exception:
            return None

    @staticmethod
    def _runtime_matches(identity, observation):
        return bool(
            observation is not None
            and observation.exact
            and observation.steam_app_id == identity.steam_app_id
            and observation.scopes == identity.scopes
        )

    def _counter_sample(self, processes, binding):
        try:
            return self._counters.sample(processes, binding)
        except Exception:
            return None

    @classmethod
    def _compare(
        cls,
        first: DrmEngineCounterSample,
        second: DrmEngineCounterSample,
        runtime_kind: GameRuntimeKind,
        evidence_generation: str,
        placement,
    ) -> GameRenderActivityEvidence:
        first_clients = {client.identity: client for client in first.clients}
        second_clients = {client.identity: client for client in second.clients}
        if first_clients.keys() != second_clients.keys():
            return cls._unknown("render_activity.client_set_changed")
        if not first_clients:
            return GameRenderActivityEvidence(
                GameRenderActivityStatus.NO_CLIENT,
                runtime_kind,
                0,
                "render_activity.no_client",
                evidence_generation,
                placement,
            )
        active = 0
        for identity, first_client in first_clients.items():
            second_client = second_clients[identity]
            first_counters = dict(first_client.counters_ns)
            second_counters = dict(second_client.counters_ns)
            if first_counters.keys() != second_counters.keys():
                return cls._unknown("render_activity.engine_set_changed")
            for engine, first_value in first_counters.items():
                second_value = second_counters[engine]
                if second_value < first_value:
                    return cls._unknown("render_activity.counter_decreased")
                if second_value > first_value:
                    active += 1
        if active:
            return GameRenderActivityEvidence(
                GameRenderActivityStatus.ACTIVE,
                runtime_kind,
                active,
                "render_activity.active",
                evidence_generation,
                placement,
            )
        return GameRenderActivityEvidence(
            GameRenderActivityStatus.IDLE_WINDOW,
            runtime_kind,
            0,
            "render_activity.idle_window",
            evidence_generation,
            placement,
        )

    @staticmethod
    def _evidence_generation(
        before_generation,
        snapshot_generation,
        binding,
        first,
        second,
        after_generation,
    ):
        def sample(value):
            return ";".join(
                f"{client.pid}:{client.process_start_time_ticks}:"
                f"{client.drm_client_id}:"
                + ",".join(
                    f"{engine}={counter}"
                    for engine, counter in client.counters_ns
                )
                for client in value.clients
            )

        material = "|".join(
            (
                before_generation,
                snapshot_generation,
                binding.gpu_stable_id,
                binding.pci_bdf,
                binding.render_node,
                sample(first),
                sample(second),
                after_generation,
            )
        ).encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    @staticmethod
    def _unknown(reason: str) -> GameRenderActivityEvidence:
        return GameRenderActivityEvidence(
            GameRenderActivityStatus.UNKNOWN,
            GameRuntimeKind.UNKNOWN,
            0,
            reason,
        )


class GameRenderActivityComparisonService:
    """Sample internal and external targets inside one stable observation window."""

    def __init__(
        self,
        *,
        runtime: GameRuntimeObservationPort,
        snapshots: TransitionObservationPort,
        internal_binding: DrmRenderBindingPort,
        external_binding: DrmRenderBindingPort,
        counters: DrmEngineCounterPort,
        waiter: DeadlineWaitPort,
        sample_interval_ms: int = 250,
    ) -> None:
        if not MIN_SAMPLE_INTERVAL_MS <= sample_interval_ms <= MAX_SAMPLE_INTERVAL_MS:
            raise ValueError("render activity sample interval is invalid")
        self._runtime = runtime
        self._snapshots = snapshots
        self._bindings = {
            GpuRole.INTERNAL: internal_binding,
            GpuRole.EXTERNAL: external_binding,
        }
        self._counters = counters
        self._waiter = waiter
        self._sample_interval_ms = sample_interval_ms

    def observe(
        self, identity: ActiveGameIdentity, *, user_uid: int
    ) -> GameRenderActivityComparison:
        if user_uid <= 0 or user_uid > 2_147_483_647:
            return self._unknown_pair("render_activity.user_invalid")
        before = self._runtime_observation(identity, user_uid)
        if not GameRenderActivityEvidenceService._runtime_matches(identity, before):
            return self._unknown_pair("render_activity.runtime_unavailable")
        snapshot_before = self._snapshot()
        if snapshot_before is None or not snapshot_before.generation:
            return self._unknown_pair("render_activity.snapshot_unavailable")
        snapshot = snapshot_before.snapshot
        if snapshot.game_state is not GameState.RUNNING:
            return self._unknown_pair("render_activity.game_state_changed")
        placement = infer_placement(snapshot)
        if placement in {PlacementState.UNKNOWN, PlacementState.DEGRADED}:
            return self._unknown_pair("render_activity.placement_unverified")
        profiles = resolve_runtime_profiles(snapshot)
        expected = {
            role: self._expected_gpu_id(snapshot, profiles, role)
            for role in (GpuRole.INTERNAL, GpuRole.EXTERNAL)
        }
        results = {
            GpuRole.INTERNAL: self._unknown(
                "render_activity.internal_gpu_unverified"
            ),
            GpuRole.EXTERNAL: self._unknown("render_activity.egpu_unverified"),
        }
        bindings = {}
        for role, expected_gpu_id in expected.items():
            if not expected_gpu_id:
                continue
            binding = self._binding(role, snapshot)
            if binding is None or binding.gpu_stable_id != expected_gpu_id:
                results[role] = self._unknown("render_activity.binding_unverified")
                continue
            bindings[role] = binding

        first = {}
        for role, binding in bindings.items():
            sample = self._counter_sample(before.processes, binding)
            if sample is None or not sample.complete:
                results[role] = self._unknown("render_activity.counter_unavailable")
                continue
            first[role] = sample
        if not first:
            return self._result(results)
        try:
            self._waiter.wait_ms(self._sample_interval_ms)
        except Exception:
            return self._unknown_pair("render_activity.wait_failed")

        second = {}
        for role, sample_before in first.items():
            sample_after = self._counter_sample(before.processes, bindings[role])
            if sample_after is None or not sample_after.complete:
                results[role] = self._unknown("render_activity.counter_unavailable")
                continue
            second[role] = sample_after
        after = self._runtime_observation(identity, user_uid)
        if (
            not GameRenderActivityEvidenceService._runtime_matches(identity, after)
            or before.generation != after.generation
            or before.sample_id == after.sample_id
        ):
            return self._unknown_pair("render_activity.runtime_changed")
        snapshot_after = self._snapshot()
        if (
            snapshot_after is None
            or snapshot_after.generation != snapshot_before.generation
            or snapshot_after.sample_id == snapshot_before.sample_id
        ):
            return self._unknown_pair("render_activity.snapshot_changed")
        for role, sample_after in second.items():
            results[role] = GameRenderActivityEvidenceService._compare(
                first[role],
                sample_after,
                after.runtime_kind,
                GameRenderActivityEvidenceService._evidence_generation(
                    before.generation,
                    snapshot_before.generation,
                    bindings[role],
                    first[role],
                    sample_after,
                    after.generation,
                ),
                placement,
            )
        return self._result(results)

    @staticmethod
    def _expected_gpu_id(snapshot, profiles, role: GpuRole) -> str:
        if not profiles.exact_host:
            return ""
        if role is GpuRole.INTERNAL:
            internal = tuple(
                gpu
                for gpu in snapshot.gpus
                if gpu.present
                and gpu.role is GpuRole.INTERNAL
                and gpu.confidence is Confidence.VERIFIED
            )
            return internal[0].stable_id if len(internal) == 1 else ""
        readiness = snapshot.disconnect_readiness
        if (
            not profiles.exact_egpu
            or not readiness.applicable
            or not readiness.scan_complete
            or readiness.error
            or readiness.egpu_stable_id != profiles.egpu_stable_id
        ):
            return ""
        return profiles.egpu_stable_id

    def _runtime_observation(self, identity, user_uid):
        try:
            return self._runtime.observe(identity, user_uid=user_uid)
        except Exception:
            return None

    def _snapshot(self):
        try:
            return self._snapshots.observe()
        except Exception:
            return None

    def _binding(self, role, snapshot):
        try:
            return self._bindings[role].resolve(snapshot)
        except Exception:
            return None

    def _counter_sample(self, processes, binding):
        try:
            return self._counters.sample(processes, binding)
        except Exception:
            return None

    @staticmethod
    def _unknown(reason):
        return GameRenderActivityEvidenceService._unknown(reason)

    @classmethod
    def _unknown_pair(cls, reason):
        unknown = cls._unknown(reason)
        return GameRenderActivityComparison(unknown, unknown)

    @staticmethod
    def _result(results):
        return GameRenderActivityComparison(
            results[GpuRole.INTERNAL],
            results[GpuRole.EXTERNAL],
        )
