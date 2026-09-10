from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.unexpected_undock import (  # noqa: E402
    LossOrigin,
    RecoveryStage,
    UnexpectedUndockRecoveryCoordinator,
    UnexpectedUndockRequest,
)
from regear.domain.control_plane import (  # noqa: E402
    PlacementState,
    TransitionOutcomeKind,
    WorkflowState,
)
from regear.domain.event_policy import TopologyEvent  # noqa: E402
from regear.domain.models import Blocker, GameState, GpuRole  # noqa: E402
from regear.domain.serialization import snapshot_from_dict  # noqa: E402
from regear.ports.transition import MechanismResult, VersionedObservation  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures"
EGPU_ID = "gpd-g1:0123456789abcdef"


def snapshot(name: str):
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    old_external_ids = {
        gpu["stable_id"] for gpu in value["gpus"] if gpu["role"] == "external"
    }
    for gpu in value["gpus"]:
        if gpu["role"] == "external":
            gpu["stable_id"] = EGPU_ID
    if value["gamescope"].get("render_gpu_stable_id") in old_external_ids:
        value["gamescope"]["render_gpu_stable_id"] = EGPU_ID
    return snapshot_from_dict(value)


def loss_snapshot(event: TopologyEvent):
    docked = snapshot("tv-docked.json")
    if event is TopologyEvent.EGPU_REMOVED:
        gpus = tuple(
            replace(gpu, present=False, selected_for_render=False)
            if gpu.role is GpuRole.EXTERNAL
            else gpu
            for gpu in docked.gpus
        )
        displays = tuple(
            replace(display, connected=False, active=False)
            if display.stable_id == "external-tv"
            else display
            for display in docked.displays
        )
        return replace(docked, gpus=gpus, displays=displays)
    displays = tuple(
        replace(display, connected=False, active=False)
        if display.stable_id == "external-tv"
        else display
        for display in docked.displays
    )
    return replace(docked, displays=displays)


def portable_with_egpu():
    portable = snapshot("portable.json")
    docked = snapshot("tv-docked.json")
    external = next(gpu for gpu in docked.gpus if gpu.role is GpuRole.EXTERNAL)
    return replace(
        portable,
        gpus=(*portable.gpus, replace(external, selected_for_render=False)),
        disconnect_readiness=docked.disconnect_readiness,
    )


def observation(generation: str, sample_id: str, value):
    return VersionedObservation(generation, value, sample_id)


class FakeClockWaiter:
    def __init__(self):
        self.value = 0
        self.waits: list[int] = []

    def now_ms(self):
        return self.value

    def wait_ms(self, milliseconds):
        self.waits.append(milliseconds)
        self.value += milliseconds


class ScriptedObservations:
    def __init__(self, *values):
        self.values = list(values)
        self.calls = 0

    def observe(self):
        self.calls += 1
        if not self.values:
            return None
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class FakeMechanism:
    def __init__(self, *, restore=None, fallback=None):
        self.restore_result = restore or MechanismResult(
            True, "recovery.portable_restore_started"
        )
        self.fallback_result = fallback or MechanismResult(
            True, "recovery.usable_state_preserved"
        )
        self.restores = []
        self.fallbacks = []

    def restore_portable(self, binding, value, deadline_ms):
        self.restores.append((binding, value, deadline_ms))
        if isinstance(self.restore_result, Exception):
            raise self.restore_result
        return self.restore_result

    def preserve_portable_path(self, binding, value, deadline_ms):
        self.fallbacks.append((binding, value, deadline_ms))
        if isinstance(self.fallback_result, Exception):
            raise self.fallback_result
        return self.fallback_result


def request(
    *,
    event=TopologyEvent.EGPU_REMOVED,
    workflow=WorkflowState.IDLE,
    generation="generation-1",
    sample_id="sample-1",
):
    return UnexpectedUndockRequest(
        request_id="unexpected-undock-1",
        event=event,
        workflow=workflow,
        trigger_generation=generation,
        trigger_sample_id=sample_id,
        canonical_sleep_operation_id=(
            "sleep-operation-1"
            if workflow is WorkflowState.SLEEP_PENDING_DISCONNECT
            else ""
        ),
        verification_deadline_ms=300,
        fallback_deadline_ms=300,
    )


def coordinator(observations, mechanism, clock=None):
    clock = clock or FakeClockWaiter()
    return (
        UnexpectedUndockRecoveryCoordinator(
            observations=observations,
            mechanism=mechanism,
            clock=clock,
            waiter=clock,
        ),
        clock,
    )


class UnexpectedUndockRecoveryTests(unittest.TestCase):
    def test_unsolicited_loss_restores_verifies_and_commits_portable(self):
        observations = ScriptedObservations(
            observation("generation-1", "sample-1", snapshot("tv-docked.json")),
            observation(
                "generation-2",
                "sample-2",
                loss_snapshot(TopologyEvent.EGPU_REMOVED),
            ),
            observation("generation-3", "sample-3", snapshot("portable.json")),
        )
        mechanism = FakeMechanism()
        service, _clock = coordinator(observations, mechanism)

        result = service.run(request())

        self.assertEqual(result.kind, TransitionOutcomeKind.SUCCEEDED)
        self.assertEqual(result.origin, LossOrigin.UNSOLICITED)
        self.assertEqual(result.placement, PlacementState.PORTABLE)
        self.assertEqual(result.workflow_state, WorkflowState.IDLE)
        self.assertFalse(result.authorizes_sleep)
        self.assertFalse(result.canonical_sleep_recheck_required)
        self.assertEqual(len(mechanism.restores), 1)
        self.assertEqual(mechanism.fallbacks, [])
        self.assertEqual(
            [event.stage for event in result.trace],
            [
                RecoveryStage.DETECTED,
                RecoveryStage.VALIDATED,
                RecoveryStage.ATTEMPTED,
                RecoveryStage.VERIFIED,
                RecoveryStage.COMMITTED,
            ],
        )
        exported_trace = json.dumps(
            [
                {
                    "sequence": event.sequence,
                    "stage": event.stage,
                    "code": event.code,
                    "placement": event.placement,
                }
                for event in result.trace
            ],
            sort_keys=True,
        )
        self.assertNotIn(EGPU_ID, exported_trace)
        self.assertNotIn("internal-panel", exported_trace)

    def test_sleep_pending_loss_preserves_transaction_for_canonical_recheck(self):
        observations = ScriptedObservations(
            observation("generation-1", "sample-1", snapshot("tv-docked.json")),
            observation(
                "generation-2",
                "sample-2",
                loss_snapshot(TopologyEvent.EGPU_REMOVED),
            ),
            observation("generation-3", "sample-3", snapshot("portable.json")),
        )
        mechanism = FakeMechanism()
        service, _clock = coordinator(observations, mechanism)

        result = service.run(
            request(workflow=WorkflowState.SLEEP_PENDING_DISCONNECT)
        )

        self.assertEqual(result.kind, TransitionOutcomeKind.SUCCEEDED)
        self.assertEqual(result.origin, LossOrigin.CANONICAL_SLEEP_PENDING)
        self.assertEqual(
            result.workflow_state, WorkflowState.SLEEP_PENDING_DISCONNECT
        )
        self.assertTrue(result.canonical_sleep_recheck_required)
        self.assertFalse(result.authorizes_sleep)

    def test_sleep_pending_requires_exact_transaction_identity(self):
        observations = ScriptedObservations()
        mechanism = FakeMechanism()
        service, _clock = coordinator(observations, mechanism)
        invalid = replace(
            request(workflow=WorkflowState.SLEEP_PENDING_DISCONNECT),
            canonical_sleep_operation_id="",
        )

        result = service.run(invalid)

        self.assertEqual(result.kind, TransitionOutcomeKind.BLOCKED)
        self.assertEqual(result.reason_code, "sleep.transaction_identity_missing")
        self.assertEqual(observations.calls, 0)
        self.assertEqual(mechanism.restores, [])

    def test_stale_trigger_and_uncorrelated_loss_fail_before_mutation(self):
        stale = ScriptedObservations(
            observation("other-generation", "other-sample", snapshot("tv-docked.json"))
        )
        mechanism = FakeMechanism()
        service, _clock = coordinator(stale, mechanism)
        stale_result = service.run(request())
        self.assertEqual(stale_result.reason_code, "observation.stale_trigger")

        uncorrelated = ScriptedObservations(
            observation("generation-1", "sample-1", snapshot("tv-docked.json")),
            observation("generation-1", "sample-2", snapshot("tv-docked.json")),
        )
        service, _clock = coordinator(uncorrelated, mechanism)
        uncorrelated_result = service.run(request())
        self.assertEqual(
            uncorrelated_result.reason_code, "observation.loss_not_correlated"
        )
        self.assertEqual(mechanism.restores, [])

    def test_unknown_loss_or_game_evidence_fails_closed(self):
        unknown_loss = replace(
            loss_snapshot(TopologyEvent.EGPU_REMOVED),
            blockers=(Blocker("drm_inventory_unavailable", "unavailable"),),
        )
        observations = ScriptedObservations(
            observation("generation-1", "sample-1", snapshot("tv-docked.json")),
            observation("generation-2", "sample-2", unknown_loss),
        )
        mechanism = FakeMechanism()
        service, _clock = coordinator(observations, mechanism)
        result = service.run(request())
        self.assertEqual(result.reason_code, "recovery.loss_unverified")

        unknown_game = replace(
            loss_snapshot(TopologyEvent.EGPU_REMOVED), game_state=GameState.UNKNOWN
        )
        observations = ScriptedObservations(
            observation("generation-1", "sample-1", snapshot("tv-docked.json")),
            observation("generation-2", "sample-2", unknown_game),
        )
        service, _clock = coordinator(observations, mechanism)
        result = service.run(request())
        self.assertEqual(result.reason_code, "game.state_unknown")
        self.assertEqual(mechanism.restores, [])

    def test_failed_primary_attempt_uses_bounded_fallback(self):
        observations = ScriptedObservations(
            observation("generation-1", "sample-1", snapshot("tv-docked.json")),
            observation(
                "generation-2",
                "sample-2",
                loss_snapshot(TopologyEvent.EGPU_REMOVED),
            ),
            observation("generation-3", "sample-3", snapshot("portable.json")),
        )
        mechanism = FakeMechanism(
            restore=MechanismResult(False, "recovery.primary_refused")
        )
        service, _clock = coordinator(observations, mechanism)

        result = service.run(request())

        self.assertEqual(result.kind, TransitionOutcomeKind.RECOVERED)
        self.assertTrue(result.usable_path_preserved)
        self.assertEqual(result.placement, PlacementState.PORTABLE)
        self.assertEqual(len(mechanism.fallbacks), 1)
        self.assertEqual(mechanism.restores[0][2], 300)
        self.assertEqual(mechanism.fallbacks[0][2], 300)
        self.assertIn(RecoveryStage.FALLBACK_VERIFIED, [e.stage for e in result.trace])
        self.assertFalse(result.authorizes_sleep)

    def test_verification_and_fallback_failures_are_time_bounded(self):
        observations = ScriptedObservations(
            observation("generation-1", "sample-1", snapshot("tv-docked.json")),
            observation(
                "generation-2",
                "sample-2",
                loss_snapshot(TopologyEvent.EGPU_REMOVED),
            ),
        )
        mechanism = FakeMechanism(
            fallback=MechanismResult(False, "recovery.fallback_refused")
        )
        clock = FakeClockWaiter()
        service, _clock = coordinator(observations, mechanism, clock)

        result = service.run(request())

        self.assertEqual(result.kind, TransitionOutcomeKind.FAILED)
        self.assertEqual(result.workflow_state, WorkflowState.ACTION_REQUIRED)
        self.assertEqual(sum(clock.waits), 300)
        self.assertEqual(len(mechanism.fallbacks), 1)
        self.assertEqual(result.trace[-1].stage, RecoveryStage.FAILED)

    def test_external_display_loss_uses_same_guarded_path(self):
        observations = ScriptedObservations(
            observation("generation-1", "sample-1", snapshot("tv-docked.json")),
            observation(
                "generation-2",
                "sample-2",
                loss_snapshot(TopologyEvent.EXTERNAL_DISPLAY_LOST),
            ),
            observation("generation-3", "sample-3", portable_with_egpu()),
        )
        mechanism = FakeMechanism()
        service, _clock = coordinator(observations, mechanism)

        result = service.run(request(event=TopologyEvent.EXTERNAL_DISPLAY_LOST))

        self.assertEqual(result.kind, TransitionOutcomeKind.SUCCEEDED)
        self.assertEqual(
            mechanism.restores[0][0].event, TopologyEvent.EXTERNAL_DISPLAY_LOST
        )

    def test_display_loss_rejects_changed_egpu_identity(self):
        changed = loss_snapshot(TopologyEvent.EXTERNAL_DISPLAY_LOST)
        changed_id = "gpd-g1:fedcba9876543210"
        changed = replace(
            changed,
            gpus=tuple(
                replace(gpu, stable_id=changed_id)
                if gpu.role is GpuRole.EXTERNAL
                else gpu
                for gpu in changed.gpus
            ),
            gamescope=replace(
                changed.gamescope, render_gpu_stable_id=changed_id
            ),
        )
        observations = ScriptedObservations(
            observation("generation-1", "sample-1", snapshot("tv-docked.json")),
            observation("generation-2", "sample-2", changed),
        )
        mechanism = FakeMechanism()
        service, _clock = coordinator(observations, mechanism)

        result = service.run(request(event=TopologyEvent.EXTERNAL_DISPLAY_LOST))

        self.assertEqual(result.reason_code, "identity.egpu_changed")
        self.assertEqual(mechanism.restores, [])

    def test_duplicate_portable_removal_is_verified_no_op(self):
        portable = snapshot("portable.json")
        observations = ScriptedObservations(
            observation("generation-1", "sample-1", portable),
            observation("generation-1", "sample-2", portable),
        )
        mechanism = FakeMechanism()
        service, _clock = coordinator(observations, mechanism)

        result = service.run(request())

        self.assertEqual(result.kind, TransitionOutcomeKind.NO_OP)
        self.assertEqual(result.placement, PlacementState.PORTABLE)
        self.assertEqual(mechanism.restores, [])
        self.assertEqual(mechanism.fallbacks, [])

    def test_unknown_trigger_placement_and_non_loss_events_do_not_mutate(self):
        observations = ScriptedObservations(
            observation("generation-1", "sample-1", snapshot("gamescope-down.json"))
        )
        mechanism = FakeMechanism()
        service, _clock = coordinator(observations, mechanism)
        result = service.run(request())
        self.assertEqual(result.kind, TransitionOutcomeKind.BLOCKED)
        self.assertEqual(result.reason_code, "egpu.removed_placement_unverified")

        observations = ScriptedObservations()
        service, _clock = coordinator(observations, mechanism)
        result = service.run(request(event=TopologyEvent.EGPU_ATTACHED))
        self.assertEqual(result.reason_code, "event.not_recovery_loss")
        self.assertEqual(mechanism.restores, [])


if __name__ == "__main__":
    unittest.main()
