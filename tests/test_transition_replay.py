from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.transition_replay import TransitionReplaySimulator  # noqa: E402
from regear.domain.control_plane import (  # noqa: E402
    PlacementState,
    PlannedStep,
    TransitionBinding,
    TransitionOutcomeKind,
    TransitionPlan,
    TransitionStepCode,
    WorkflowState,
)
from regear.domain.serialization import snapshot_from_dict  # noqa: E402
from regear.domain.transition_journal import JournalEventKind  # noqa: E402
from regear.ports.transition import MechanismResult, VersionedObservation  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures"


def snapshot(name: str):
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return snapshot_from_dict(value)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0

    def now_ms(self) -> int:
        return self.value

    def advance(self, milliseconds: int) -> None:
        self.value += milliseconds


class ScriptedObservations:
    def __init__(self, *values: VersionedObservation | None) -> None:
        self.values = list(values)

    def observe(self) -> VersionedObservation | None:
        return self.values.pop(0) if self.values else None


class ScriptedMechanism:
    def __init__(
        self,
        clock: FakeClock,
        apply_results: list[tuple[int, MechanismResult]],
        recovery_result: tuple[int, MechanismResult] = (
            1,
            MechanismResult(True, "recovery.internal_restored"),
        ),
    ) -> None:
        self.clock = clock
        self.apply_results = apply_results
        self.recovery_result = recovery_result
        self.applied: list[str] = []
        self.recoveries = 0

    def apply(self, step: PlannedStep) -> MechanismResult:
        self.applied.append(step.code)
        duration, result = self.apply_results.pop(0)
        self.clock.advance(duration)
        return result

    def recover(self, plan: TransitionPlan) -> MechanismResult:
        self.recoveries += 1
        duration, result = self.recovery_result
        self.clock.advance(duration)
        return result


def dock_plan(*steps: PlannedStep) -> TransitionPlan:
    return TransitionPlan(
        plan_id="operation-1",
        request_id="request-1",
        observed_generation="generation-1",
        from_placement=PlacementState.PORTABLE,
        target_placement=PlacementState.DOCKED_EGPU,
        workflow_state=WorkflowState.CONNECTING,
        steps=steps,
        binding=TransitionBinding(
            "host", "egpu", "egpu-1", "internal-gpu", "egpu-1", "panel", "tv"
        ),
    )


class TransitionReplayTests(unittest.TestCase):
    def run_replay(self, observations, mechanism, plan):
        return TransitionReplaySimulator(
            observations, mechanism, mechanism.clock
        ).run(plan)

    def test_verified_transition_commits_after_fresh_snapshot(self):
        clock = FakeClock()
        observations = ScriptedObservations(
            VersionedObservation("generation-1", snapshot("portable.json")),
            VersionedObservation("generation-2", snapshot("tv-docked.json")),
        )
        mechanism = ScriptedMechanism(
            clock, [(20, MechanismResult(True, "display.applied"))]
        )
        result = self.run_replay(
            observations,
            mechanism,
            dock_plan(
                PlannedStep(
                    TransitionStepCode.PRESENTATION_APPLY_DOCKED_EGPU,
                    100,
                    expected_placement=PlacementState.DOCKED_EGPU,
                )
            ),
        )
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.SUCCEEDED)
        self.assertEqual(result.outcome.placement, PlacementState.DOCKED_EGPU)
        self.assertEqual(result.journal.entries[-1].kind, JournalEventKind.COMMITTED)
        self.assertEqual(mechanism.recoveries, 0)

    def test_stale_initial_generation_blocks_without_mechanism(self):
        clock = FakeClock()
        observations = ScriptedObservations(
            VersionedObservation("old-generation", snapshot("portable.json"))
        )
        mechanism = ScriptedMechanism(clock, [])
        result = self.run_replay(
            observations,
            mechanism,
            dock_plan(
                PlannedStep(
                    TransitionStepCode.PRESENTATION_APPLY_DOCKED_EGPU,
                    100,
                    expected_placement=PlacementState.DOCKED_EGPU,
                )
            ),
        )
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.BLOCKED)
        self.assertEqual(mechanism.applied, [])

    def test_partial_state_after_apply_recovers_to_portable(self):
        clock = FakeClock()
        observations = ScriptedObservations(
            VersionedObservation("generation-1", snapshot("portable.json")),
            VersionedObservation("generation-2", snapshot("ambiguous.json")),
            VersionedObservation("generation-3", snapshot("portable.json")),
        )
        mechanism = ScriptedMechanism(
            clock, [(20, MechanismResult(True, "display.applied"))]
        )
        result = self.run_replay(
            observations,
            mechanism,
            dock_plan(
                PlannedStep(
                    TransitionStepCode.PRESENTATION_APPLY_DOCKED_EGPU,
                    100,
                    expected_placement=PlacementState.DOCKED_EGPU,
                )
            ),
        )
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.RECOVERED)
        self.assertEqual(result.outcome.placement, PlacementState.PORTABLE)
        self.assertEqual(
            result.journal.entries[-1].kind, JournalEventKind.RECOVERY_VERIFIED
        )

    def test_deadline_expiry_recovers_without_claiming_step_success(self):
        clock = FakeClock()
        observations = ScriptedObservations(
            VersionedObservation("generation-1", snapshot("portable.json")),
            VersionedObservation("generation-2", snapshot("portable.json")),
        )
        mechanism = ScriptedMechanism(
            clock, [(101, MechanismResult(True, "display.applied"))]
        )
        result = self.run_replay(
            observations,
            mechanism,
            dock_plan(
                PlannedStep(
                    TransitionStepCode.PRESENTATION_APPLY_DOCKED_EGPU,
                    100,
                    expected_placement=PlacementState.DOCKED_EGPU,
                )
            ),
        )
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.RECOVERED)
        self.assertNotIn(
            JournalEventKind.STEP_VERIFIED,
            [entry.kind for entry in result.journal.entries],
        )

    def test_failed_recovery_requires_action(self):
        clock = FakeClock()
        observations = ScriptedObservations(
            VersionedObservation("generation-1", snapshot("portable.json")),
            VersionedObservation("generation-2", snapshot("ambiguous.json")),
        )
        mechanism = ScriptedMechanism(
            clock,
            [(10, MechanismResult(False, "display.apply_failed"))],
            (10, MechanismResult(False, "recovery.apply_failed")),
        )
        result = self.run_replay(
            observations,
            mechanism,
            dock_plan(
                PlannedStep(
                    TransitionStepCode.PRESENTATION_APPLY_DOCKED_EGPU,
                    100,
                    expected_placement=PlacementState.DOCKED_EGPU,
                )
            ),
        )
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.FAILED)
        self.assertEqual(result.outcome.workflow_state, WorkflowState.ACTION_REQUIRED)
        self.assertFalse(result.outcome.recovery.verified)

    def test_stale_recovery_observation_requires_action(self):
        clock = FakeClock()
        observations = ScriptedObservations(
            VersionedObservation("generation-1", snapshot("portable.json")),
            VersionedObservation("generation-1", snapshot("portable.json")),
        )
        mechanism = ScriptedMechanism(
            clock, [(101, MechanismResult(True, "display.applied"))]
        )
        result = self.run_replay(
            observations,
            mechanism,
            dock_plan(
                PlannedStep(
                    TransitionStepCode.PRESENTATION_APPLY_DOCKED_EGPU,
                    100,
                    expected_placement=PlacementState.DOCKED_EGPU,
                )
            ),
        )
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.FAILED)
        self.assertEqual(result.outcome.workflow_state, WorkflowState.ACTION_REQUIRED)

    def test_recovery_deadline_is_bounded(self):
        clock = FakeClock()
        observations = ScriptedObservations(
            VersionedObservation("generation-1", snapshot("portable.json")),
            VersionedObservation("generation-2", snapshot("portable.json")),
        )
        mechanism = ScriptedMechanism(
            clock,
            [(101, MechanismResult(True, "display.applied"))],
            (51, MechanismResult(True, "recovery.internal_restored")),
        )
        plan = dock_plan(
            PlannedStep(
                TransitionStepCode.PRESENTATION_APPLY_DOCKED_EGPU,
                100,
                expected_placement=PlacementState.DOCKED_EGPU,
            )
        )
        plan = TransitionPlan(
            plan_id=plan.plan_id,
            request_id=plan.request_id,
            observed_generation=plan.observed_generation,
            from_placement=plan.from_placement,
            target_placement=plan.target_placement,
            workflow_state=plan.workflow_state,
            steps=plan.steps,
            recovery_deadline_ms=50,
            binding=plan.binding,
        )
        result = self.run_replay(observations, mechanism, plan)
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.FAILED)

    def test_no_op_does_not_call_mechanism(self):
        clock = FakeClock()
        observations = ScriptedObservations(
            VersionedObservation("generation-1", snapshot("portable.json"))
        )
        mechanism = ScriptedMechanism(clock, [])
        plan = TransitionPlan(
            plan_id="operation-1",
            request_id="request-1",
            observed_generation="generation-1",
            from_placement=PlacementState.PORTABLE,
            target_placement=PlacementState.PORTABLE,
            workflow_state=WorkflowState.RETURNING_TO_PORTABLE,
        )
        result = self.run_replay(observations, mechanism, plan)
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.NO_OP)
        self.assertEqual(mechanism.applied, [])


if __name__ == "__main__":
    unittest.main()
