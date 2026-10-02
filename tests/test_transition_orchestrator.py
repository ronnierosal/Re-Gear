from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.transition_orchestrator import (  # noqa: E402
    TransitionOrchestrator,
)
from regear.adapters.transition_runtime import versioned_snapshot_observation  # noqa: E402
from regear.domain.control_plane import (  # noqa: E402
    ExperimentalTransitionPermit,
    PlacementState,
    TransitionOutcomeKind,
)
from regear.domain.manual_transition import (  # noqa: E402
    evidence_from_snapshot,
    plan_manual_transition,
)
from regear.domain.serialization import snapshot_from_dict  # noqa: E402
from regear.domain.transition_journal import (  # noqa: E402
    JournalEventKind,
    TransitionJournal,
    append_journal_entry,
)
from regear.ports.transition import MechanismResult, VersionedObservation  # noqa: E402
from regear.profiles.registry import resolve_runtime_profiles  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures"


def snapshot(name: str, *, game_state: str | None = None, egpu_id: str | None = None):
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    if game_state is not None:
        value["game_state"] = game_state
    exact_id = egpu_id or "gpd-g1:0123456789abcdef"
    old_external_ids = {
        gpu["stable_id"] for gpu in value["gpus"] if gpu["role"] == "external"
    }
    for gpu in value["gpus"]:
        if gpu["role"] == "external":
            gpu["stable_id"] = exact_id
    if value["gamescope"].get("render_gpu_stable_id") in old_external_ids:
        value["gamescope"]["render_gpu_stable_id"] = exact_id
    return snapshot_from_dict(value)


def docked_igpu_snapshot():
    value = json.loads((FIXTURES / "tv-docked.json").read_text(encoding="utf-8"))
    for gpu in value["gpus"]:
        gpu["selected_for_render"] = gpu["role"] == "internal"
        if gpu["role"] == "external":
            gpu["stable_id"] = "gpd-g1:0123456789abcdef"
    value["gamescope"]["render_gpu_stable_id"] = "internal-gpu"
    value["gamescope"]["render_vendor_device"] = "1002:0000"
    return snapshot_from_dict(value)


def experimental_plan(
    initial,
    generation="generation-1",
    *,
    current=PlacementState.PORTABLE,
):
    resolved = resolve_runtime_profiles(initial)
    evidence = evidence_from_snapshot(
        initial,
        observed_generation=generation,
        capabilities=resolved.capabilities,
    )
    permit = ExperimentalTransitionPermit(
        permit_id="experimental-token-1",
        plan_id="operation-1",
        observed_generation=generation,
        target_placement=PlacementState.DOCKED_EGPU,
        host_profile_id=resolved.capabilities.host_profile_id,
        egpu_profile_id=resolved.capabilities.egpu_profile_id,
        egpu_stable_id=resolved.egpu_stable_id,
    )
    decision = plan_manual_transition(
        plan_id="operation-1",
        request_id="request-1",
        current=current,
        target=PlacementState.DOCKED_EGPU,
        capabilities=resolved.capabilities,
        evidence=evidence,
        experimental_permit=permit,
        step_deadline_ms=300,
        recovery_deadline_ms=300,
    )
    if decision.plan is None:
        raise AssertionError(decision.blockers)
    return decision.plan


class FakeClockWaiter:
    def __init__(self):
        self.value = 0
        self.waits = []

    def now_ms(self):
        return self.value

    def wait_ms(self, milliseconds):
        self.waits.append(milliseconds)
        self.value += milliseconds


class ScriptedObservations:
    def __init__(self, *values):
        self.values = list(values)

    def observe(self):
        return self.values.pop(0) if self.values else None


class MemoryJournalStore:
    def __init__(self, current=None, fail_kind=None):
        self.current = current
        self.fail_kind = fail_kind
        self.saved = []

    def load_current(self):
        return self.current

    def save(self, journal):
        if journal.entries[-1].kind is self.fail_kind:
            raise OSError("injected journal failure")
        self.current = journal
        self.saved.append(journal)

    def clear_terminal(self, operation_id):
        if self.current and self.current.operation_id == operation_id:
            self.current = None


class FakeMechanism:
    def __init__(self, clock, *, apply=None, recover=None):
        self.clock = clock
        self.apply_result = apply or MechanismResult(True, "presentation.applied")
        self.recover_result = recover or MechanismResult(
            True, "recovery.portable_restored"
        )
        self.applied = []
        self.recoveries = []

    def apply(self, step, binding, observation):
        self.applied.append((step.code, binding.egpu_stable_id, observation.game_state))
        self.clock.value += 10
        if isinstance(self.apply_result, Exception):
            raise self.apply_result
        return self.apply_result

    def recover(self, source, binding, observation):
        self.recoveries.append((source, binding, observation))
        self.clock.value += 10
        return self.recover_result


def observation(generation, value):
    return VersionedObservation(generation, value)


def orchestrator(observations, mechanism, store, clock):
    return TransitionOrchestrator(
        observations=observations,
        mechanism=mechanism,
        journal_store=store,
        clock=clock,
        waiter=clock,
        occurred_at=lambda: "2026-08-31T12:00:00Z",
    )


class TransitionOrchestratorTests(unittest.TestCase):
    def test_verified_no_op_commits_without_binding_or_mechanism(self):
        portable = snapshot("connected-internal.json")
        resolved = resolve_runtime_profiles(portable)
        evidence = evidence_from_snapshot(
            portable,
            observed_generation="generation-1",
            capabilities=resolved.capabilities,
        )
        decision = plan_manual_transition(
            plan_id="operation-1",
            request_id="request-1",
            current=PlacementState.PORTABLE,
            target=PlacementState.PORTABLE,
            capabilities=resolved.capabilities,
            evidence=evidence,
        )
        clock = FakeClockWaiter()
        mechanism = FakeMechanism(clock)
        result = orchestrator(
            ScriptedObservations(observation("generation-1", portable)),
            mechanism,
            MemoryJournalStore(),
            clock,
        ).run(decision.plan)
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.NO_OP)
        self.assertEqual(mechanism.applied, [])
        self.assertEqual(mechanism.recoveries, [])

    def test_success_persists_step_before_apply_and_commits_after_verification(self):
        portable = snapshot("connected-internal.json")
        docked = snapshot("tv-docked.json")
        plan = experimental_plan(portable)
        clock = FakeClockWaiter()
        store = MemoryJournalStore()
        mechanism = FakeMechanism(clock)
        service = orchestrator(
            ScriptedObservations(
                observation("generation-1", portable),
                observation("generation-1b", portable),
                observation("generation-2", docked),
            ),
            mechanism,
            store,
            clock,
        )
        result = service.run(plan)
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.SUCCEEDED)
        self.assertTrue(result.durable)
        kinds = [item.entries[-1].kind for item in store.saved]
        self.assertLess(kinds.index(JournalEventKind.STEP_STARTED), len(kinds) - 1)
        self.assertEqual(kinds[-1], JournalEventKind.COMMITTED)
        self.assertEqual(len(mechanism.applied), 1)

    def test_docked_igpu_promotes_through_same_journaled_orchestrator(self):
        source = docked_igpu_snapshot()
        docked = snapshot("tv-docked.json")
        plan = experimental_plan(
            source, current=PlacementState.DOCKED_IGPU
        )
        clock = FakeClockWaiter()
        store = MemoryJournalStore()
        mechanism = FakeMechanism(clock)

        result = orchestrator(
            ScriptedObservations(
                observation("generation-1", source),
                observation("generation-1b", source),
                observation("generation-2", docked),
            ),
            mechanism,
            store,
            clock,
        ).run(plan)

        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.SUCCEEDED)
        self.assertEqual(result.outcome.placement, PlacementState.DOCKED_EGPU)
        self.assertEqual(
            result.journal.entries[0].placement, PlacementState.DOCKED_IGPU
        )
        self.assertEqual(result.journal.entries[-1].kind, JournalEventKind.COMMITTED)

    def test_game_or_identity_change_before_step_blocks_without_mutation(self):
        portable = snapshot("connected-internal.json")
        plan = experimental_plan(portable)
        cases = (
            snapshot("connected-internal.json", game_state="running"),
            snapshot("connected-internal.json", egpu_id="gpd-g1:different000000"),
        )
        for changed in cases:
            with self.subTest(changed=changed):
                clock = FakeClockWaiter()
                mechanism = FakeMechanism(clock)
                result = orchestrator(
                    ScriptedObservations(
                        observation("generation-1", portable),
                        observation("generation-changed", changed),
                    ),
                    mechanism,
                    MemoryJournalStore(),
                    clock,
                ).run(plan)
                self.assertEqual(result.outcome.kind, TransitionOutcomeKind.BLOCKED)
                self.assertEqual(mechanism.applied, [])

    def test_verification_polls_within_deadline_then_commits(self):
        portable = snapshot("connected-internal.json")
        docked = snapshot("tv-docked.json")
        plan = experimental_plan(portable)
        clock = FakeClockWaiter()
        result = orchestrator(
            ScriptedObservations(
                observation("generation-1", portable),
                observation("generation-1b", portable),
                observation("generation-1b", portable),
                observation("generation-2", docked),
            ),
            FakeMechanism(clock),
            MemoryJournalStore(),
            clock,
        ).run(plan)
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.SUCCEEDED)
        self.assertEqual(clock.waits, [100])

    def test_verification_timeout_at_source_still_requires_mechanism_recovery(self):
        portable = snapshot("connected-internal.json")
        plan = experimental_plan(portable)
        clock = FakeClockWaiter()
        mechanism = FakeMechanism(clock)
        store = MemoryJournalStore()
        result = orchestrator(
            ScriptedObservations(
                observation("generation-1", portable),
                observation("generation-1b", portable),
                observation("generation-1b", portable),
                observation("generation-1b", portable),
                observation("generation-1b", portable),
                observation("generation-before-recovery", portable),
                observation("generation-recovered", portable),
                observation("generation-recovered-verified", portable),
            ),
            mechanism,
            store,
            clock,
        ).run(plan)
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.RECOVERED)
        self.assertEqual(result.outcome.placement, PlacementState.PORTABLE)
        self.assertEqual(len(mechanism.recoveries), 1)
        self.assertNotIn(
            JournalEventKind.COMMITTED,
            [entry.kind for entry in result.journal.entries],
        )

    def test_source_display_cannot_hide_failed_audio_recovery(self):
        portable = snapshot("connected-internal.json")
        plan = experimental_plan(portable)
        clock = FakeClockWaiter()
        mechanism = FakeMechanism(clock,
            apply=MechanismResult(False, "audio.verification_failed"),
            recover=MechanismResult(False, "audio.portable_sink_unavailable"))
        result = orchestrator(ScriptedObservations(
            observation("generation-1", portable),
            observation("generation-1b", portable),
            observation("generation-before-recovery", portable),
            observation("generation-recovered", portable),
        ), mechanism, MemoryJournalStore(), clock).run(plan)
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.FAILED)
        self.assertFalse(result.outcome.recovery.verified)
        self.assertEqual(len(mechanism.recoveries), 1)

    def test_mechanism_exception_is_categorical_and_source_proof_recovers(self):
        portable = snapshot("connected-internal.json")
        plan = experimental_plan(portable)
        clock = FakeClockWaiter()
        mechanism = FakeMechanism(clock, apply=OSError("private mechanism detail"))
        result = orchestrator(
            ScriptedObservations(
                observation("generation-1", portable),
                observation("generation-1b", portable),
                observation("generation-before-recovery", portable),
                observation("generation-recovered", portable),
            ),
            mechanism,
            MemoryJournalStore(),
            clock,
        ).run(plan)
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.RECOVERED)
        self.assertEqual(result.outcome.failure.code, "mechanism.exception")
        self.assertNotIn("private", repr(result))

    def test_commit_persistence_failure_recovers_but_requires_action(self):
        portable = snapshot("connected-internal.json")
        docked = snapshot("tv-docked.json")
        plan = experimental_plan(portable)
        clock = FakeClockWaiter()
        mechanism = FakeMechanism(clock)
        store = MemoryJournalStore(fail_kind=JournalEventKind.COMMITTED)
        result = orchestrator(
            ScriptedObservations(
                observation("generation-1", portable),
                observation("generation-1b", portable),
                observation("generation-2", docked),
                observation("generation-before-recovery", docked),
                observation("generation-recovered", portable),
            ),
            mechanism,
            store,
            clock,
        ).run(plan)
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.FAILED)
        self.assertTrue(result.outcome.recovery.verified)
        self.assertFalse(result.durable)
        self.assertEqual(len(mechanism.recoveries), 1)

    def test_existing_incomplete_operation_blocks_a_new_plan(self):
        portable = snapshot("connected-internal.json")
        plan = experimental_plan(portable)
        current = append_journal_entry(
            TransitionJournal("older-operation", "older-request"),
            kind=JournalEventKind.REQUESTED,
            occurred_at="2026-08-31T12:00:00Z",
            workflow_state=plan.workflow_state,
            placement=PlacementState.PORTABLE,
            code="request.accepted",
        )
        clock = FakeClockWaiter()
        mechanism = FakeMechanism(clock)
        result = orchestrator(
            ScriptedObservations(),
            mechanism,
            MemoryJournalStore(current=current),
            clock,
        ).run(plan)
        self.assertEqual(result.outcome.failure.code, "journal.recovery_required")
        self.assertEqual(mechanism.applied, [])

    def test_restart_at_source_requires_recovery_for_pending_restart_and_audio(self):
        portable = snapshot("connected-internal.json")
        plan = experimental_plan(portable)
        journal = TransitionJournal(plan.plan_id, plan.request_id)
        for kind, code in (
            (JournalEventKind.REQUESTED, "request.accepted"),
            (JournalEventKind.OBSERVED, "snapshot.observed"),
            (JournalEventKind.VALIDATED, "plan.validated"),
            (JournalEventKind.PLANNED, "plan.ready"),
            (JournalEventKind.STEP_STARTED, "step.started"),
        ):
            journal = append_journal_entry(
                journal,
                kind=kind,
                occurred_at="2026-08-31T12:00:00Z",
                workflow_state=plan.workflow_state,
                placement=PlacementState.PORTABLE,
                code=code,
                details=(
                    (("step_code", "presentation.apply_docked_egpu"),)
                    if kind is JournalEventKind.STEP_STARTED
                    else ()
                ),
            )
        clock = FakeClockWaiter()
        mechanism = FakeMechanism(clock)
        store = MemoryJournalStore(current=journal)
        result = orchestrator(
            ScriptedObservations(
                observation("generation-current", portable),
                observation("generation-recovered", portable),
            ),
            mechanism,
            store,
            clock,
        ).recover_interrupted()
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.RECOVERED)
        self.assertEqual(result.journal.entries[-1].kind, JournalEventKind.RECOVERY_VERIFIED)
        self.assertEqual(len(mechanism.recoveries), 1)

    def test_restart_before_any_mutation_terminals_without_recovery(self):
        portable = snapshot("connected-internal.json")
        plan = experimental_plan(portable)
        journal = TransitionJournal(plan.plan_id, plan.request_id)
        for kind, code in (
            (JournalEventKind.REQUESTED, "request.accepted"),
            (JournalEventKind.OBSERVED, "snapshot.observed"),
            (JournalEventKind.VALIDATED, "plan.validated"),
            (JournalEventKind.PLANNED, "plan.ready"),
        ):
            journal = append_journal_entry(
                journal,
                kind=kind,
                occurred_at="2026-08-31T12:00:00Z",
                workflow_state=plan.workflow_state,
                placement=PlacementState.PORTABLE,
                code=code,
            )
        clock = FakeClockWaiter()
        mechanism = FakeMechanism(clock)
        result = orchestrator(
            ScriptedObservations(observation("generation-current", portable)),
            mechanism,
            MemoryJournalStore(current=journal),
            clock,
        ).recover_interrupted()
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.FAILED)
        self.assertEqual(mechanism.recoveries, [])
        self.assertEqual(result.journal.entries[-1].kind, JournalEventKind.FAILED)


class FreshRecoveryRuntimeTests(unittest.TestCase):
    def run_recovery(self, *, interrupted=False, duplicate=False,
                     duplicate_then_fresh=False, recovery_ok=True,
                     recovery_duration=10, observation_duration=0,
                     fail_kind=None):
        source = snapshot("connected-internal.json")
        scans = [versioned_snapshot_observation(replace(
            source, observed_at=f"2026-10-02T16:00:{index:02d}Z"))
            for index in range(4)]
        self.assertEqual(len({scan.generation for scan in scans}), 1)
        self.assertEqual(len({scan.sample_id for scan in scans}), 4)
        plan = experimental_plan(source, scans[0].generation)
        clock = FakeClockWaiter()

        class Mechanism(FakeMechanism):
            def recover(self, *args):
                result = super().recover(*args)
                clock.value += recovery_duration - 10
                return result

        class Observations(ScriptedObservations):
            def observe(self):
                if len(self.values) == 1:
                    clock.value += observation_duration
                return super().observe()

        mechanism = Mechanism(clock,
            apply=MechanismResult(False, "display.apply_failed"),
            recover=MechanismResult(recovery_ok, "recovery.result"))
        journal = None
        if interrupted:
            journal = TransitionJournal(plan.plan_id, plan.request_id)
            for kind, code in (
                (JournalEventKind.REQUESTED, "request.accepted"),
                (JournalEventKind.OBSERVED, "snapshot.observed"),
                (JournalEventKind.VALIDATED, "plan.validated"),
                (JournalEventKind.PLANNED, "plan.ready"),
                (JournalEventKind.STEP_STARTED, "step.started"),
            ):
                journal = append_journal_entry(journal, kind=kind,
                    occurred_at="2026-10-02T16:00:00Z",
                    workflow_state=plan.workflow_state, placement=PlacementState.PORTABLE,
                    code=code, details=(("step_code", "presentation.apply_docked_egpu"),)
                    if kind is JournalEventKind.STEP_STARTED else ())
        values = [scans[2]] if interrupted else scans[:3]
        values += [scans[2]] if duplicate or duplicate_then_fresh else [scans[3]]
        if duplicate_then_fresh:
            values.append(scans[3])
        store = MemoryJournalStore(current=journal, fail_kind=fail_kind)
        service = orchestrator(Observations(*values), mechanism, store, clock)
        result = (service.recover_interrupted(recovery_deadline_ms=300)
                  if interrupted else service.run(plan))
        self.assertEqual(len(mechanism.recoveries), 1)
        self.assertEqual(len(mechanism.applied), 0 if interrupted else 1)
        self.assertNotIn(JournalEventKind.COMMITTED,
                         [entry.kind for entry in result.journal.entries])
        return result, clock

    def test_fresh_unchanged_source_verifies_normal_and_interrupted_recovery(self):
        for interrupted in (False, True):
            with self.subTest(interrupted=interrupted):
                result, _ = self.run_recovery(interrupted=interrupted)
                self.assertEqual(result.outcome.kind, TransitionOutcomeKind.RECOVERED)
                self.assertTrue(result.outcome.recovery.verified)
                self.assertTrue(result.durable)
                self.assertEqual(result.journal.entries[-1].kind,
                                 JournalEventKind.RECOVERY_VERIFIED)

    def test_duplicate_source_sample_cannot_verify_recovery(self):
        for interrupted in (False, True):
            with self.subTest(interrupted=interrupted):
                result, _ = self.run_recovery(interrupted=interrupted, duplicate=True)
                self.assertEqual(result.outcome.kind, TransitionOutcomeKind.FAILED)
                self.assertFalse(result.outcome.recovery.verified)

    def test_duplicate_sample_waits_for_an_independently_fresh_source_scan(self):
        result, clock = self.run_recovery(duplicate_then_fresh=True)
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.RECOVERED)
        self.assertEqual(clock.waits, [100])

    def test_fresh_source_cannot_hide_failed_recovery_mechanism(self):
        for interrupted in (False, True):
            with self.subTest(interrupted=interrupted):
                result, _ = self.run_recovery(interrupted=interrupted, recovery_ok=False)
                self.assertEqual(result.outcome.kind, TransitionOutcomeKind.FAILED)
                self.assertFalse(result.outcome.recovery.verified)

    def test_fresh_source_cannot_hide_recovery_deadline_expiry(self):
        for interrupted in (False, True):
            for durations in ((301, 0), (10, 291)):
                with self.subTest(interrupted=interrupted, durations=durations):
                    result, _ = self.run_recovery(interrupted=interrupted,
                        recovery_duration=durations[0], observation_duration=durations[1])
                    self.assertEqual(result.outcome.kind, TransitionOutcomeKind.FAILED)
                    self.assertFalse(result.outcome.recovery.verified)

    def test_fresh_source_at_recovery_deadline_is_accepted(self):
        result, _ = self.run_recovery(observation_duration=290)
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.RECOVERED)

    def test_fresh_recovery_cannot_hide_journal_verification_failure(self):
        result, _ = self.run_recovery(fail_kind=JournalEventKind.RECOVERY_VERIFIED)
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.FAILED)
        self.assertTrue(result.outcome.recovery.verified)
        self.assertFalse(result.durable)
        self.assertEqual(result.outcome.failure.code, "journal.persist_failed")


if __name__ == "__main__":
    unittest.main()
