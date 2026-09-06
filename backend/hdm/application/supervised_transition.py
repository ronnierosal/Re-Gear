"""Supervised exact-plan facade for the dormant presentation orchestrator."""

from __future__ import annotations

import re
import secrets
import threading
from dataclasses import dataclass
from typing import Callable, Protocol

from ..domain.control_plane import (
    ExperimentalTransitionPermit,
    PlacementState,
    TransitionOutcome,
)
from ..domain.inference import infer_placement
from ..domain.manual_transition import evidence_from_snapshot, plan_manual_transition
from ..domain.transition_journal import JournalEventKind
from ..ports.transition import TransitionObservationPort
from ..ports.transition_journal import TransitionJournalPort
from ..profiles.registry import resolve_runtime_profiles
from .experimental_transition import ExperimentalTransitionApprovalStore
from .transition_orchestrator import RuntimeTransitionResult, TransitionOrchestrator
from .presentation_completion import PresentationCompletion, committed_target, reconcile_presentation_completion


IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.-]{8,64}$")


class RuntimeOrchestratorPort(Protocol):
    def run(self, plan) -> RuntimeTransitionResult: ...

    def recover_interrupted(
        self, *, recovery_deadline_ms: int = 15_000
    ) -> RuntimeTransitionResult: ...


@dataclass(frozen=True, slots=True)
class SupervisedTransitionPreview:
    target: PlacementState
    current: PlacementState
    approval_token: str = ""
    blockers: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return not self.blockers


@dataclass(frozen=True, slots=True)
class SupervisedTransitionExecution:
    accepted: bool
    code: str
    operation_id: str = ""
    outcome: TransitionOutcome | None = None
    durable: bool = False


@dataclass(frozen=True, slots=True)
class SupervisedTransitionStatus:
    """Durable, identity-minimized result for an interrupted Decky RPC.

    A Gamescope restart can replace the visible UI before the original execute
    RPC response is deliverable.  The transition journal, rather than that
    response, is authoritative.  This status deliberately exposes only a
    categorical state/code and the exact terminal acknowledgement identity.
    """

    code: str
    acknowledgement_required: bool = False
    action_required: bool = False
    operation_id: str = ""
    durable: bool = True
    target: PlacementState = PlacementState.UNKNOWN


class SupervisedPresentationTransitionService:
    def __init__(
        self,
        *,
        observations: TransitionObservationPort,
        orchestrator: TransitionOrchestrator | RuntimeOrchestratorPort,
        journal_store: TransitionJournalPort,
        integration_ready: Callable[[], bool],
        approvals: ExperimentalTransitionApprovalStore | None = None,
        identifier_factory: Callable[[], str] | None = None,
        portable_trial_runner: Callable | None = None,
    ) -> None:
        self._observations = observations
        self._orchestrator = orchestrator
        self._journal_store = journal_store
        self._portable_trial_runner = portable_trial_runner
        self._integration_ready = integration_ready
        self._approvals = approvals or ExperimentalTransitionApprovalStore()
        self._identifier_factory = identifier_factory or (
            lambda: secrets.token_urlsafe(18)
        )
        self._lock = threading.Lock()

    def preview(
        self,
        target: PlacementState,
        *,
        user_confirmed: bool,
        expected_generation: str = "",
        portable_vulkan_trial: bool = False,
    ) -> SupervisedTransitionPreview:
        if target not in {PlacementState.PORTABLE, PlacementState.DOCKED_EGPU}:
            return SupervisedTransitionPreview(
                target, PlacementState.UNKNOWN, blockers=("placement.target_unsupported",)
            )
        observed = self._observe()
        if observed is None:
            return SupervisedTransitionPreview(
                target, PlacementState.UNKNOWN, blockers=("observation.unavailable",)
            )
        if expected_generation and observed.generation != expected_generation:
            return SupervisedTransitionPreview(
                target,
                infer_placement(observed.snapshot),
                blockers=("transition.evidence_changed",),
            )
        current = infer_placement(observed.snapshot)
        if portable_vulkan_trial and (
            target is not PlacementState.PORTABLE
            or current is not PlacementState.DOCKED_EGPU
            or self._portable_trial_runner is None
        ):
            return SupervisedTransitionPreview(
                target, current, blockers=("portable_trial.requires_supervised_docked_source",)
            )
        resolved = resolve_runtime_profiles(observed.snapshot)
        evidence = evidence_from_snapshot(
            observed.snapshot,
            observed_generation=observed.generation,
            capabilities=resolved.capabilities,
        )
        plan_id = self._identifier()
        request_id = self._identifier()
        permit = self._preview_permit(
            plan_id=plan_id,
            target=target,
            generation=observed.generation,
            evidence=evidence,
            capabilities=resolved.capabilities,
        )
        decision = plan_manual_transition(
            plan_id=plan_id,
            request_id=request_id,
            current=current,
            target=target,
            capabilities=resolved.capabilities,
            evidence=evidence,
            experimental_permit=permit,
        )
        blockers = list(decision.blockers)
        if not self._ready():
            blockers.append("integration.not_ready")
        journal_blocker = self._journal_blocker()
        if journal_blocker:
            blockers.append(journal_blocker)
        if blockers:
            return SupervisedTransitionPreview(
                target, current, blockers=tuple(dict.fromkeys(blockers))
            )
        token = ""
        if user_confirmed:
            token = self._approvals.issue(
                plan_id=plan_id,
                observed_generation=observed.generation,
                target_placement=target,
                host_profile_id=resolved.capabilities.host_profile_id,
                egpu_profile_id=resolved.capabilities.egpu_profile_id,
                egpu_stable_id=evidence.egpu_stable_id,
                user_confirmed=True,
                portable_vulkan_trial=portable_vulkan_trial,
            )
        return SupervisedTransitionPreview(target, current, token)

    def execute(self, approval_token: str) -> SupervisedTransitionExecution:
        if not self._lock.acquire(blocking=False):
            return SupervisedTransitionExecution(False, "transition.concurrent_request")
        try:
            return self._execute_locked(approval_token)
        finally:
            self._lock.release()

    def execute_automatic(
        self,
        target: PlacementState,
        *,
        expected_generation: str,
        standing_consent: bool,
    ) -> SupervisedTransitionExecution:
        """Run the same exact plan for a persisted player opt-in.

        Standing consent is supplied only by the root-owned preference delivery
        boundary.  A caller still cannot bypass fresh evidence, the prepared
        integration, the journal, profile capabilities, or idle-game policy.
        """
        if not standing_consent:
            return SupervisedTransitionExecution(False, "automatic_dock.not_enabled")
        if not self._lock.acquire(blocking=False):
            return SupervisedTransitionExecution(False, "transition.concurrent_request")
        try:
            observed = self._observe()
            if observed is None:
                return SupervisedTransitionExecution(
                    False, "transition.observation_unavailable"
                )
            if not expected_generation or observed.generation != expected_generation:
                return SupervisedTransitionExecution(False, "transition.evidence_changed")
            if not self._ready():
                return SupervisedTransitionExecution(
                    False, "transition.integration_not_ready"
                )
            journal_blocker = self._journal_blocker()
            if journal_blocker:
                return SupervisedTransitionExecution(False, journal_blocker)
            resolved = resolve_runtime_profiles(observed.snapshot)
            evidence = evidence_from_snapshot(
                observed.snapshot,
                observed_generation=observed.generation,
                capabilities=resolved.capabilities,
            )
            plan_id = self._identifier()
            permit = self._preview_permit(
                plan_id=plan_id,
                target=target,
                generation=observed.generation,
                evidence=evidence,
                capabilities=resolved.capabilities,
            )
            decision = plan_manual_transition(
                plan_id=plan_id,
                request_id=self._identifier(),
                current=infer_placement(observed.snapshot),
                target=target,
                capabilities=resolved.capabilities,
                evidence=evidence,
                experimental_permit=permit,
            )
            if decision.plan is None:
                return SupervisedTransitionExecution(
                    False, "transition.preconditions_changed"
                )
            result = self._orchestrator.run(decision.plan)
            code = (
                result.outcome.failure.code
                if result.outcome.failure is not None
                else f"transition.{result.outcome.kind.value}"
            )
            return SupervisedTransitionExecution(
                True,
                code,
                decision.plan.plan_id,
                result.outcome,
                result.durable,
            )
        finally:
            self._lock.release()

    def _execute_locked(self, approval_token: str) -> SupervisedTransitionExecution:
        try:
            permit = self._approvals.consume(approval_token)
        except ValueError:
            return SupervisedTransitionExecution(False, "transition.approval_invalid")
        observed = self._observe()
        if observed is None:
            return SupervisedTransitionExecution(False, "transition.observation_unavailable")
        if observed.generation != permit.observed_generation:
            return SupervisedTransitionExecution(False, "transition.evidence_changed")
        if not self._ready():
            return SupervisedTransitionExecution(False, "transition.integration_not_ready")
        current = infer_placement(observed.snapshot)
        resolved = resolve_runtime_profiles(observed.snapshot)
        evidence = evidence_from_snapshot(
            observed.snapshot,
            observed_generation=observed.generation,
            capabilities=resolved.capabilities,
        )
        decision = plan_manual_transition(
            plan_id=permit.plan_id,
            request_id=f"request-{permit.plan_id}",
            current=current,
            target=permit.target_placement,
            capabilities=resolved.capabilities,
            evidence=evidence,
            experimental_permit=permit,
        )
        if decision.plan is None:
            return SupervisedTransitionExecution(False, "transition.preconditions_changed")
        if permit.portable_vulkan_trial:
            if self._portable_trial_runner is None or current is not PlacementState.DOCKED_EGPU:
                return SupervisedTransitionExecution(False, "portable_trial.unavailable")
            result = self._portable_trial_runner(decision.plan, self._orchestrator)
        else:
            result = self._orchestrator.run(decision.plan)
        code = (
            result.outcome.failure.code
            if result.outcome.failure is not None
            else f"transition.{result.outcome.kind.value}"
        )
        if permit.portable_vulkan_trial and result.outcome.failure is None:
            code = "portable_trial.application_unverified"
        return SupervisedTransitionExecution(
            True,
            code,
            decision.plan.plan_id,
            result.outcome,
            result.durable,
        )

    def acknowledge(self, operation_id: str) -> bool:
        if not IDENTIFIER_RE.fullmatch(operation_id):
            return False
        if not self._lock.acquire(blocking=False):
            return False
        try:
            current = self._journal_store.load_current()
            if (
                current is None
                or not current.terminal
                or current.operation_id != operation_id
                or not self._is_presentation_journal(current)
            ):
                return False
            if current.entries[-1].kind is JournalEventKind.COMMITTED:
                if committed_target(current) is PlacementState.UNKNOWN:
                    return False
                self._journal_store.retire_committed(operation_id)
            else:
                self._journal_store.clear_terminal(operation_id)
            return True
        except (OSError, ValueError):
            return False
        finally:
            self._lock.release()

    def reconcile_completion(self, current) -> PresentationCompletion:
        """Background success retirement shares the transition execution lock."""
        if not self._lock.acquire(blocking=False):
            return PresentationCompletion("completion.transition_busy")
        try:
            return reconcile_presentation_completion(self._journal_store, current)
        finally:
            self._lock.release()

    def status(self) -> SupervisedTransitionStatus:
        """Read the durable outcome after a restart without issuing a mutation.

        Incomplete journal state is deliberately not interpreted as success.
        A delivery owner may offer its separately gated recovery entry point,
        but must not issue another transition from this inspection method.
        """
        try:
            current = self._journal_store.load_current()
        except Exception:
            return SupervisedTransitionStatus(
                "transition.journal_unavailable",
                action_required=True,
                durable=False,
            )
        if current is None:
            return SupervisedTransitionStatus("transition.idle")
        if not self._is_presentation_journal(current):
            return SupervisedTransitionStatus(
                "transition.foreign_journal",
                action_required=True,
            )
        if not current.terminal:
            return SupervisedTransitionStatus(
                "transition.recovery_required",
                action_required=True,
                operation_id=current.operation_id,
            )
        terminal = current.entries[-1]
        trial_unverified = (
            dict(current.entries[0].details).get('launch_policy') == 'portable_vulkan_trial'
            and terminal.kind is JournalEventKind.COMMITTED
        )
        return SupervisedTransitionStatus(
            "portable_trial.application_unverified" if trial_unverified else terminal.code,
            acknowledgement_required=True,
            action_required=terminal.kind
            in (JournalEventKind.BLOCKED, JournalEventKind.FAILED),
            operation_id=current.operation_id,
            target=self._journal_target(current),
        )

    def recover_interrupted(self) -> RuntimeTransitionResult:
        return self._orchestrator.recover_interrupted()

    @staticmethod
    def _preview_permit(
        *,
        plan_id,
        target,
        generation,
        evidence,
        capabilities,
    ):
        if not all(
            (
                evidence.egpu_stable_id,
                capabilities.host_profile_id,
                capabilities.egpu_profile_id,
            )
        ):
            return None
        return ExperimentalTransitionPermit(
            "preview-permit",
            plan_id,
            generation,
            target,
            capabilities.host_profile_id,
            capabilities.egpu_profile_id,
            evidence.egpu_stable_id,
        )

    def _identifier(self) -> str:
        value = self._identifier_factory()
        if not IDENTIFIER_RE.fullmatch(value):
            raise ValueError("supervised transition identifier is invalid")
        return value

    def _ready(self) -> bool:
        try:
            return self._integration_ready() is True
        except Exception:
            return False

    def _journal_blocker(self) -> str:
        try:
            current = self._journal_store.load_current()
        except Exception:
            return "journal.unavailable"
        if current is None:
            return ""
        if not self._is_presentation_journal(current):
            return "journal.foreign_workflow"
        return (
            "journal.acknowledgement_required"
            if current.terminal
            else "journal.recovery_required"
        )

    @staticmethod
    def _is_presentation_journal(journal) -> bool:
        """Refuse to surface or clear a different workflow's journal.

        The common journal store is also used by sleep and process-release
        workflows.  Their operation must remain Action Required here instead
        of being mislabeled as a display result after a UI restart.
        """
        return bool(
            journal.entries
            and journal.entries[0].code == "request.accepted"
            and dict(journal.entries[0].details).get("capability")
            in (None, "presentation_transition")
        )

    @staticmethod
    def _journal_target(journal) -> PlacementState:
        """Recover only the categorical target persisted with the request."""
        if not journal.entries:
            return PlacementState.UNKNOWN
        value = dict(journal.entries[0].details).get("target_placement", "")
        try:
            return PlacementState(value)
        except ValueError:
            return PlacementState.UNKNOWN

    def _observe(self):
        try:
            return self._observations.observe()
        except Exception:
            return None
