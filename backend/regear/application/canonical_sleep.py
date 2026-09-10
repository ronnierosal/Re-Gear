"""Durable coordinator for one canonical sleep/disconnect request.

The coordinator persists intent and step boundaries but deliberately does not
perform any directive. Steam UI, physical-button, game, process, removal,
portable-recovery, and sleep-continuation mechanisms remain outside this module.
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace

from ..domain.control_plane import (
    CapabilitySupport,
    EffectiveCapabilities,
    RequestIntent,
    RequestSource,
    TransitionRequest,
    WorkflowState,
)
from ..domain.game_compatibility import GameSaveCapability
from ..domain.models import EgpuPresence
from ..domain.sleep_workflow import (
    SleepFlow,
    SleepFlowEvent,
    SleepFlowStage,
    advance_sleep_flow,
    start_sleep_flow,
)
from ..domain.transition_journal import (
    JournalEventKind,
    TransitionJournal,
    append_journal_entry,
)
from ..ports.sleep_workflow import (
    SleepWorkflowObservation,
    SleepWorkflowObservationPort,
)
from ..ports.transition import MonotonicClockPort
from ..ports.transition_journal import TransitionJournalPort
from .process_release import TOKEN_RE
from .sleep_workflow_journal import (
    advance_sleep_journal,
    recover_interrupted_sleep_journal,
    start_sleep_journal,
)


_REQUEST_SOURCES = frozenset(
    {RequestSource.STEAM_MENU, RequestSource.PHYSICAL_BUTTON}
)
_FRESH_EVIDENCE_EVENTS = frozenset(
    {
        SleepFlowEvent.GAME_EXIT_VERIFIED,
        SleepFlowEvent.SOFTWARE_CLIENTS_RELEASED,
        SleepFlowEvent.EGPU_REMOVAL_VERIFIED,
        SleepFlowEvent.PORTABLE_RECOVERY_VERIFIED,
    }
)


@dataclass(frozen=True, slots=True)
class CanonicalSleepSession:
    request: TransitionRequest
    operation_id: str
    flow: SleepFlow
    last_sample_id: str
    bound_egpu_stable_id: str
    bound_capabilities: EffectiveCapabilities
    verified_save_completed: bool = False


@dataclass(frozen=True, slots=True)
class CanonicalSleepResult:
    accepted: bool
    code: str
    operation_id: str = ""
    flow: SleepFlow | None = None
    durable: bool = False
    action_required: bool = False


@dataclass(frozen=True, slots=True)
class CanonicalSleepStatus:
    code: str
    operation_id: str = ""
    request_id: str = ""
    source: RequestSource | None = None
    stage: SleepFlowStage | None = None
    acknowledgement_required: bool = False
    action_required: bool = False
    durable: bool = True


class CanonicalSleepWorkflowService:
    """Coordinate one request without executing its typed directives."""

    def __init__(
        self,
        *,
        observations: SleepWorkflowObservationPort,
        clock: MonotonicClockPort,
        journal_store: TransitionJournalPort,
        occurred_at: Callable[[], str],
        operation_id_factory: Callable[[], str] | None = None,
        request_ttl_ms: int = 15 * 60 * 1000,
    ) -> None:
        if request_ttl_ms <= 0 or request_ttl_ms > 60 * 60 * 1000:
            raise ValueError("canonical sleep request TTL is invalid")
        self._observations = observations
        self._clock = clock
        self._journal_store = journal_store
        self._occurred_at = occurred_at
        self._operation_id_factory = operation_id_factory or (
            lambda: f"sleep-operation-{secrets.token_hex(8)}"
        )
        self._request_ttl_ms = request_ttl_ms
        self._session: CanonicalSleepSession | None = None
        self._lock = threading.Lock()

    def start(self, request: TransitionRequest) -> CanonicalSleepResult:
        if request.intent is not RequestIntent.SLEEP:
            return CanonicalSleepResult(False, "sleep.intent_invalid")
        if request.source not in _REQUEST_SOURCES:
            return CanonicalSleepResult(False, "sleep.source_unsupported")
        if not self._lock.acquire(blocking=False):
            return CanonicalSleepResult(False, "sleep.concurrent_request")
        try:
            return self._start_locked(request)
        finally:
            self._lock.release()

    def _start_locked(self, request: TransitionRequest) -> CanonicalSleepResult:
        blocker = self._journal_blocker()
        if blocker:
            return CanonicalSleepResult(False, blocker, action_required=True)
        observed = self._observe()
        if observed is None:
            return CanonicalSleepResult(
                False, "sleep.observation_unavailable", action_required=True
            )
        if (
            request.source is RequestSource.PHYSICAL_BUTTON
            and observed.context.capabilities.power_button_interception
            not in {CapabilitySupport.EXPERIMENTAL, CapabilitySupport.VERIFIED}
        ):
            return CanonicalSleepResult(
                False,
                "sleep.physical_interception_unavailable",
                action_required=True,
            )
        if observed.generation != request.expected_generation:
            return CanonicalSleepResult(
                False, "sleep.request_generation_stale", action_required=True
            )
        operation_id = self._operation_id_factory()
        if not TOKEN_RE.fullmatch(operation_id):
            return CanonicalSleepResult(
                False, "sleep.operation_identity_invalid", action_required=True
            )
        flow = start_sleep_flow(
            request.request_id,
            observed.context,
            now_ms=self._clock.now_ms(),
            request_ttl_ms=self._request_ttl_ms,
        )
        try:
            journal = start_sleep_journal(
                operation_id,
                flow,
                observed.context.placement,
                occurred_at=self._occurred_at(),
            )
            self._journal_store.save(journal)
        except (OSError, ValueError):
            return CanonicalSleepResult(
                False,
                "sleep.journal_persist_failed",
                operation_id,
                flow,
                action_required=True,
            )
        self._session = CanonicalSleepSession(
            request,
            operation_id,
            flow,
            observed.sample_id,
            observed.egpu_stable_id,
            observed.context.capabilities,
        )
        return self._result(operation_id, flow)

    def advance(
        self, request_id: str, event: SleepFlowEvent
    ) -> CanonicalSleepResult:
        if not self._lock.acquire(blocking=False):
            return CanonicalSleepResult(False, "sleep.concurrent_request")
        try:
            return self._advance_locked(request_id, event)
        finally:
            self._lock.release()

    def _advance_locked(
        self, request_id: str, event: SleepFlowEvent
    ) -> CanonicalSleepResult:
        session = self._session
        if session is None or session.request.request_id != request_id:
            return CanonicalSleepResult(
                False, "sleep.session_not_found", action_required=True
            )
        if session.flow.stage in {
            SleepFlowStage.COMPLETED,
            SleepFlowStage.CANCELLED,
            SleepFlowStage.ACTION_REQUIRED,
            SleepFlowStage.SHUTDOWN_REQUIRED,
            SleepFlowStage.NORMAL_SLEEP_ALLOWED,
        }:
            return CanonicalSleepResult(
                False,
                "sleep.session_terminal",
                session.operation_id,
                session.flow,
                durable=True,
                action_required=True,
            )
        observed = self._observe()
        if observed is None:
            return CanonicalSleepResult(
                False,
                "sleep.observation_unavailable",
                session.operation_id,
                session.flow,
                durable=True,
                action_required=True,
            )
        context_error = self._context_error(session, event, observed)
        if context_error:
            return self._fail_session(session, observed, context_error)
        if (
            event in _FRESH_EVIDENCE_EVENTS
            and observed.sample_id == session.last_sample_id
        ):
            return CanonicalSleepResult(
                False,
                "sleep.fresh_observation_required",
                session.operation_id,
                session.flow,
                durable=True,
                action_required=True,
            )
        context = replace(
            observed.context,
            capabilities=session.bound_capabilities,
        )
        after = advance_sleep_flow(
            session.flow,
            event,
            context,
            now_ms=self._clock.now_ms(),
        )
        try:
            journal = self._journal_store.load_current()
            if journal is None or journal.operation_id != session.operation_id:
                raise ValueError("canonical sleep journal identity changed")
            journal = advance_sleep_journal(
                journal,
                session.flow,
                after,
                context.placement,
                occurred_at=self._occurred_at(),
            )
            self._journal_store.save(journal)
        except (OSError, ValueError):
            return CanonicalSleepResult(
                False,
                "sleep.journal_persist_failed",
                session.operation_id,
                session.flow,
                durable=False,
                action_required=True,
            )
        self._session = CanonicalSleepSession(
            session.request,
            session.operation_id,
            after,
            observed.sample_id,
            session.bound_egpu_stable_id,
            session.bound_capabilities,
            session.verified_save_completed,
        )
        return self._result(session.operation_id, after)

    def recover_interrupted(self) -> CanonicalSleepResult:
        if not self._lock.acquire(blocking=False):
            return CanonicalSleepResult(False, "sleep.concurrent_request")
        try:
            try:
                journal = self._journal_store.load_current()
            except Exception:
                return CanonicalSleepResult(
                    False, "sleep.journal_unavailable", action_required=True
                )
            if journal is None:
                self._session = None
                return CanonicalSleepResult(True, "sleep.no_recovery", durable=True)
            if not self._is_sleep_journal(journal):
                return CanonicalSleepResult(
                    False,
                    "sleep.foreign_journal",
                    journal.operation_id,
                    durable=True,
                    action_required=True,
                )
            if journal.terminal:
                terminal = journal.entries[-1]
                return CanonicalSleepResult(
                    True,
                    terminal.code,
                    journal.operation_id,
                    durable=True,
                    action_required=terminal.kind
                    in (JournalEventKind.BLOCKED, JournalEventKind.FAILED),
                )
            observed = self._observe()
            if observed is None:
                return CanonicalSleepResult(
                    False,
                    "sleep.recovery_observation_unavailable",
                    journal.operation_id,
                    durable=True,
                    action_required=True,
                )
            try:
                recovered = recover_interrupted_sleep_journal(
                    journal,
                    observed.context.placement,
                    exact_egpu_absence_verified=(
                        observed.context.egpu_presence is EgpuPresence.ABSENT
                    ),
                    occurred_at=self._occurred_at(),
                )
                self._journal_store.save(recovered)
            except (OSError, ValueError):
                return CanonicalSleepResult(
                    False,
                    "sleep.recovery_persist_failed",
                    journal.operation_id,
                    durable=False,
                    action_required=True,
                )
            self._session = None
            return CanonicalSleepResult(
                True,
                recovered.entries[-1].code,
                recovered.operation_id,
                durable=True,
                action_required=recovered.entries[-1].kind
                in (JournalEventKind.BLOCKED, JournalEventKind.FAILED),
            )
        finally:
            self._lock.release()

    def acknowledge(self, operation_id: str) -> bool:
        if not TOKEN_RE.fullmatch(operation_id):
            return False
        with self._lock:
            try:
                journal = self._journal_store.load_current()
                if (
                    journal is None
                    or not journal.terminal
                    or journal.operation_id != operation_id
                    or not self._is_sleep_journal(journal)
                ):
                    return False
                self._journal_store.clear_terminal(operation_id)
            except (OSError, ValueError):
                return False
            if (
                self._session is not None
                and self._session.operation_id == operation_id
            ):
                self._session = None
            return True

    def status(self) -> CanonicalSleepStatus:
        try:
            journal = self._journal_store.load_current()
        except Exception:
            return CanonicalSleepStatus(
                "sleep.journal_unavailable", action_required=True, durable=False
            )
        if journal is None:
            return CanonicalSleepStatus("sleep.idle")
        if not self._is_sleep_journal(journal):
            return CanonicalSleepStatus(
                "sleep.foreign_journal",
                journal.operation_id,
                journal.request_id,
                action_required=True,
            )
        session = self._session
        source = (
            session.request.source
            if session is not None and session.operation_id == journal.operation_id
            else None
        )
        stage = (
            session.flow.stage
            if session is not None and session.operation_id == journal.operation_id
            else None
        )
        if journal.terminal:
            terminal = journal.entries[-1]
            return CanonicalSleepStatus(
                terminal.code,
                journal.operation_id,
                journal.request_id,
                source,
                stage,
                acknowledgement_required=True,
                action_required=terminal.kind
                in (JournalEventKind.BLOCKED, JournalEventKind.FAILED),
            )
        return CanonicalSleepStatus(
            "sleep.in_progress",
            journal.operation_id,
            journal.request_id,
            source,
            stage,
            action_required=session is None,
        )

    def release_parent_operation_id(self, request_id: str) -> str:
        """Return the backend-owned parent only during the client-release step."""
        with self._lock:
            session = self._session
            if (
                session is None
                or session.request.request_id != request_id
                or session.flow.stage is not SleepFlowStage.RELEASING_CLIENTS
            ):
                return ""
            try:
                journal = self._journal_store.load_current()
            except Exception:
                return ""
            if (
                journal is None
                or journal.terminal
                or journal.operation_id != session.operation_id
                or not self._is_sleep_journal(journal)
            ):
                return ""
            return session.operation_id

    def game_close_parent_operation_id(self, request_id: str) -> str:
        """Return the backend-owned parent only during graceful game close."""
        with self._lock:
            session = self._session
            if (
                session is None
                or session.request.request_id != request_id
                or session.flow.stage is not SleepFlowStage.CLOSING_GAME
            ):
                return ""
            try:
                journal = self._journal_store.load_current()
            except Exception:
                return ""
            if (
                journal is None
                or journal.terminal
                or journal.operation_id != session.operation_id
                or not self._is_sleep_journal(journal)
            ):
                return ""
            return session.operation_id

    def game_close_requirements(
        self, request_id: str
    ) -> tuple[str, GameSaveCapability | None]:
        """Return parent identity and the save policy bound at consent time."""
        parent = self.game_close_parent_operation_id(request_id)
        if not parent:
            return "", None
        with self._lock:
            session = self._session
            if session is None or session.operation_id != parent:
                return "", None
            return parent, session.flow.save_capability

    def verified_game_save_completed(self, request_id: str) -> bool:
        with self._lock:
            session = self._session
            return bool(
                session is not None
                and session.request.request_id == request_id
                and session.flow.stage is SleepFlowStage.CLOSING_GAME
                and session.verified_save_completed
            )

    def game_save_requirements(self, request_id: str) -> tuple[str, str, str]:
        """Return the exact profile tuple only for a required save child."""
        parent = self.game_close_parent_operation_id(request_id)
        if not parent:
            return "", "", ""
        with self._lock:
            session = self._session
            if (
                session is None
                or session.operation_id != parent
                or session.flow.save_capability
                is not GameSaveCapability.VERIFIED_TRIGGERABLE_AUTOSAVE
                or session.verified_save_completed
            ):
                return "", "", ""
            capabilities = session.bound_capabilities
            return (
                parent,
                capabilities.host_profile_id,
                capabilities.egpu_profile_id,
            )

    def mark_verified_game_save_completed(
        self, request_id: str, parent_operation_id: str
    ) -> bool:
        """Accept only the durable verified child belonging to this session."""
        with self._lock:
            session = self._session
            if (
                session is None
                or session.request.request_id != request_id
                or session.operation_id != parent_operation_id
                or session.flow.stage is not SleepFlowStage.CLOSING_GAME
                or session.flow.save_capability
                is not GameSaveCapability.VERIFIED_TRIGGERABLE_AUTOSAVE
                or session.verified_save_completed
            ):
                return False
            try:
                journal = self._journal_store.load_current()
            except Exception:
                return False
            if (
                journal is None
                or journal.terminal
                or journal.operation_id != session.operation_id
                or not self._is_sleep_journal(journal)
                or not journal.entries
            ):
                return False
            last = journal.entries[-1]
            if (
                last.kind is not JournalEventKind.SUBSTEP_VERIFIED
                or last.code != "game.save_substep_verified"
                or dict(last.details).get("step_code") != "game_save.verified"
            ):
                return False
            self._session = replace(session, verified_save_completed=True)
            return True

    def _journal_blocker(self) -> str:
        try:
            current = self._journal_store.load_current()
        except Exception:
            return "sleep.journal_unavailable"
        if current is None:
            return ""
        return (
            "sleep.journal_acknowledgement_required"
            if current.terminal
            else "sleep.journal_recovery_required"
        )

    def _observe(self) -> SleepWorkflowObservation | None:
        try:
            return self._observations.observe()
        except Exception:
            return None

    @staticmethod
    def _context_error(
        session: CanonicalSleepSession,
        event: SleepFlowEvent,
        observed: SleepWorkflowObservation,
    ) -> str:
        context = observed.context
        if (
            context.capabilities.host_profile_id
            != session.bound_capabilities.host_profile_id
        ):
            return "sleep.host_profile_changed"
        removal_or_later = event in {
            SleepFlowEvent.EGPU_REMOVAL_VERIFIED,
            SleepFlowEvent.PORTABLE_RECOVERY_VERIFIED,
            SleepFlowEvent.ORIGINAL_SLEEP_CONTINUED,
        }
        if removal_or_later:
            if context.egpu_presence is not EgpuPresence.ABSENT:
                return "sleep.egpu_absence_unverified"
            return ""
        if session.bound_egpu_stable_id and (
            context.egpu_presence is not EgpuPresence.PRESENT
            or not context.exact_egpu_identity_verified
            or observed.egpu_stable_id != session.bound_egpu_stable_id
        ):
            return "sleep.egpu_identity_changed"
        return ""

    def _fail_session(
        self,
        session: CanonicalSleepSession,
        observed: SleepWorkflowObservation,
        code: str,
    ) -> CanonicalSleepResult:
        try:
            journal = self._journal_store.load_current()
            if journal is None or journal.operation_id != session.operation_id:
                raise ValueError("canonical sleep journal identity changed")
            failed = append_journal_entry(
                journal,
                kind=JournalEventKind.FAILED,
                occurred_at=self._occurred_at(),
                workflow_state=WorkflowState.ACTION_REQUIRED,
                placement=observed.context.placement,
                code=code,
                details=(("reason_code", code),),
            )
            self._journal_store.save(failed)
        except (OSError, ValueError):
            return CanonicalSleepResult(
                False,
                "sleep.journal_persist_failed",
                session.operation_id,
                session.flow,
                durable=False,
                action_required=True,
            )
        self._session = None
        return CanonicalSleepResult(
            False,
            code,
            session.operation_id,
            session.flow,
            durable=True,
            action_required=True,
        )

    @staticmethod
    def _is_sleep_journal(journal: TransitionJournal) -> bool:
        return bool(journal.entries and journal.entries[0].code == "sleep.requested")

    @staticmethod
    def _result(operation_id: str, flow: SleepFlow) -> CanonicalSleepResult:
        action_required = flow.stage in {
            SleepFlowStage.ACTION_REQUIRED,
            SleepFlowStage.SHUTDOWN_REQUIRED,
        }
        return CanonicalSleepResult(
            True,
            flow.reason_code,
            operation_id,
            flow,
            durable=True,
            action_required=action_required,
        )
