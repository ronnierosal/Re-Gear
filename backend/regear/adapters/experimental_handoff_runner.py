"""Inert transaction-budget contract, without a runtime consumer or native port.

Injected ports/intents are server-owned fixture seams here. This class cannot
authenticate hardware/session evidence or a durable claim by itself. Production
composition, command wiring, audio and secure-store deadlines remain absent.
No subprocess, argv, collector, persistence or automatic recovery is provided.
"""
from dataclasses import dataclass
from enum import StrEnum
import math
import threading
import time
from typing import Callable

from ..application.experimental_handoff_approval import (
    ApprovedHandoff, HandoffContext, HandoffAudioOperation, HandoffAudioPermission,
)
from ..ports.presentation_activation import UserServiceOperation
from ..domain.control_plane import ExperimentalTransitionPermit


class RunnerOperation(StrEnum):
    PREFLIGHT_SNAPSHOT = "preflight_snapshot"
    SNAPSHOT = "snapshot"
    RELOAD = "reload"
    VERIFY_UNIT = "verify_unit"
    RESTART = "restart"
    OBSERVE_INVOCATION = "observe_invocation"
    AUDIO_DUMP = "audio_dump"
    AUDIO_SET_DEFAULT = "audio_set_default"
    SAFETY_STATE_WRITE = "safety_state_write"


# Phase membership, aggregate cap, per-phase cap, per-call seconds, typed op.
_RULES = {
    RunnerOperation.PREFLIGHT_SNAPSHOT: ({"preflight"}, 4, 4, 1.0, None),
    RunnerOperation.SNAPSHOT: ({"forward", "recovery"}, 128, 64, 1.0, None),
    RunnerOperation.RELOAD: ({"forward", "recovery"}, 2, 1, 8.0, UserServiceOperation.DAEMON_RELOAD),
    RunnerOperation.VERIFY_UNIT: ({"forward", "recovery"}, 2, 1, 8.0, UserServiceOperation.VERIFY_GAMESCOPE_UNIT),
    RunnerOperation.RESTART: ({"forward", "recovery"}, 2, 1, 8.0, UserServiceOperation.RESTART_GAMESCOPE_SESSION),
    RunnerOperation.OBSERVE_INVOCATION: ({"recovery"}, 62, 62, .25, UserServiceOperation.OBSERVE_FILTER_GAMESCOPE),
    RunnerOperation.AUDIO_DUMP: ({"forward", "recovery"}, 32, 16, 1.0, None),
    RunnerOperation.AUDIO_SET_DEFAULT: ({"forward", "recovery"}, 2, 1, 5.0, None),
}

_AUDIO = {RunnerOperation.AUDIO_DUMP: HandoffAudioOperation.DUMP,
          RunnerOperation.AUDIO_SET_DEFAULT: HandoffAudioOperation.SET_DEFAULT}


@dataclass(frozen=True, slots=True)
class AudioValidation:
    """Fresh authenticated projection supplied by a future server-owned adapter.

    This fixture seam does not collect/authenticate evidence or form commands.
    Hash equality alone cannot prove current ownership or availability.
    """
    permission: HandoffAudioPermission
    request_id: str
    claim_id: str
    boot_id: str
    user_context_sha256: str
    snapshot_generation: str
    target_sink_sha256: str
    available: bool
    observed_at: float


@dataclass(frozen=True, slots=True)
class RecoveryIntent:
    """Ephemeral projection seam, not a new journal or recovery authority.

    A future adapter must derive this from the same durable request/claim and
    fresh source checks. RPC booleans must never supply these values.
    """
    request_id: str
    claim_id: str
    boot_id: str
    durable: bool
    source_revalidated: bool


@dataclass(frozen=True, slots=True)
class RunnerOutcome:
    accepted: bool
    code: str


class HandoffRunnerContract:
    def __init__(self, *, approved: ApprovedHandoff, claim_id: str,
                 qualified_context: HandoffContext | None,
                 read_claim: Callable, read_recovery_intent: Callable,
                 read_audio: Callable | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self._approved = approved
        self._claim_id = claim_id
        self._qualified = (type(approved) is ApprovedHandoff
                           and type(qualified_context) is HandoffContext
                           and qualified_context == approved.context
                           and type(approved.permit) is ExperimentalTransitionPermit
                           and approved.permit.observed_generation == qualified_context.snapshot_generation
                           and approved.permit.target_placement is qualified_context.target_placement
                           and approved.permit.host_profile_id == qualified_context.host_profile_id
                           and approved.permit.egpu_profile_id == qualified_context.egpu_profile_id
                           and approved.permit.egpu_stable_id == qualified_context.egpu_stable_id
                           and approved.permit.portable_vulkan_trial is False
                           and approved.permit.portable_trial_schema_version == 1
                           and type(claim_id) is str and bool(claim_id))
        self._read_claim = read_claim
        self._read_recovery_intent = read_recovery_intent
        self._read_audio = read_audio
        self._clock = clock
        self._lock = threading.Lock()
        self._closed = False
        self._blocked = False
        self._phase = "preflight"
        self._recovery_requested = False
        self._counts = {}
        self._phase_counts = {}
        self._last = None
        started = self._now()
        self._deadline = (started or 0) + 35.0
        self._phase_deadline = (started or 0) + 5.0

    def _now(self):
        try:
            value = self._clock()
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or (self._last is not None and value < self._last)):
                self._closed = True
                return None
            self._last = value
            return value
        except Exception:
            self._closed = True
            return None
        except BaseException:
            self._closed = True
            raise

    def _live(self, *, transition=False):
        if self._closed or not self._qualified:
            return None
        try:
            expected = self._approved.permit.plan_id, self._claim_id
            if self._read_claim() != expected:
                self._closed = True
                return None
        except Exception:
            self._closed = True
            return None
        except BaseException:
            self._closed = True
            raise
        now = self._now()
        if now is None or now >= self._deadline:
            self._closed = True
            return None
        if not transition and (self._blocked or now >= self._phase_deadline):
            self._blocked = True
            return None
        return now

    def begin_forward(self) -> bool:
        if not self._lock.acquire(blocking=False):
            return False
        try:
            now = self._live()
            if now is None or self._phase != "preflight":
                return False
            self._phase = "forward"
            self._phase_deadline = min(now + 15.0, self._deadline)
            return True
        finally:
            self._lock.release()

    def begin_recovery(self) -> bool:
        if not self._lock.acquire(blocking=False):
            return False
        try:
            now = self._live(transition=True)
            if now is None or self._phase != "forward" or self._recovery_requested:
                return False
            self._recovery_requested = True
            # An attempted recovery qualification ends forward authority even
            # when the read fails or returns an invalid/uncertain projection.
            self._blocked = True
            try:
                intent = self._read_recovery_intent()
            except Exception:
                return False
            except BaseException:
                self._closed = True
                raise
            if (type(intent) is not RecoveryIntent or intent.durable is not True
                    or intent.source_revalidated is not True
                    or (intent.request_id, intent.claim_id, intent.boot_id) != (
                        self._approved.permit.plan_id, self._claim_id, self._approved.context.boot_id)):
                return False
            now = self._live(transition=True)
            if now is None:
                return False
            # Counters and the transaction deadline never reset at this boundary.
            self._phase = "recovery"
            self._blocked = False
            self._phase_deadline = min(now + 15.0, self._deadline)
            return True
        finally:
            self._lock.release()

    def attempt(self, operation: RunnerOperation, port: Callable[[float], object]) -> RunnerOutcome:
        """Account before one inert delegated call; never retry or form a command."""
        denied = RunnerOutcome(False, "handoff_runner.unavailable")
        if not self._lock.acquire(blocking=False):
            return denied
        try:
            now = self._live()
            if now is None or type(operation) is not RunnerOperation:
                return denied
            # Storage lacks a qualified durable adapter. Never skip safety
            # writes or infer write capability from inspection or a boolean.
            if operation not in _RULES:
                return denied
            phases, total_cap, phase_cap, call_cap, user_operation = _RULES[operation]
            if self._phase not in phases:
                return denied
            if user_operation is not None and user_operation not in self._approved.context.allowed_operations:
                return denied
            permission = self._approved.context.audio
            if operation in _AUDIO and (permission is None or self._read_audio is None
                    or _AUDIO[operation] not in permission.operations):
                return denied
            key = self._phase, operation
            if self._counts.get(operation, 0) >= total_cap or self._phase_counts.get(key, 0) >= phase_cap:
                self._blocked = True
                return denied
            timeout = min(call_cap, self._phase_deadline - now, self._deadline - now)
            self._counts[operation] = self._counts.get(operation, 0) + 1
            self._phase_counts[key] = self._phase_counts.get(key, 0) + 1
            if operation in _AUDIO:
                target = (permission.rollback_sink_sha256 if self._phase == "recovery"
                          else permission.target_sink_sha256)
                try:
                    evidence = self._read_audio(operation, target, timeout)
                    checked = self._live()
                    c = self._approved.context
                    valid = (checked is not None and type(evidence) is AudioValidation
                             and type(evidence.permission) is HandoffAudioPermission
                             and evidence.permission == permission and evidence.available is True
                             and type(evidence.observed_at) in (int, float)
                             and math.isfinite(evidence.observed_at)
                             and 0 <= checked - evidence.observed_at <= 1.0
                             and (evidence.request_id, evidence.claim_id, evidence.boot_id,
                                  evidence.user_context_sha256, evidence.snapshot_generation,
                                  evidence.target_sink_sha256) == (
                                     self._approved.permit.plan_id, self._claim_id, c.boot_id,
                                     c.user_context_sha256, c.snapshot_generation, target))
                    if not valid:
                        self._blocked = True
                        return RunnerOutcome(False, "handoff_runner.uncertain")
                    timeout = min(timeout - (checked - now), self._phase_deadline - checked,
                                  self._deadline - checked)
                    if timeout <= 0:
                        self._blocked = True
                        return RunnerOutcome(False, "handoff_runner.uncertain")
                    now = checked
                except Exception:
                    self._blocked = True
                    return RunnerOutcome(False, "handoff_runner.uncertain")
                except BaseException:
                    self._closed = True
                    raise
            try:
                result = port(timeout)
            except Exception:
                self._blocked = True
                return RunnerOutcome(False, "handoff_runner.uncertain")
            except BaseException:
                self._closed = True
                raise
            try:
                succeeded = result is True or getattr(result, "ok", None) is True
            except Exception:
                succeeded = False
            except BaseException:
                self._closed = True
                raise
            finished = self._live()
            if finished is None or finished > now + timeout or not succeeded:
                self._blocked = True
                return RunnerOutcome(False, "handoff_runner.uncertain")
            return RunnerOutcome(True, "handoff_runner.fixture_completed")
        finally:
            self._lock.release()
