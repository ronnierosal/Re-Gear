"""Observe SteamOS native recovery after an unexpected dock presentation loss.

This coordinator never restarts Gamescope or claims that physical eGPU removal
is safe.  It binds the last exact idle TV-Docked observation, recognizes the
specific degraded interval where Gamescope is absent but the internal path is
still physically available, and verifies SteamOS' own return to Portable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..domain.control_plane import PlacementState
from ..domain.inference import infer_placement
from ..domain.models import Confidence, DisplayKind, GameState, GpuRole
from ..ports.transition import VersionedObservation
from ..profiles.registry import resolve_runtime_profiles


DEFAULT_NATIVE_RECOVERY_DEADLINE_MS = 120_000


class NativeRecoveryStage(StrEnum):
    IDLE = "idle"
    ARMED = "armed"
    WAITING = "waiting"
    RECOVERED = "recovered"
    ACTION_REQUIRED = "action_required"


@dataclass(frozen=True, slots=True)
class NativeRecoveryStatus:
    stage: NativeRecoveryStage
    code: str
    restore_portable_audio: bool = False


@dataclass(frozen=True, slots=True)
class _DockedBaseline:
    generation: str
    sample_id: str
    host_profile_id: str
    egpu_profile_id: str
    egpu_stable_id: str
    internal_gpu_stable_id: str
    internal_display_stable_id: str
    external_display_stable_id: str


class NativePortableRecoverySupervisor:
    """Verify native Portable recovery without adding display mutation authority."""

    def __init__(self, deadline_ms: int = DEFAULT_NATIVE_RECOVERY_DEADLINE_MS) -> None:
        if type(deadline_ms) is not int or not 1_000 <= deadline_ms <= 300_000:
            raise ValueError("native recovery deadline is invalid")
        self._deadline_ms = deadline_ms
        self._baseline: _DockedBaseline | None = None
        self._started_ms: int | None = None
        self._status = NativeRecoveryStatus(
            NativeRecoveryStage.IDLE, "native_recovery.idle"
        )

    def status(self) -> NativeRecoveryStatus:
        return self._status

    def update(
        self,
        *,
        enabled: bool,
        current: VersionedObservation,
        now_ms: int,
    ) -> NativeRecoveryStatus:
        if type(enabled) is not bool or type(now_ms) is not int or now_ms < 0:
            raise ValueError("native recovery update is invalid")
        if not enabled:
            return self._reset("native_recovery.disabled")

        baseline = self._exact_idle_docked_baseline(current)
        if baseline is not None:
            self._baseline = baseline
            self._started_ms = None
            self._status = NativeRecoveryStatus(
                NativeRecoveryStage.ARMED, "native_recovery.armed"
            )
            return self._status

        if self._baseline is None:
            self._status = NativeRecoveryStatus(
                NativeRecoveryStage.IDLE, "native_recovery.no_docked_baseline"
            )
            return self._status

        if self._portable_verified(current):
            if self._started_ms is None:
                return self._reset("native_recovery.portable_without_incident")
            self._baseline = None
            self._started_ms = None
            self._status = NativeRecoveryStatus(
                NativeRecoveryStage.RECOVERED,
                "native_recovery.portable_verified",
                restore_portable_audio=True,
            )
            return self._status

        if self._path_loss_correlated(current):
            if self._started_ms is None:
                self._started_ms = now_ms
            elapsed = now_ms - self._started_ms
            if elapsed < 0:
                return self._action_required("native_recovery.clock_regressed")
            if elapsed >= self._deadline_ms:
                return self._action_required("native_recovery.timeout")
            self._status = NativeRecoveryStatus(
                NativeRecoveryStage.WAITING, "native_recovery.waiting_for_steamos"
            )
            return self._status

        if self._started_ms is not None:
            if now_ms - self._started_ms >= self._deadline_ms:
                return self._action_required("native_recovery.timeout")
            self._status = NativeRecoveryStatus(
                NativeRecoveryStage.WAITING,
                "native_recovery.waiting_for_complete_evidence",
            )
            return self._status

        return self._action_required("native_recovery.state_diverged")

    def _exact_idle_docked_baseline(
        self, current: VersionedObservation
    ) -> _DockedBaseline | None:
        snapshot = current.snapshot
        if (
            snapshot.game_state is not GameState.IDLE
            or infer_placement(snapshot) is not PlacementState.DOCKED_EGPU
        ):
            return None
        profiles = resolve_runtime_profiles(snapshot)
        if not profiles.exact_host or not profiles.exact_egpu:
            return None
        internal_gpus = tuple(
            gpu
            for gpu in snapshot.gpus
            if gpu.role is GpuRole.INTERNAL
            and gpu.present
            and gpu.confidence is Confidence.VERIFIED
        )
        internal_displays = tuple(
            display
            for display in snapshot.displays
            if display.kind is DisplayKind.INTERNAL
            and display.connected is True
            and display.confidence is Confidence.VERIFIED
        )
        external_displays = tuple(
            display
            for display in snapshot.displays
            if display.kind is DisplayKind.EXTERNAL
            and display.connected is True
            and display.active is True
            and display.confidence is Confidence.VERIFIED
        )
        if not all(
            len(values) == 1
            for values in (internal_gpus, internal_displays, external_displays)
        ):
            return None
        return _DockedBaseline(
            current.generation,
            current.sample_id,
            profiles.capabilities.host_profile_id,
            profiles.capabilities.egpu_profile_id,
            profiles.egpu_stable_id,
            internal_gpus[0].stable_id,
            internal_displays[0].stable_id,
            external_displays[0].stable_id,
        )

    def _path_loss_correlated(self, current: VersionedObservation) -> bool:
        baseline = self._baseline
        snapshot = current.snapshot
        if baseline is None:
            return False
        if (
            current.generation == baseline.generation
            or current.sample_id == baseline.sample_id
            or snapshot.host_profile != baseline.host_profile_id
            or snapshot.game_state is not GameState.IDLE
            or snapshot.gamescope.running is not False
        ):
            return False
        if not self._internal_path_available(snapshot):
            return False
        lost = tuple(
            display
            for display in snapshot.displays
            if display.stable_id == baseline.external_display_stable_id
        )
        if len(lost) != 1 or not (
            lost[0].kind is DisplayKind.EXTERNAL
            and lost[0].connected is False
            and lost[0].active is not True
            and lost[0].confidence is Confidence.VERIFIED
        ):
            return False
        return not any(
            display.kind is DisplayKind.EXTERNAL
            and (
                display.connected is not False
                or display.active is True
                or display.confidence is not Confidence.VERIFIED
            )
            for display in snapshot.displays
        )

    def _portable_verified(self, current: VersionedObservation) -> bool:
        baseline = self._baseline
        snapshot = current.snapshot
        return bool(
            baseline is not None
            and snapshot.host_profile == baseline.host_profile_id
            and snapshot.game_state is GameState.IDLE
            and self._internal_path_available(snapshot)
            and infer_placement(snapshot) is PlacementState.PORTABLE
        )

    def _internal_path_available(self, snapshot) -> bool:
        baseline = self._baseline
        if baseline is None:
            return False
        gpus = tuple(
            gpu
            for gpu in snapshot.gpus
            if gpu.stable_id == baseline.internal_gpu_stable_id
            and gpu.role is GpuRole.INTERNAL
            and gpu.present
            and gpu.confidence is Confidence.VERIFIED
        )
        displays = tuple(
            display
            for display in snapshot.displays
            if display.stable_id == baseline.internal_display_stable_id
            and display.kind is DisplayKind.INTERNAL
            and display.connected is True
            and display.confidence is Confidence.VERIFIED
        )
        return len(gpus) == 1 and len(displays) == 1

    def _action_required(self, code: str) -> NativeRecoveryStatus:
        self._baseline = None
        self._started_ms = None
        self._status = NativeRecoveryStatus(NativeRecoveryStage.ACTION_REQUIRED, code)
        return self._status

    def _reset(self, code: str) -> NativeRecoveryStatus:
        self._baseline = None
        self._started_ms = None
        self._status = NativeRecoveryStatus(NativeRecoveryStage.IDLE, code)
        return self._status
