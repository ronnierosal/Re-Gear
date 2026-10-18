"""Inert, one-use context envelope for a future supervised handoff facade.

No runtime consumer, profile admission, collector or executor is provided here.
Callers must independently verify context evidence. A matching envelope does not
qualify hardware or authorize commands outside a reviewed transaction runner.
"""
from dataclasses import dataclass, fields
import re
import threading
from enum import StrEnum
from typing import Callable

from .experimental_transition import ExperimentalTransitionApprovalStore
from ..domain.control_plane import ExperimentalTransitionPermit, PlacementState
from ..ports.presentation_activation import UserServiceOperation


_HASH = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:@-]{1,256}")
_OPERATIONS = frozenset({
    UserServiceOperation.DAEMON_RELOAD,
    UserServiceOperation.VERIFY_GAMESCOPE_UNIT,
    UserServiceOperation.RESTART_GAMESCOPE_SESSION,
    UserServiceOperation.OBSERVE_FILTER_GAMESCOPE,
})


class HandoffAudioOperation(StrEnum):
    DUMP = "dump"
    SET_DEFAULT = "set_default"


@dataclass(frozen=True, slots=True)
class HandoffAudioPermission:
    """Approved identities only; availability must be validated before each call."""
    source_sink_sha256: str
    target_sink_sha256: str
    rollback_sink_sha256: str
    operations: tuple[HandoffAudioOperation, ...]

    def __post_init__(self):
        for value in (self.source_sink_sha256, self.target_sink_sha256, self.rollback_sink_sha256):
            if type(value) is not str or _HASH.fullmatch(value) is None:
                raise ValueError("audio identity must be an exact digest")
        if (type(self.operations) is not tuple or not self.operations
                or any(type(op) is not HandoffAudioOperation for op in self.operations)
                or len(set(self.operations)) != len(self.operations)):
            raise ValueError("audio operation permission is invalid")


@dataclass(frozen=True, slots=True)
class HandoffContext:
    host_identity_sha256: str
    host_profile_id: str
    egpu_profile_id: str
    egpu_stable_id: str
    build_profile: str
    boot_id: str
    snapshot_generation: str
    source_placement: PlacementState
    target_placement: PlacementState
    internal_gpu_id: str
    internal_display_id: str
    external_display_id: str
    user_uid: int
    user_context_sha256: str
    session_unit: str
    session_target: str
    session_definition_sha256: str
    integration_sha256: str
    source_invocation_id: str
    source_main_pid: int
    allowed_operations: tuple[UserServiceOperation, ...]
    evidence_verified: bool
    audio: HandoffAudioPermission | None = None

    def __post_init__(self) -> None:
        if self.audio is not None and type(self.audio) is not HandoffAudioPermission:
            raise ValueError("audio permission is invalid")
        if self.build_profile != "development" or self.evidence_verified is not True:
            raise ValueError("handoff context is not verified development evidence")
        placements = {PlacementState.PORTABLE, PlacementState.DOCKED_EGPU}
        if (type(self.source_placement) is not PlacementState
                or type(self.target_placement) is not PlacementState
                or self.source_placement not in placements or self.target_placement not in placements
                or self.source_placement is self.target_placement):
            raise ValueError("handoff context placement is invalid")
        for name in ("user_uid", "source_main_pid"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError("handoff context user or process is invalid")
        operations = self.allowed_operations
        if (type(operations) is not tuple or not operations
                or any(type(value) is not UserServiceOperation for value in operations)
                or len(set(operations)) != len(operations)
                or not set(operations).issubset(_OPERATIONS)):
            raise ValueError("handoff context operation set is invalid")
        excluded = {"source_placement", "target_placement", "user_uid", "source_main_pid",
                    "allowed_operations", "evidence_verified", "audio"}
        for field in fields(self):
            if field.name in excluded:
                continue
            value = getattr(self, field.name)
            pattern = _HASH if field.name.endswith("sha256") or field.name == "snapshot_generation" else _IDENTIFIER
            if type(value) is not str or pattern.fullmatch(value) is None or value == "unknown":
                raise ValueError("handoff context field is missing or invalid")
        if (not self.session_unit.endswith(".service") or not self.session_target.endswith(".target")
                or self.session_unit.startswith(".") or self.session_target.startswith(".")):
            raise ValueError("handoff context session definition is invalid")


@dataclass(frozen=True, slots=True)
class ApprovedHandoff:
    permit: ExperimentalTransitionPermit
    context: HandoffContext


class HandoffApprovalStore:
    """One immutable envelope alongside the existing expiring, one-use permit.

    Consumption checks pre-effect source invocation. Post-restart replacement
    invocation verification belongs to the future runner, not envelope equality.
    Every consume attempt clears the envelope; stale/uncertain context cannot
    be retried using the same token. No I/O, commands or admission occur here.
    """
    def __init__(self, *, monotonic: Callable[[], float] | None = None,
                 token_factory: Callable[[], str] | None = None) -> None:
        options = {"token_factory": token_factory}
        if monotonic is not None:
            options["monotonic"] = monotonic
        self._approvals = ExperimentalTransitionApprovalStore(**options)
        self._lock = threading.Lock()
        self._envelope: tuple[str, HandoffContext] | None = None

    def issue(self, *, plan_id: str, context: HandoffContext, user_confirmed: object) -> str:
        if user_confirmed is not True or type(context) is not HandoffContext:
            raise ValueError("handoff approval requires verified context and literal consent")
        with self._lock:
            token = self._approvals.issue(
                plan_id=plan_id, observed_generation=context.snapshot_generation,
                target_placement=context.target_placement, host_profile_id=context.host_profile_id,
                egpu_profile_id=context.egpu_profile_id, egpu_stable_id=context.egpu_stable_id,
                user_confirmed=True,
            )
            self._envelope = token, context
            return token

    def consume(self, token: str, *, current: HandoffContext) -> ApprovedHandoff:
        with self._lock:
            envelope = self._envelope
            self._envelope = None
            if type(token) is not str or envelope is None:
                raise ValueError("handoff approval is unavailable")
            permit = self._approvals.consume(token)
            if envelope[0] != token or type(current) is not HandoffContext or envelope[1] != current:
                raise ValueError("handoff approval context changed or is unavailable")
            return ApprovedHandoff(permit, envelope[1])
