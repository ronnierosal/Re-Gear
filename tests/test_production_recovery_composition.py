"""Recovery verification through the production adapters; all OS ports mocked."""
from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.presentation_transition import PresentationTransitionMechanism
from regear.adapters.transition_runtime import SnapshotTransitionObservationAdapter
from regear.application.transition_orchestrator import TransitionOrchestrator
from regear.domain.control_plane import PlacementState, TransitionOutcomeKind
from regear.domain.transition_journal import (
    JournalEventKind, TransitionJournal, append_journal_entry,
)
from regear.ports.presentation_activation import UserServiceOperation
from tests.test_presentation_transition import (
    BOOT_ID, USER, FakeCommands, FakeConfig, FakeIntegration,
    GamescopeUserResolution,
)
from tests.test_transition_orchestrator import (
    FakeClockWaiter, MemoryJournalStore, experimental_plan, snapshot,
)


def identity(invocation="a" * 32, *, state="active", pid="123", group="/user.slice/session"):
    return (f"MainPID={pid}\nInvocationID={invocation}\n"
            f"ActiveState={state}\nControlGroup={group}")


class ProductionRecoveryCompositionTests(unittest.TestCase):
    def run_case(self, *, interrupted=False, completion=True, duplicate=False,
                 changed_session=False, restart_failed=False, bad_after=None,
                 bad_before=None, boot_changed=False, user_changed=False,
                 read_duration=0, persist_failure=None, wrong_source=False):
        source = snapshot("connected-internal.json")
        scans = [replace(source, observed_at=f"2026-10-03T03:00:{i:02d}Z")
                 for i in range(5)]
        if changed_session:
            scans[-1] = replace(scans[-1], gamescope=replace(source.gamescope, pid=9876))
        if duplicate:
            scans[-1] = scans[-2]
        if wrong_source:
            scans[-1] = snapshot("tv-docked.json")

        class Discovery:
            def collect_snapshot(self):
                return scans.pop(0) if len(scans) > 1 else scans[0]

        observations = SnapshotTransitionObservationAdapter(Discovery())
        initial = observations.observe()
        plan = experimental_plan(source, initial.generation)
        clock = FakeClockWaiter()
        events = []
        recovery_codes = []

        class Commands(FakeCommands):
            reads = 0

            def run(self, operation, **kwargs):
                if operation is UserServiceOperation.OBSERVE_FILTER_GAMESCOPE:
                    self.reads += 1
                    if self.reads > 1:
                        clock.value += read_duration
                    output = (identity() if bad_before is None else bad_before)
                    if self.reads > 1:
                        output = (identity("b" * 32 if completion else "a" * 32)
                                  if bad_after is None else bad_after)
                    return SimpleNamespace(ok=True, output=output)
                return super().run(operation, **kwargs)

        commands = Commands(events, fail=(UserServiceOperation.RESTART_GAMESCOPE_SESSION,)
                            if restart_failed else ())

        class TracedMechanism(PresentationTransitionMechanism):
            def recover(self, *args):
                result = super().recover(*args)
                recovery_codes.append(result.code)
                return result

        mechanism = TracedMechanism(
            integration=FakeIntegration(events=events),
            config=FakeConfig(events, fail_on_call=0 if interrupted else 1),
            commands=commands,
            resolve_user=lambda: GamescopeUserResolution(None if
                user_changed and commands.reads > 0 else USER),
            read_boot_id=lambda: "different-boot" if
                boot_changed and commands.reads > 0 else BOOT_ID,
        )
        journal = None
        if interrupted:
            journal = TransitionJournal(plan.plan_id, plan.request_id)
            for kind in (JournalEventKind.REQUESTED, JournalEventKind.OBSERVED,
                         JournalEventKind.VALIDATED, JournalEventKind.PLANNED,
                         JournalEventKind.STEP_STARTED):
                journal = append_journal_entry(journal, kind=kind,
                    occurred_at="2026-10-03T03:00:00Z", workflow_state=plan.workflow_state,
                    placement=PlacementState.PORTABLE, code="step.started",
                    details=(("step_code", "presentation.apply_docked_egpu"),)
                    if kind is JournalEventKind.STEP_STARTED else ())
        store = MemoryJournalStore(current=journal, fail_kind=persist_failure)
        service = TransitionOrchestrator(observations=observations, mechanism=mechanism,
            journal_store=store, clock=clock, waiter=clock,
            occurred_at=lambda: "2026-10-03T03:00:00Z")
        result = (service.recover_interrupted(recovery_deadline_ms=300)
                  if interrupted else service.run(plan))
        self.assertEqual(len(recovery_codes), 1)
        self.assertNotIn(JournalEventKind.COMMITTED, [e.kind for e in result.journal.entries])
        return result, recovery_codes, commands

    def test_completed_invocation_verifies_fresh_unchanged_source(self):
        for interrupted in (False, True):
            with self.subTest(interrupted=interrupted):
                result, codes, _ = self.run_case(interrupted=interrupted)
                self.assertEqual(codes, ["recovery.restart_queued"])
                self.assertEqual(result.outcome.kind, TransitionOutcomeKind.RECOVERED)
                self.assertTrue(result.outcome.recovery.verified)
                self.assertTrue(result.durable)

    def test_queued_unchanged_invocation_is_not_completion(self):
        result, _, _ = self.run_case(completion=False)
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.FAILED)
        self.assertFalse(result.outcome.recovery.verified)

    def test_completion_needs_a_fresh_source_scan(self):
        result, _, _ = self.run_case(duplicate=True)
        self.assertFalse(result.outcome.recovery.verified)

    def test_completion_needs_the_expected_source(self):
        result, _, _ = self.run_case(wrong_source=True)
        self.assertFalse(result.outcome.recovery.verified)

    def test_unusable_service_identity_is_not_completion(self):
        for output in ("", identity(state="activating"), identity(pid="0"),
                       identity(invocation="0" * 32), identity(invocation="bad"),
                       identity(group=""), identity() + "\nMainPID=456",
                       identity() + "\nUnknownField=anything"):
            with self.subTest(output=output):
                result, _, _ = self.run_case(bad_after=output)
                self.assertFalse(result.outcome.recovery.verified)

    def test_missing_pre_restart_identity_is_not_completion(self):
        result, _, _ = self.run_case(bad_before="")
        self.assertFalse(result.outcome.recovery.verified)

    def test_service_group_change_is_not_completion(self):
        result, _, _ = self.run_case(bad_after=identity("b" * 32, group="/other"))
        self.assertFalse(result.outcome.recovery.verified)

    def test_changed_user_or_boot_is_not_completion(self):
        for field in ("user_changed", "boot_changed"):
            with self.subTest(field=field):
                result, _, _ = self.run_case(**{field: True})
                self.assertFalse(result.outcome.recovery.verified)

    def test_failed_restart_stays_failed(self):
        result, codes, _ = self.run_case(restart_failed=True)
        self.assertEqual(codes, ["recovery.restart_failed"])
        self.assertFalse(result.outcome.recovery.verified)

    def test_completion_read_consumes_recovery_deadline(self):
        result, _, _ = self.run_case(read_duration=301)
        self.assertFalse(result.outcome.recovery.verified)

    def test_completion_at_exact_deadline_is_accepted(self):
        result, _, _ = self.run_case(read_duration=300)
        self.assertTrue(result.outcome.recovery.verified)

    def test_verified_completion_cannot_hide_journal_failure(self):
        result, _, _ = self.run_case(persist_failure=JournalEventKind.RECOVERY_VERIFIED)
        self.assertTrue(result.outcome.recovery.verified)
        self.assertFalse(result.durable)
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.FAILED)

    def test_existing_changed_session_recovery_remains_successful(self):
        result, _, _ = self.run_case(changed_session=True, bad_before="")
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.RECOVERED)


if __name__ == "__main__":
    unittest.main()
