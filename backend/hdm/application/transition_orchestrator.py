"""Durable detect/validate/attempt/verify/commit transition orchestration."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from ..domain.control_plane import (
    PlacementState,
    RecoveryOutcome,
    TransitionFailure,
    TransitionOutcome,
    TransitionOutcomeKind,
    TransitionPlan,
    WorkflowState,
)
from ..domain.inference import infer_placement
from ..domain.transition_journal import (
    JournalEventKind,
    TransitionJournal,
    append_journal_entry,
)
from ..ports.runtime_transition import (
    DeadlineWaitPort,
    RuntimeTransitionMechanismPort,
)
from ..ports.transition import (
    MechanismResult,
    MonotonicClockPort,
    TransitionObservationPort,
)
from ..ports.transition_journal import TransitionJournalPort
from .transition_runtime_policy import StrictRuntimeTransitionPolicy


VERIFY_POLL_MS = 100


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class RuntimeTransitionResult:
    journal: TransitionJournal | None
    outcome: TransitionOutcome
    durable: bool


class TransitionOrchestrator:
    def __init__(
        self,
        *,
        observations: TransitionObservationPort,
        mechanism: RuntimeTransitionMechanismPort,
        journal_store: TransitionJournalPort,
        clock: MonotonicClockPort,
        waiter: DeadlineWaitPort,
        occurred_at: Callable[[], str] = _utc_now,
        policy: StrictRuntimeTransitionPolicy | None = None,
    ) -> None:
        self._observations = observations
        self._mechanism = mechanism
        self._journal_store = journal_store
        self._clock = clock
        self._waiter = waiter
        self._occurred_at = occurred_at
        self._policy = policy or StrictRuntimeTransitionPolicy()
        self._lock = threading.Lock()

    def run(self, plan: TransitionPlan, *, portable_vulkan_trial: bool = False) -> RuntimeTransitionResult:
        if not self._lock.acquire(blocking=False):
            return self._without_journal(
                plan.from_placement, "transition.concurrent_request"
            )
        try:
            return self._run_locked(plan, portable_vulkan_trial=portable_vulkan_trial)
        finally:
            self._lock.release()

    def _run_locked(self, plan: TransitionPlan, *, portable_vulkan_trial: bool = False) -> RuntimeTransitionResult:
        try:
            current = self._journal_store.load_current()
        except Exception:
            return self._without_journal(
                PlacementState.UNKNOWN, "journal.load_failed", failed=True
            )
        if current is not None:
            code = (
                "journal.terminal_unacknowledged"
                if current.terminal
                else "journal.recovery_required"
            )
            return RuntimeTransitionResult(
                current,
                self._outcome(
                    TransitionOutcomeKind.BLOCKED,
                    current.entries[-1].placement if current.entries else PlacementState.UNKNOWN,
                    code,
                ),
                True,
            )

        journal = TransitionJournal(plan.plan_id, plan.request_id)
        try:
            journal = self._append_save(
                journal,
                JournalEventKind.REQUESTED,
                WorkflowState.IDLE,
                plan.from_placement,
                "request.accepted",
                tuple(sorted((
                    ("capability", "presentation_transition"),
                    ("target_placement", plan.target_placement.value),
                ) + ((("launch_policy", "portable_vulkan_trial"),) if portable_vulkan_trial else ()))),
            )
        except Exception:
            return self._without_journal(
                plan.from_placement, "journal.persist_failed", failed=True
            )

        initial = self._observe()
        if initial is None:
            return self._terminal(journal, plan.from_placement, "observation.unavailable")
        initial_placement = infer_placement(initial.snapshot)
        try:
            journal = self._append_save(
                journal,
                JournalEventKind.OBSERVED,
                plan.workflow_state,
                initial_placement,
                "snapshot.observed",
            )
        except Exception:
            return RuntimeTransitionResult(
                journal,
                self._outcome(
                    TransitionOutcomeKind.FAILED,
                    initial_placement,
                    "journal.persist_failed",
                    failed=True,
                ),
                False,
            )
        if initial.generation != plan.observed_generation:
            return self._blocked(journal, initial_placement, "observation.stale")
        if initial_placement is plan.target_placement and not plan.steps:
            try:
                journal = self._append_save(
                    journal,
                    JournalEventKind.VALIDATED,
                    plan.workflow_state,
                    initial_placement,
                    "plan.validated",
                )
                journal = self._append_save(
                    journal,
                    JournalEventKind.PLANNED,
                    plan.workflow_state,
                    initial_placement,
                    "plan.ready",
                )
            except Exception:
                return self._terminal(
                    journal, initial_placement, "journal.persist_failed"
                )
            return self._commit_no_op(journal, initial_placement)
        blockers = self._policy.blockers(plan, initial.snapshot, plan.from_placement)
        if blockers:
            return self._blocked(journal, initial_placement, blockers[0])
        try:
            journal = self._append_save(
                journal,
                JournalEventKind.VALIDATED,
                plan.workflow_state,
                initial_placement,
                "plan.validated",
            )
            journal = self._append_save(
                journal,
                JournalEventKind.PLANNED,
                plan.workflow_state,
                initial_placement,
                "plan.ready",
            )
        except Exception:
            return self._terminal(journal, initial_placement, "journal.persist_failed")
        if not plan.steps:
            return self._blocked(journal, initial_placement, "plan.empty")

        last = initial
        placement = initial_placement
        for step in plan.steps:
            before = self._observe()
            if before is None:
                return self._blocked(journal, placement, "observation.unavailable")
            placement = infer_placement(before.snapshot)
            blockers = self._policy.blockers(plan, before.snapshot, placement)
            if placement is not infer_placement(last.snapshot):
                blockers = ("placement.changed", *blockers)
            if blockers:
                return self._blocked(journal, placement, blockers[0])
            try:
                journal = self._append_save(
                    journal,
                    JournalEventKind.STEP_STARTED,
                    plan.workflow_state,
                    placement,
                    "step.started",
                    (("step_code", step.code.value),),
                )
            except Exception:
                return self._terminal(journal, placement, "journal.persist_failed")

            started = self._clock.now_ms()
            try:
                mechanism_result = self._mechanism.apply(
                    step, plan.binding, before.snapshot
                )
            except Exception:
                mechanism_result = None
            if mechanism_result is None:
                return self._recover(
                    journal, plan, placement, "mechanism.exception", before.generation
                )
            if not mechanism_result.succeeded:
                return self._recover(
                    journal, plan, placement, mechanism_result.code, before.generation
                )
            verified = self._verify_step(plan, step, before.generation, started)
            if verified is None:
                return self._recover(
                    journal,
                    plan,
                    placement,
                    "step.verification_timeout",
                    before.generation,
                )
            placement = infer_placement(verified.snapshot)
            try:
                journal = self._append_save(
                    journal,
                    JournalEventKind.STEP_VERIFIED,
                    plan.workflow_state,
                    placement,
                    "step.verified",
                    (("step_code", step.code.value),),
                )
            except Exception:
                return self._recover(
                    journal,
                    plan,
                    placement,
                    "journal.persist_failed",
                    verified.generation,
                    durable=False,
                )
            last = verified

        if placement is not plan.target_placement:
            return self._recover(
                journal, plan, placement, "target.verification_failed", last.generation
            )
        try:
            journal = self._append_save(
                journal,
                JournalEventKind.COMMITTED,
                WorkflowState.IDLE,
                placement,
                "transition.committed",
            )
        except Exception:
            return self._recover(
                journal,
                plan,
                placement,
                "journal.persist_failed",
                last.generation,
                durable=False,
            )
        return RuntimeTransitionResult(
            journal,
            TransitionOutcome(
                TransitionOutcomeKind.SUCCEEDED, placement, WorkflowState.IDLE
            ),
            True,
        )

    def recover_interrupted(
        self, *, recovery_deadline_ms: int = 15_000
    ) -> RuntimeTransitionResult:
        if recovery_deadline_ms <= 0 or recovery_deadline_ms > 60_000:
            raise ValueError("interrupted recovery deadline is invalid")
        if not self._lock.acquire(blocking=False):
            return self._without_journal(
                PlacementState.UNKNOWN, "transition.concurrent_request"
            )
        try:
            return self._recover_interrupted_locked(recovery_deadline_ms)
        finally:
            self._lock.release()

    def _recover_interrupted_locked(self, deadline_ms):
        try:
            journal = self._journal_store.load_current()
        except Exception:
            return self._without_journal(
                PlacementState.UNKNOWN, "journal.load_failed", failed=True
            )
        if journal is None:
            return RuntimeTransitionResult(
                None,
                TransitionOutcome(
                    TransitionOutcomeKind.NO_OP,
                    PlacementState.UNKNOWN,
                    WorkflowState.IDLE,
                ),
                True,
            )
        last = journal.entries[-1] if journal.entries else None
        if journal.terminal:
            placement = last.placement if last else PlacementState.UNKNOWN
            return RuntimeTransitionResult(
                journal,
                self._outcome(
                    TransitionOutcomeKind.BLOCKED,
                    placement,
                    "journal.terminal_unacknowledged",
                ),
                True,
            )
        if last is None:
            return RuntimeTransitionResult(
                journal,
                self._outcome(
                    TransitionOutcomeKind.FAILED,
                    PlacementState.UNKNOWN,
                    "journal.invalid",
                    failed=True,
                ),
                False,
            )
        source = journal.entries[0].placement
        observed = self._observe()
        placement = (
            infer_placement(observed.snapshot)
            if observed is not None
            else PlacementState.UNKNOWN
        )
        mutation_may_have_started = last.kind in {
            JournalEventKind.STEP_STARTED,
            JournalEventKind.STEP_VERIFIED,
            JournalEventKind.RECOVERY_STARTED,
        }
        if not mutation_may_have_started:
            return self._terminal(
                journal, placement, "transition.interrupted_before_mutation"
            )
        if last.kind is not JournalEventKind.RECOVERY_STARTED:
            try:
                journal = self._append_save(
                    journal,
                    JournalEventKind.RECOVERY_STARTED,
                    WorkflowState.RECOVERING,
                    placement,
                    "recovery.started",
                    (("reason_code", "transition.interrupted"),),
                )
            except Exception:
                return RuntimeTransitionResult(
                    journal,
                    self._outcome(
                        TransitionOutcomeKind.FAILED,
                        placement,
                        "journal.persist_failed",
                        failed=True,
                    ),
                    False,
                )
        started = self._clock.now_ms()
        prior_generation = observed.generation if observed is not None else ""
        # A queued restart or partially changed audio can outlive the source
        # display snapshot. Always recover and verify a fresh generation.
        try:
            result = self._mechanism.recover(
                source,
                None,
                observed.snapshot if observed is not None else None,
            )
        except Exception:
            result = None
        verified = self._verify_recovery(
            source, prior_generation, started, deadline_ms
        )
        if result is not None and result.succeeded and verified is not None:
            recovered = infer_placement(verified.snapshot)
            try:
                journal = self._append_save(
                    journal,
                    JournalEventKind.RECOVERY_VERIFIED,
                    WorkflowState.IDLE,
                    recovered,
                    "recovery.verified",
                    (("recovery_code", result.code),),
                )
            except Exception:
                return RuntimeTransitionResult(
                    journal,
                    self._outcome(
                        TransitionOutcomeKind.FAILED,
                        recovered,
                        "journal.persist_failed",
                        failed=True,
                    ),
                    False,
                )
            return RuntimeTransitionResult(
                journal,
                TransitionOutcome(
                    TransitionOutcomeKind.RECOVERED,
                    recovered,
                    WorkflowState.IDLE,
                    failure=TransitionFailure(
                        "transition.interrupted", "transition.interrupted", True
                    ),
                    recovery=RecoveryOutcome(True, True, recovered),
                ),
                True,
            )
        recovery_code = result.code if result is not None else "recovery.exception"
        try:
            journal = self._append_save(
                journal,
                JournalEventKind.FAILED,
                WorkflowState.ACTION_REQUIRED,
                placement,
                "recovery.failed",
                (("reason_code", "transition.interrupted"),),
            )
            durable = True
        except Exception:
            durable = False
        return RuntimeTransitionResult(
            journal,
            TransitionOutcome(
                TransitionOutcomeKind.FAILED,
                placement,
                WorkflowState.ACTION_REQUIRED,
                failure=TransitionFailure(
                    "transition.interrupted", "transition.interrupted", False, True
                ),
                recovery=RecoveryOutcome(
                    True,
                    False,
                    placement,
                    TransitionFailure(
                        recovery_code, recovery_code, False, True
                    ),
                ),
            ),
            durable,
        )

    def _verify_step(self, plan, step, prior_generation, started):
        while True:
            now = self._clock.now_ms()
            elapsed = now - started
            if elapsed < 0 or elapsed > step.deadline_ms:
                return None
            observed = self._observe()
            if observed is not None and observed.generation != prior_generation:
                placement = infer_placement(observed.snapshot)
                blockers = self._policy.blockers(plan, observed.snapshot, placement)
                if (
                    not blockers
                    and step.expected_placement is not None
                    and placement is step.expected_placement
                ):
                    return observed
            remaining = step.deadline_ms - (self._clock.now_ms() - started)
            if remaining <= 0:
                return None
            self._waiter.wait_ms(min(VERIFY_POLL_MS, remaining))

    def _recover(
        self,
        journal,
        plan,
        placement,
        reason,
        prior_generation,
        *,
        durable=True,
    ):
        try:
            journal = self._append_save(
                journal,
                JournalEventKind.RECOVERY_STARTED,
                WorkflowState.RECOVERING,
                placement,
                "recovery.started",
                (("reason_code", reason),),
            )
        except Exception:
            durable = False
        before = self._observe()
        started = self._clock.now_ms()
        # A queued restart or partially changed audio can outlive the source
        # display snapshot. Always recover and verify a fresh generation.
        try:
            result = self._mechanism.recover(
                plan.from_placement,
                plan.binding,
                before.snapshot if before is not None else None,
            )
        except Exception:
            result = None
        verified = self._verify_recovery(
            plan.from_placement,
            before.generation if before is not None else prior_generation,
            started,
            plan.recovery_deadline_ms,
        )
        if result is not None and result.succeeded and verified is not None:
            recovered = infer_placement(verified.snapshot)
            if durable:
                try:
                    journal = self._append_save(
                        journal,
                        JournalEventKind.RECOVERY_VERIFIED,
                        WorkflowState.IDLE,
                        recovered,
                        "recovery.verified",
                        (("recovery_code", result.code),),
                    )
                except Exception:
                    durable = False
            if durable:
                failure = TransitionFailure(reason, reason, True)
                return RuntimeTransitionResult(
                    journal,
                    TransitionOutcome(
                        TransitionOutcomeKind.RECOVERED,
                        recovered,
                        WorkflowState.IDLE,
                        failure=failure,
                        recovery=RecoveryOutcome(True, True, recovered),
                    ),
                    True,
                )
            return RuntimeTransitionResult(
                journal,
                TransitionOutcome(
                    TransitionOutcomeKind.FAILED,
                    recovered,
                    WorkflowState.ACTION_REQUIRED,
                    failure=TransitionFailure(
                        "journal.persist_failed",
                        "journal.persist_failed",
                        False,
                        True,
                    ),
                    recovery=RecoveryOutcome(True, True, recovered),
                ),
                False,
            )
        failed = (
            infer_placement(verified.snapshot)
            if verified is not None
            else (
                infer_placement(before.snapshot)
                if before is not None
                else PlacementState.UNKNOWN
            )
        )
        if durable:
            try:
                journal = self._append_save(
                    journal,
                    JournalEventKind.FAILED,
                    WorkflowState.ACTION_REQUIRED,
                    failed,
                    "recovery.failed",
                    (("reason_code", reason),),
                )
            except Exception:
                durable = False
        recovery_code = result.code if result is not None else "recovery.exception"
        return RuntimeTransitionResult(
            journal,
            TransitionOutcome(
                TransitionOutcomeKind.FAILED,
                failed,
                WorkflowState.ACTION_REQUIRED,
                failure=TransitionFailure(reason, reason, False, True),
                recovery=RecoveryOutcome(
                    True,
                    False,
                    failed,
                    TransitionFailure(recovery_code, recovery_code, False, True),
                ),
            ),
            durable,
        )

    def _verify_recovery(self, target, prior_generation, started, deadline_ms):
        while True:
            elapsed = self._clock.now_ms() - started
            if elapsed < 0 or elapsed > deadline_ms:
                return None
            observed = self._observe()
            if (
                observed is not None
                and observed.generation != prior_generation
                and infer_placement(observed.snapshot) is target
            ):
                return observed
            remaining = deadline_ms - (self._clock.now_ms() - started)
            if remaining <= 0:
                return None
            self._waiter.wait_ms(min(VERIFY_POLL_MS, remaining))

    def _observe(self):
        try:
            return self._observations.observe()
        except Exception:
            return None

    def _append_save(self, journal, kind, workflow, placement, code, details=()):
        updated = append_journal_entry(
            journal,
            kind=kind,
            occurred_at=self._occurred_at(),
            workflow_state=workflow,
            placement=placement,
            code=code,
            details=details,
        )
        self._journal_store.save(updated)
        return updated

    def _blocked(self, journal, placement, code):
        try:
            journal = self._append_save(
                journal,
                JournalEventKind.BLOCKED,
                WorkflowState.ACTION_REQUIRED,
                placement,
                "transition.blocked",
                (("blocker_code", code),),
            )
            durable = True
        except Exception:
            durable = False
        return RuntimeTransitionResult(
            journal,
            self._outcome(TransitionOutcomeKind.BLOCKED, placement, code),
            durable,
        )

    def _terminal(self, journal, placement, code):
        try:
            journal = self._append_save(
                journal,
                JournalEventKind.FAILED,
                WorkflowState.ACTION_REQUIRED,
                placement,
                "transition.failed",
                (("reason_code", code),),
            )
            durable = True
        except Exception:
            durable = False
        return RuntimeTransitionResult(
            journal,
            self._outcome(
                TransitionOutcomeKind.FAILED, placement, code, failed=True
            ),
            durable,
        )

    def _commit_no_op(self, journal, placement):
        try:
            journal = self._append_save(
                journal,
                JournalEventKind.COMMITTED,
                WorkflowState.IDLE,
                placement,
                "transition.no_op",
            )
        except Exception:
            return self._terminal(journal, placement, "journal.persist_failed")
        return RuntimeTransitionResult(
            journal,
            TransitionOutcome(
                TransitionOutcomeKind.NO_OP, placement, WorkflowState.IDLE
            ),
            True,
        )

    def _without_journal(self, placement, code, *, failed=False):
        return RuntimeTransitionResult(
            None,
            self._outcome(
                TransitionOutcomeKind.FAILED if failed else TransitionOutcomeKind.BLOCKED,
                placement,
                code,
                failed=failed,
            ),
            False,
        )

    @staticmethod
    def _outcome(kind, placement, code, *, failed=False):
        return TransitionOutcome(
            kind,
            placement,
            WorkflowState.ACTION_REQUIRED,
            failure=TransitionFailure(code, code, not failed, True),
        )
