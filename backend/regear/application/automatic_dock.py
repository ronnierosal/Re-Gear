"""Pure one-shot policy for automatic TV docking after exact attach readiness."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import TYPE_CHECKING

from ..domain.control_plane import PlacementState, TransitionOutcomeKind
from ..domain.models import Confidence, DisplayKind, GameState, GpuRole
if TYPE_CHECKING:
    from .supervised_transition import SupervisedTransitionExecution
from ..ports.transition import VersionedObservation
from ..profiles.registry import ProfileResolutionStatus, resolve_runtime_profiles
from .attach_readiness import AttachReadinessStage, AttachReadinessStatus
from .connection_readiness import ConnectionReadinessStage, ConnectionReadinessStatus
from ..domain.inference import infer_placement


class AutomaticDockStage(StrEnum):
    DISABLED = "disabled"
    OBSERVING = "observing"
    SETTLING = "settling"
    WAITING = "waiting"
    SWITCHING = "switching"
    DOCKED = "docked"
    ACTION_REQUIRED = "action_required"


@dataclass(frozen=True, slots=True)
class AutomaticDockStatus:
    stage: AutomaticDockStage
    code: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class AutomaticDockDecision:
    status: AutomaticDockStatus
    expected_generation: str = ""

    @property
    def should_switch(self) -> bool:
        return bool(self.expected_generation)


class AutomaticDockCoordinator:
    """One hardware attempt, plus one same-target pre-mutation refusal retry."""

    def __init__(self) -> None:
        self._attempted = False
        self._retry_pending = False
        self._retry_spent = False
        self._request_binding = None
        self._request_generation = ""
        self._request_sample = ""
        self._status = AutomaticDockStatus(
            AutomaticDockStage.DISABLED, "automatic_dock.disabled", False
        )

    def status(self) -> AutomaticDockStatus:
        return self._status

    def update(
        self,
        *,
        enabled: bool,
        readiness: AttachReadinessStatus | ConnectionReadinessStatus,
        current: VersionedObservation,
    ) -> AutomaticDockDecision:
        profiles = resolve_runtime_profiles(current.snapshot)
        # Loss of exact identity during PCI/DRM enumeration is not removal.
        # Keep the one-shot/safe-disconnect latch while any attachment evidence
        # remains; otherwise a transient unknown snapshot can re-arm a restart.
        if verified_egpu_absent(current.snapshot):
            self._attempted = False
            self._clear_retry()
        if not enabled:
            self._attempted = False
            self._clear_retry()
            self._status = AutomaticDockStatus(
                AutomaticDockStage.DISABLED, "automatic_dock.disabled", False
            )
            return AutomaticDockDecision(self._status)
        if self._retry_pending:
            binding = _retry_binding(current)
            # A different observed identity cancels rather than waiting until
            # the original target returns. Missing HDMI alone may settle later.
            host, gpu_id, display_id = self._request_binding
            identity_changed = (
                current.snapshot.host_profile != host
                or any(g.role is GpuRole.EXTERNAL and g.present and g.stable_id != gpu_id
                       for g in current.snapshot.gpus)
                or any(d.kind is DisplayKind.EXTERNAL and d.connected is not False
                       and d.edid_ready is True and d.stable_id != display_id
                       for d in current.snapshot.displays)
            )
            if identity_changed or (binding is not None and binding != self._request_binding):
                self._retry_pending = False
                self._request_binding = None
        if not profiles.exact_host or not profiles.exact_egpu:
            self._status = AutomaticDockStatus(
                AutomaticDockStage.OBSERVING,
                "automatic_dock.waiting_for_exact_g1",
                True,
            )
            return AutomaticDockDecision(self._status)
        placement = infer_placement(current.snapshot)
        if placement is PlacementState.DOCKED_EGPU:
            self._attempted = True
            self._retry_pending = False
            self._request_binding = None
            self._status = AutomaticDockStatus(
                AutomaticDockStage.DOCKED, "automatic_dock.tv_active", True
            )
            return AutomaticDockDecision(self._status)
        if self._retry_pending:
            binding = _retry_binding(current)
            if (
                enabled is not True
                or binding is None
                or placement is not PlacementState.PORTABLE
                or current.sample_id == self._request_sample
                or current.snapshot.game_state is not GameState.IDLE
                or current.snapshot.gamescope.running is not True
                or current.snapshot.gamescope.confidence is not Confidence.VERIFIED
                or not isinstance(readiness, ConnectionReadinessStatus)
                or readiness.stage is not ConnectionReadinessStage.READY_IDLE
            ):
                return AutomaticDockDecision(self._status)
            # The normal source/readiness gates and the shared engine still run.
            self._retry_pending = False
            self._retry_spent = True
            self._attempted = False
        if self._attempted:
            return AutomaticDockDecision(self._status)
        if readiness.stage in {
            AttachReadinessStage.READY_IDLE,
            ConnectionReadinessStage.READY_IDLE,
        }:
            if placement is not PlacementState.PORTABLE:
                self._status = AutomaticDockStatus(
                    AutomaticDockStage.ACTION_REQUIRED,
                    "automatic_dock.source_unverified",
                    True,
                )
                return AutomaticDockDecision(self._status)
            self._attempted = True
            self._request_binding = _retry_binding(current)
            self._request_generation = current.generation
            self._request_sample = current.sample_id
            self._status = AutomaticDockStatus(
                AutomaticDockStage.SWITCHING, "automatic_dock.switch_requested", True
            )
            return AutomaticDockDecision(self._status, current.generation)
        if readiness.stage in {
            AttachReadinessStage.SETTLING,
            ConnectionReadinessStage.STABILIZING,
            ConnectionReadinessStage.TRANSPORT_DETECTED,
        }:
            stage = AutomaticDockStage.SETTLING
        elif readiness.stage in {
            AttachReadinessStage.ACTION_REQUIRED,
            ConnectionReadinessStage.ACTION_REQUIRED,
            ConnectionReadinessStage.LINK_TRAINING_FAILED,
            ConnectionReadinessStage.TIMED_OUT,
        }:
            stage = AutomaticDockStage.ACTION_REQUIRED
        else:
            stage = AutomaticDockStage.WAITING
        self._status = AutomaticDockStatus(stage, readiness.code, True)
        return AutomaticDockDecision(self._status)

    def reset_after_acknowledgement(self) -> AutomaticDockStatus:
        """Permit one fresh re-evaluation after the player clears a journal."""
        self._attempted = False
        self._clear_retry()
        self._status = AutomaticDockStatus(
            AutomaticDockStage.OBSERVING,
            "automatic_dock.rearmed_after_acknowledgement",
            True,
        )
        return self._status
    def suppress_current_attachment_after_portable_return(self) -> AutomaticDockStatus:
        """Do not undo an intentional safe-disconnect Portable transition.

        The attempted latch clears automatically only after the exact eGPU is
        no longer observed (or when the player deliberately disables docking).
        """
        self._attempted = True
        self._retry_pending = False
        self._request_binding = None
        self._status = AutomaticDockStatus(
            AutomaticDockStage.WAITING,
            "automatic_dock.suppressed_for_safe_disconnect",
            True,
        )
        return self._status

    def record_result(self, code: str, *, succeeded: bool) -> AutomaticDockStatus:
        self._retry_pending = False
        self._request_binding = None
        self._status = AutomaticDockStatus(
            AutomaticDockStage.DOCKED if succeeded else AutomaticDockStage.ACTION_REQUIRED,
            code,
            True,
        )
        return self._status

    def record_execution(
        self, result: SupervisedTransitionExecution, *, expected_generation: str
    ) -> AutomaticDockStatus:
        """Only the service's explicit pre-plan refusal can open the retry lane.

        A code alone, exception, accepted plan, outcome or durable record never
        proves that hardware work did not begin. Generation binds late replies
        to the request; suppression clears that request's identity binding.
        """
        binding = self._request_binding
        may_retry = (
            result.accepted is False
            and result.code == "transition.evidence_changed"
            and result.operation_id == ""
            and result.outcome is None
            and result.durable is False
            and self._attempted
            and not self._retry_spent
            and binding is not None
            and expected_generation == self._request_generation
        )
        self.record_result(result.code, succeeded=bool(
            result.outcome and result.outcome.kind is TransitionOutcomeKind.SUCCEEDED
        ))
        if may_retry:
            self._request_binding = binding
            self._retry_pending = True
        return self._status

    def _clear_retry(self) -> None:
        self._retry_pending = False
        self._retry_spent = False
        self._request_binding = None
        self._request_generation = ""
        self._request_sample = ""


def _retry_binding(current: VersionedObservation) -> tuple[str, str, str] | None:
    """Bind the exact dock and EDID panel, never a connector/socket identity."""
    snapshot = current.snapshot
    profiles = resolve_runtime_profiles(snapshot)
    gpus = [gpu for gpu in snapshot.gpus if gpu.role is GpuRole.EXTERNAL and gpu.present]
    displays = [display for display in snapshot.displays
                if display.kind is DisplayKind.EXTERNAL and display.connected is not False]
    if not profiles.exact_host or not profiles.exact_egpu or len(gpus) != 1 or len(displays) != 1:
        return None
    gpu, display = gpus[0], displays[0]
    if (gpu.confidence is not Confidence.VERIFIED
            or display.confidence is not Confidence.VERIFIED
            or display.connected is not True or display.edid_ready is not True
            or re.fullmatch(r"display:[0-9a-f]{16}", display.stable_id) is None):
        return None
    return snapshot.host_profile, gpu.stable_id, display.stable_id


def verified_egpu_absent(snapshot) -> bool:
    """Observation reset only, never authorization for physical removal."""
    profiles = resolve_runtime_profiles(snapshot)
    return bool(
        profiles.exact_host
        and profiles.egpu_status is ProfileResolutionStatus.ABSENT
        and not snapshot.egpu_link.applicable
        and not snapshot.disconnect_readiness.applicable
        and not snapshot.sleep_guard.required
    )
