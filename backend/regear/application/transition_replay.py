"""Deterministic transition runner for snapshot replay and failure injection.

No production adapter constructs this service.  It exists to prove ordering,
deadlines, observation verification, and recovery behavior before live mutation
is introduced.
"""

from __future__ import annotations

from dataclasses import dataclass

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
from ..ports.transition import (
    MonotonicClockPort,
    TransitionMechanismPort,
    TransitionObservationPort,
    VersionedObservation,
)


@dataclass(frozen=True, slots=True)
class ReplayResult:
    journal: TransitionJournal
    outcome: TransitionOutcome


class TransitionReplaySimulator:
    def __init__(
        self,
        observations: TransitionObservationPort,
        mechanism: TransitionMechanismPort,
        clock: MonotonicClockPort,
    ) -> None:
        self._observations = observations
        self._mechanism = mechanism
        self._clock = clock

    def run(self, plan: TransitionPlan) -> ReplayResult:
        journal = TransitionJournal(plan.plan_id, plan.request_id)
        journal = self._append(
            journal,
            JournalEventKind.REQUESTED,
            WorkflowState.IDLE,
            plan.from_placement,
            "request.accepted",
        )
        initial = self._observations.observe()
        if initial is None:
            return self._terminal_failure(
                journal, plan.from_placement, "observation.unavailable"
            )
        journal = self._append(
            journal,
            JournalEventKind.OBSERVED,
            plan.workflow_state,
            infer_placement(initial.snapshot),
            "snapshot.observed",
        )
        initial_placement = infer_placement(initial.snapshot)
        if initial.generation != plan.observed_generation:
            return self._blocked(journal, initial_placement, "observation.stale")
        if initial_placement in (PlacementState.UNKNOWN, PlacementState.DEGRADED):
            return self._blocked(journal, initial_placement, "placement.unknown")
        if initial_placement is not plan.from_placement:
            return self._blocked(journal, initial_placement, "placement.changed")

        journal = self._append(
            journal,
            JournalEventKind.VALIDATED,
            plan.workflow_state,
            initial_placement,
            "plan.validated",
        )
        journal = self._append(
            journal,
            JournalEventKind.PLANNED,
            plan.workflow_state,
            initial_placement,
            "plan.ready",
        )
        if initial_placement is plan.target_placement:
            journal = self._append(
                journal,
                JournalEventKind.COMMITTED,
                WorkflowState.IDLE,
                initial_placement,
                "transition.no_op",
            )
            return ReplayResult(
                journal,
                TransitionOutcome(
                    TransitionOutcomeKind.NO_OP,
                    initial_placement,
                    WorkflowState.IDLE,
                ),
            )
        if not plan.steps:
            return self._blocked(journal, initial_placement, "plan.empty")

        last_generation = initial.generation
        current_placement = initial_placement
        for step in plan.steps:
            journal = self._append(
                journal,
                JournalEventKind.STEP_STARTED,
                plan.workflow_state,
                current_placement,
                "step.started",
                (("step_code", step.code),),
            )
            started_at = self._clock.now_ms()
            result = self._mechanism.apply(step)
            elapsed = self._clock.now_ms() - started_at
            if elapsed < 0 or elapsed > step.deadline_ms:
                return self._recover(
                    journal,
                    plan,
                    current_placement,
                    "step.deadline_exceeded",
                    last_generation,
                )
            if not result.succeeded:
                return self._recover(
                    journal, plan, current_placement, result.code, last_generation
                )

            observed = self._observations.observe()
            if observed is None:
                return self._recover(
                    journal,
                    plan,
                    current_placement,
                    "observation.unavailable",
                    last_generation,
                )
            observed_placement = infer_placement(observed.snapshot)
            if observed.generation == last_generation:
                return self._recover(
                    journal,
                    plan,
                    observed_placement,
                    "observation.stale",
                    last_generation,
                )
            last_generation = observed.generation
            if observed_placement in (
                PlacementState.UNKNOWN,
                PlacementState.DEGRADED,
            ):
                return self._recover(
                    journal,
                    plan,
                    observed_placement,
                    "placement.unknown",
                    last_generation,
                )
            if (
                step.expected_placement is not None
                and observed_placement is not step.expected_placement
            ):
                return self._recover(
                    journal,
                    plan,
                    observed_placement,
                    "step.verification_failed",
                    last_generation,
                )
            current_placement = observed_placement
            journal = self._append(
                journal,
                JournalEventKind.STEP_VERIFIED,
                plan.workflow_state,
                current_placement,
                "step.verified",
                (("step_code", step.code),),
            )

        if current_placement is not plan.target_placement:
            return self._recover(
                journal,
                plan,
                current_placement,
                "target.verification_failed",
                last_generation,
            )
        journal = self._append(
            journal,
            JournalEventKind.COMMITTED,
            WorkflowState.IDLE,
            current_placement,
            "transition.committed",
        )
        return ReplayResult(
            journal,
            TransitionOutcome(
                TransitionOutcomeKind.SUCCEEDED,
                current_placement,
                WorkflowState.IDLE,
            ),
        )

    def _recover(
        self,
        journal: TransitionJournal,
        plan: TransitionPlan,
        placement: PlacementState,
        reason_code: str,
        previous_generation: str,
    ) -> ReplayResult:
        journal = self._append(
            journal,
            JournalEventKind.RECOVERY_STARTED,
            WorkflowState.RECOVERING,
            placement,
            "recovery.started",
            (("reason_code", reason_code),),
        )
        recovery_started_at = self._clock.now_ms()
        recovery_result = self._mechanism.recover(plan)
        recovery_elapsed = self._clock.now_ms() - recovery_started_at
        observed = self._observations.observe()
        if (
            recovery_result.succeeded
            and 0 <= recovery_elapsed <= plan.recovery_deadline_ms
            and observed is not None
            and observed.generation != previous_generation
        ):
            recovered_placement = infer_placement(observed.snapshot)
            if recovered_placement is plan.from_placement:
                journal = self._append(
                    journal,
                    JournalEventKind.RECOVERY_VERIFIED,
                    WorkflowState.IDLE,
                    recovered_placement,
                    "recovery.verified",
                    (("recovery_code", recovery_result.code),),
                )
                failure = TransitionFailure(reason_code, reason_code, True)
                return ReplayResult(
                    journal,
                    TransitionOutcome(
                        TransitionOutcomeKind.RECOVERED,
                        recovered_placement,
                        WorkflowState.IDLE,
                        failure=failure,
                        recovery=RecoveryOutcome(
                            True, True, recovered_placement
                        ),
                    ),
                )
        failed_placement = (
            infer_placement(observed.snapshot)
            if observed is not None
            else PlacementState.UNKNOWN
        )
        journal = self._append(
            journal,
            JournalEventKind.FAILED,
            WorkflowState.ACTION_REQUIRED,
            failed_placement,
            "recovery.failed",
            (("reason_code", reason_code),),
        )
        failure = TransitionFailure(reason_code, reason_code, False, True)
        return ReplayResult(
            journal,
            TransitionOutcome(
                TransitionOutcomeKind.FAILED,
                failed_placement,
                WorkflowState.ACTION_REQUIRED,
                failure=failure,
                recovery=RecoveryOutcome(
                    True,
                    False,
                    failed_placement,
                    TransitionFailure(
                        recovery_result.code,
                        recovery_result.code,
                        False,
                        True,
                    ),
                ),
            ),
        )

    def _blocked(
        self,
        journal: TransitionJournal,
        placement: PlacementState,
        reason_code: str,
    ) -> ReplayResult:
        journal = self._append(
            journal,
            JournalEventKind.BLOCKED,
            WorkflowState.ACTION_REQUIRED,
            placement,
            "transition.blocked",
            (("blocker_code", reason_code),),
        )
        failure = TransitionFailure(reason_code, reason_code, True, True)
        return ReplayResult(
            journal,
            TransitionOutcome(
                TransitionOutcomeKind.BLOCKED,
                placement,
                WorkflowState.ACTION_REQUIRED,
                failure=failure,
            ),
        )

    def _terminal_failure(
        self,
        journal: TransitionJournal,
        placement: PlacementState,
        reason_code: str,
    ) -> ReplayResult:
        journal = self._append(
            journal,
            JournalEventKind.FAILED,
            WorkflowState.ACTION_REQUIRED,
            placement,
            "transition.failed",
            (("reason_code", reason_code),),
        )
        failure = TransitionFailure(reason_code, reason_code, False, True)
        return ReplayResult(
            journal,
            TransitionOutcome(
                TransitionOutcomeKind.FAILED,
                placement,
                WorkflowState.ACTION_REQUIRED,
                failure=failure,
            ),
        )

    @staticmethod
    def _append(
        journal: TransitionJournal,
        kind: JournalEventKind,
        workflow: WorkflowState,
        placement: PlacementState,
        code: str,
        details: tuple[tuple[str, str], ...] = (),
    ) -> TransitionJournal:
        return append_journal_entry(
            journal,
            kind=kind,
            occurred_at="replay",
            workflow_state=workflow,
            placement=placement,
            code=code,
            details=details,
        )
