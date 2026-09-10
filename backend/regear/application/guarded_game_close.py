"""Consent-bound, exact-identity graceful game close as a sleep child step."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable

from ..domain.control_plane import WorkflowState
from ..domain.game_compatibility import GameSaveCapability
from ..domain.game_session import ActiveGameIdentity, GameSessionObservation
from ..domain.models import GameState
from ..domain.sleep_workflow import SleepFlowEvent
from ..domain.transition_journal import (
    JournalEventKind,
    SAFE_TOKEN,
    TransitionJournal,
    append_journal_entry,
)
from ..ports.game_close import GameCloseMechanismPort
from ..ports.game_session import GameSessionObservationPort
from ..ports.runtime_transition import DeadlineWaitPort
from ..ports.transition import MonotonicClockPort
from ..ports.transition_journal import TransitionJournalPort
from .canonical_sleep import CanonicalSleepResult, CanonicalSleepWorkflowService
from .process_release import TOKEN_RE


@dataclass(frozen=True, slots=True)
class GameCloseApproval:
    token: str
    parent_operation_id: str
    identity: ActiveGameIdentity
    observed_generation: str
    observed_sample_id: str
    expires_in_seconds: int


@dataclass(frozen=True, slots=True)
class GuardedGameClosePreview:
    ready: bool
    steam_app_id: str = ""
    approval_token: str = ""
    expires_in_seconds: int = 0
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GuardedGameCloseExecution:
    accepted: bool
    code: str
    parent_operation_id: str = ""
    game_exit_verified: bool = False
    action_required: bool = False
    sleep: CanonicalSleepResult | None = None


class GameCloseApprovalStore:
    def __init__(
        self,
        *,
        ttl_seconds: float = 120.0,
        max_tokens: int = 3,
        monotonic: Callable[[], float] = time.monotonic,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        if ttl_seconds <= 0 or ttl_seconds > 300:
            raise ValueError("game-close approval TTL is invalid")
        if max_tokens <= 0 or max_tokens > 10:
            raise ValueError("game-close approval bound is invalid")
        self._ttl_seconds = ttl_seconds
        self._max_tokens = max_tokens
        self._monotonic = monotonic
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(18))
        self._values: dict[str, tuple[float, GameCloseApproval]] = {}
        self._lock = threading.Lock()

    def issue(
        self,
        parent_operation_id: str,
        observed: GameSessionObservation,
    ) -> GameCloseApproval:
        if not TOKEN_RE.fullmatch(parent_operation_id):
            raise ValueError("game-close parent operation identity is invalid")
        if not observed.exact or observed.identity is None:
            raise ValueError("exact active game identity is required")
        with self._lock:
            self._expire_locked()
            while len(self._values) >= self._max_tokens:
                oldest = min(self._values, key=lambda token: self._values[token][0])
                self._values.pop(oldest)
            token = self._token_factory()
            if not TOKEN_RE.fullmatch(token) or token in self._values:
                raise ValueError("game-close approval token is invalid")
            approval = GameCloseApproval(
                token,
                parent_operation_id,
                observed.identity,
                observed.generation,
                observed.sample_id,
                max(1, int(self._ttl_seconds)),
            )
            self._values[token] = (self._monotonic(), approval)
            return approval

    def consume(self, token: str) -> GameCloseApproval:
        if not TOKEN_RE.fullmatch(token):
            raise ValueError("game-close approval token is invalid")
        with self._lock:
            self._expire_locked()
            value = self._values.pop(token, None)
            if value is None:
                raise ValueError("game-close approval expired or was already used")
            return value[1]

    def _expire_locked(self) -> None:
        cutoff = self._monotonic() - self._ttl_seconds
        for token in [
            token for token, (created, _) in self._values.items() if created < cutoff
        ]:
            self._values.pop(token, None)


class GuardedGameCloseService:
    def __init__(
        self,
        *,
        sleep: CanonicalSleepWorkflowService,
        observations: GameSessionObservationPort,
        mechanism: GameCloseMechanismPort,
        approvals: GameCloseApprovalStore,
        journal_store: TransitionJournalPort,
        clock: MonotonicClockPort,
        waiter: DeadlineWaitPort,
        occurred_at: Callable[[], str],
        close_deadline_ms: int = 5_000,
        poll_interval_ms: int = 100,
    ) -> None:
        if close_deadline_ms <= 0 or close_deadline_ms > 30_000:
            raise ValueError("game-close deadline is invalid")
        if poll_interval_ms <= 0 or poll_interval_ms > 250:
            raise ValueError("game-close poll interval is invalid")
        self._sleep = sleep
        self._observations = observations
        self._mechanism = mechanism
        self._approvals = approvals
        self._journal_store = journal_store
        self._clock = clock
        self._waiter = waiter
        self._occurred_at = occurred_at
        self._deadline_ms = close_deadline_ms
        self._poll_ms = poll_interval_ms
        self._lock = threading.Lock()

    def preview(
        self, request_id: str, *, user_confirmed: bool
    ) -> GuardedGameClosePreview:
        parent, save_capability = self._sleep.game_close_requirements(request_id)
        if not parent:
            return GuardedGameClosePreview(
                False, blockers=("sleep.game_close_step_inactive",)
            )
        if save_capability is GameSaveCapability.VERIFIED_TRIGGERABLE_AUTOSAVE:
            try:
                save_completed = self._sleep.verified_game_save_completed(request_id)
            except Exception:
                save_completed = False
            if not save_completed:
                return GuardedGameClosePreview(
                    False, blockers=("game.verified_save_step_required",)
                )
        observed = self._observe()
        if observed is None or not observed.exact or observed.identity is None:
            return GuardedGameClosePreview(
                False, blockers=("game.identity_unverified",)
            )
        if not user_confirmed:
            return GuardedGameClosePreview(True, observed.identity.steam_app_id)
        try:
            approval = self._approvals.issue(parent, observed)
        except ValueError:
            return GuardedGameClosePreview(
                False, blockers=("game.approval_unavailable",)
            )
        return GuardedGameClosePreview(
            True,
            approval.identity.steam_app_id,
            approval.token,
            approval.expires_in_seconds,
        )

    def execute(
        self, request_id: str, approval_token: str
    ) -> GuardedGameCloseExecution:
        if not self._lock.acquire(blocking=False):
            return GuardedGameCloseExecution(
                False, "game.close_concurrent", action_required=True
            )
        try:
            return self._execute_locked(request_id, approval_token)
        finally:
            self._lock.release()

    def _execute_locked(
        self, request_id: str, approval_token: str
    ) -> GuardedGameCloseExecution:
        try:
            approval = self._approvals.consume(approval_token)
        except ValueError:
            return GuardedGameCloseExecution(False, "game.approval_invalid")
        parent = self._sleep.game_close_parent_operation_id(request_id)
        if not parent or parent != approval.parent_operation_id:
            return GuardedGameCloseExecution(
                False,
                "game.parent_changed",
                approval.parent_operation_id,
                action_required=True,
            )
        observed = self._observe()
        if (
            observed is None
            or observed.sample_id == approval.observed_sample_id
            or observed.generation != approval.observed_generation
            or not observed.exact
            or observed.identity != approval.identity
        ):
            return self._fail(
                approval.parent_operation_id,
                "game.identity_changed",
                observed,
            )
        journal = self._start_substep(approval.parent_operation_id, observed)
        if journal is None:
            return GuardedGameCloseExecution(
                False,
                "game.journal_persist_failed",
                approval.parent_operation_id,
                action_required=True,
            )
        try:
            mechanism = self._mechanism.request_close(approval.identity)
        except Exception:
            return self._fail(
                approval.parent_operation_id,
                "game.close_mechanism_failed",
                observed,
            )
        if not mechanism.accepted:
            return self._fail(
                approval.parent_operation_id,
                mechanism.code,
                observed,
            )
        started = self._clock.now_ms()
        previous_sample = observed.sample_id
        while self._clock.now_ms() - started < self._deadline_ms:
            rescanned = self._observe()
            if rescanned is None:
                return self._fail(
                    approval.parent_operation_id,
                    "game.rescan_unavailable",
                    observed,
                )
            if rescanned.sample_id == previous_sample:
                if not self._wait():
                    return self._fail(
                        approval.parent_operation_id,
                        "game.wait_failed",
                        observed,
                    )
                continue
            previous_sample = rescanned.sample_id
            if rescanned.state is GameState.IDLE:
                if not self._verify_substep(approval.parent_operation_id, rescanned):
                    return GuardedGameCloseExecution(
                        False,
                        "game.journal_persist_failed",
                        approval.parent_operation_id,
                        action_required=True,
                    )
                sleep = self._sleep.advance(
                    request_id, SleepFlowEvent.GAME_EXIT_VERIFIED
                )
                return GuardedGameCloseExecution(
                    sleep.accepted,
                    "game.exit_verified" if sleep.accepted else sleep.code,
                    approval.parent_operation_id,
                    game_exit_verified=True,
                    action_required=sleep.action_required,
                    sleep=sleep,
                )
            if not rescanned.exact or rescanned.identity != approval.identity:
                return self._fail(
                    approval.parent_operation_id,
                    "game.identity_changed",
                    rescanned,
                )
            if not self._wait():
                return self._fail(
                    approval.parent_operation_id,
                    "game.wait_failed",
                    rescanned,
                )
        return self._fail(
            approval.parent_operation_id,
            "game.close_timeout",
            observed,
        )

    def _start_substep(
        self, parent: str, observed: GameSessionObservation
    ) -> TransitionJournal | None:
        return self._append(
            parent,
            JournalEventKind.SUBSTEP_STARTED,
            "game.close_substep_started",
            observed,
        )

    def _verify_substep(
        self, parent: str, observed: GameSessionObservation
    ) -> bool:
        return self._append(
            parent,
            JournalEventKind.SUBSTEP_VERIFIED,
            "game.close_substep_verified",
            observed,
        ) is not None

    def _fail(
        self,
        parent: str,
        code: str,
        observed: GameSessionObservation | None,
    ) -> GuardedGameCloseExecution:
        journal = self._append(
            parent,
            JournalEventKind.FAILED,
            code if SAFE_TOKEN.fullmatch(code) else "game.close_failed",
            observed,
        )
        return GuardedGameCloseExecution(
            False,
            code if SAFE_TOKEN.fullmatch(code) else "game.close_failed",
            parent,
            action_required=True,
        ) if journal is not None else GuardedGameCloseExecution(
            False,
            "game.journal_persist_failed",
            parent,
            action_required=True,
        )

    def _append(
        self,
        parent: str,
        kind: JournalEventKind,
        code: str,
        observed: GameSessionObservation | None,
    ) -> TransitionJournal | None:
        try:
            journal = self._journal_store.load_current()
            if (
                journal is None
                or journal.terminal
                or journal.operation_id != parent
                or not journal.entries
                or journal.entries[0].code != "sleep.requested"
            ):
                raise ValueError("game-close parent journal changed")
            active = next(
                (
                    entry
                    for entry in reversed(journal.entries)
                    if entry.kind is JournalEventKind.STEP_STARTED
                ),
                None,
            )
            if active is None or dict(active.details).get("step_code") != "closing_game":
                raise ValueError("game-close parent step changed")
            journal = append_journal_entry(
                journal,
                kind=kind,
                occurred_at=self._occurred_at(),
                workflow_state=(
                    WorkflowState.ACTION_REQUIRED
                    if kind is JournalEventKind.FAILED
                    else WorkflowState.SLEEP_PENDING_DISCONNECT
                ),
                placement=journal.entries[-1].placement,
                code=code,
                details=(
                    (("step_code", "game_close.graceful"),)
                    if kind
                    in {
                        JournalEventKind.SUBSTEP_STARTED,
                        JournalEventKind.SUBSTEP_VERIFIED,
                    }
                    else ()
                ),
            )
            self._journal_store.save(journal)
            return journal
        except (OSError, ValueError):
            return None

    def _observe(self) -> GameSessionObservation | None:
        try:
            return self._observations.observe()
        except Exception:
            return None

    def _wait(self) -> bool:
        try:
            self._waiter.wait_ms(self._poll_ms)
            return True
        except Exception:
            return False
