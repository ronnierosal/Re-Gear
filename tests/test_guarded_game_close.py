from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.canonical_sleep import CanonicalSleepResult  # noqa: E402
from regear.application.guarded_game_close import (  # noqa: E402
    GameCloseApprovalStore,
    GuardedGameCloseService,
)
from regear.application.sleep_workflow_journal import start_sleep_journal  # noqa: E402
from regear.domain.control_plane import PlacementState  # noqa: E402
from regear.domain.game_compatibility import GameSaveCapability  # noqa: E402
from regear.domain.game_session import (  # noqa: E402
    ActiveGameIdentity,
    GameSessionObservation,
)
from regear.domain.models import GameState  # noqa: E402
from regear.domain.sleep_workflow import (  # noqa: E402
    SleepFlow,
    SleepFlowEvent,
    SleepFlowStage,
)
from regear.domain.transition_journal import (  # noqa: E402
    JournalEventKind,
    journal_to_dict,
)
from regear.ports.game_close import GameCloseMechanismResult  # noqa: E402


IDENTITY = ActiveGameIdentity(
    "1234", ("app-steam-app1234-fixture.scope",)
)


def observed(sample, *, state=GameState.RUNNING, identity=IDENTITY):
    semantic = (
        "game-running" if state is GameState.RUNNING else state.value
    )
    return GameSessionObservation(
        state,
        semantic,
        sample,
        identity if state is GameState.RUNNING else None,
    )


def closing_flow():
    return SleepFlow(
        "sleep-request-0001",
        SleepFlowStage.CLOSING_GAME,
        (),
        True,
        "game.close_requested",
        0,
        900_000,
        save_capability=GameSaveCapability.UNTESTED,
    )


class Sleep:
    def __init__(
        self,
        parent="sleep-operation-0001",
        save_capability=GameSaveCapability.UNTESTED,
        save_completed=False,
    ):
        self.parent = parent
        self.save_capability = save_capability
        self.save_completed = save_completed
        self.advances = []

    def game_close_parent_operation_id(self, request_id):
        return self.parent if request_id == "sleep-request-0001" else ""

    def game_close_requirements(self, request_id):
        parent = self.game_close_parent_operation_id(request_id)
        return (parent, self.save_capability if parent else None)

    def verified_game_save_completed(self, request_id):
        return bool(
            request_id == "sleep-request-0001" and self.save_completed
        )

    def advance(self, request_id, event):
        self.advances.append((request_id, event))
        return CanonicalSleepResult(True, "disconnect.shutdown_required")


class Observations:
    def __init__(self, *values):
        self.values = list(values)

    def observe(self):
        if not self.values:
            raise OSError("no observation")
        return self.values.pop(0)


class JournalStore:
    def __init__(self):
        self.current = start_sleep_journal(
            "sleep-operation-0001",
            closing_flow(),
            PlacementState.DOCKED_EGPU,
            occurred_at="test",
        )

    def load_current(self):
        return self.current

    def save(self, journal):
        self.current = journal


class Clock:
    def __init__(self):
        self.value = 0

    def now_ms(self):
        return self.value


class Waiter:
    def __init__(self, clock, *, fail=False):
        self.clock = clock
        self.fail = fail
        self.calls = []

    def wait_ms(self, milliseconds):
        self.calls.append(milliseconds)
        if self.fail:
            raise OSError("wait unavailable")
        self.clock.value += milliseconds


class Mechanism:
    def __init__(self, store, result=None):
        self.store = store
        self.result = result or GameCloseMechanismResult(
            True, "game.close_requested"
        )
        self.calls = []
        self.preceded_by_durable_substep = False

    def request_close(self, identity):
        self.calls.append(identity)
        self.preceded_by_durable_substep = (
            self.store.current.entries[-1].kind
            is JournalEventKind.SUBSTEP_STARTED
        )
        return self.result


def service(
    observations,
    *,
    sleep=None,
    mechanism_result=None,
    deadline=500,
    wait_fail=False,
):
    store = JournalStore()
    clock = Clock()
    waiter = Waiter(clock, fail=wait_fail)
    mechanism = Mechanism(store, mechanism_result)
    value = GuardedGameCloseService(
        sleep=sleep or Sleep(),
        observations=observations,
        mechanism=mechanism,
        approvals=GameCloseApprovalStore(
            monotonic=lambda: 0,
            token_factory=lambda: "game-close-approval-0001",
        ),
        journal_store=store,
        clock=clock,
        waiter=waiter,
        occurred_at=lambda: "test",
        close_deadline_ms=deadline,
        poll_interval_ms=100,
    )
    return value, store, mechanism, waiter


class GuardedGameCloseTests(unittest.TestCase):
    def test_inspection_has_no_token_and_exact_confirmation_closes(self):
        observations = Observations(
            observed("sample-1"),
            observed("sample-2"),
            observed("sample-3"),
            observed("sample-4", state=GameState.IDLE),
        )
        sleep = Sleep()
        value, store, mechanism, _ = service(observations, sleep=sleep)
        inspection = value.preview("sleep-request-0001", user_confirmed=False)
        self.assertTrue(inspection.ready)
        self.assertEqual(inspection.steam_app_id, "1234")
        self.assertEqual(inspection.approval_token, "")
        approval = value.preview("sleep-request-0001", user_confirmed=True)
        result = value.execute("sleep-request-0001", approval.approval_token)
        self.assertTrue(result.accepted)
        self.assertTrue(result.game_exit_verified)
        self.assertTrue(mechanism.preceded_by_durable_substep)
        self.assertEqual(store.current.entries[-1].kind, JournalEventKind.SUBSTEP_VERIFIED)
        self.assertEqual(
            sleep.advances,
            [("sleep-request-0001", SleepFlowEvent.GAME_EXIT_VERIFIED)],
        )
        serialized = json.dumps(journal_to_dict(store.current))
        self.assertNotIn("1234", serialized)
        self.assertNotIn("app-steam", serialized)

    def test_identity_change_fails_before_mechanism(self):
        changed = ActiveGameIdentity(
            "5678", ("app-steam-app5678-other.scope",)
        )
        observations = Observations(
            observed("sample-1"),
            observed("sample-2", identity=changed),
        )
        value, store, mechanism, _ = service(observations)
        approval = value.preview("sleep-request-0001", user_confirmed=True)
        result = value.execute("sleep-request-0001", approval.approval_token)
        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "game.identity_changed")
        self.assertEqual(mechanism.calls, [])
        self.assertEqual(store.current.entries[-1].kind, JournalEventKind.FAILED)

    def test_semantic_generation_change_fails_before_mechanism(self):
        observations = Observations(
            observed("sample-1"),
            GameSessionObservation(
                GameState.RUNNING,
                "different-semantic-generation",
                "sample-2",
                IDENTITY,
            ),
        )
        value, store, mechanism, _ = service(observations)
        approval = value.preview("sleep-request-0001", user_confirmed=True)
        result = value.execute("sleep-request-0001", approval.approval_token)
        self.assertEqual(result.code, "game.identity_changed")
        self.assertEqual(mechanism.calls, [])
        self.assertEqual(store.current.entries[-1].kind, JournalEventKind.FAILED)

    def test_close_timeout_is_bounded_and_action_required(self):
        observations = Observations(
            observed("sample-1"),
            observed("sample-2"),
            observed("sample-3"),
            observed("sample-4"),
            observed("sample-5"),
            observed("sample-6"),
            observed("sample-7"),
        )
        value, store, mechanism, waiter = service(observations, deadline=300)
        approval = value.preview("sleep-request-0001", user_confirmed=True)
        result = value.execute("sleep-request-0001", approval.approval_token)
        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "game.close_timeout")
        self.assertTrue(result.action_required)
        self.assertEqual(waiter.calls, [100, 100, 100])
        self.assertEqual(store.current.entries[-1].kind, JournalEventKind.FAILED)
        self.assertEqual(len(mechanism.calls), 1)

    def test_wait_failure_is_terminal_and_never_escapes(self):
        observations = Observations(
            observed("sample-1"),
            observed("sample-2"),
            observed("sample-3"),
        )
        value, store, mechanism, waiter = service(
            observations, wait_fail=True
        )
        approval = value.preview("sleep-request-0001", user_confirmed=True)
        result = value.execute("sleep-request-0001", approval.approval_token)
        self.assertEqual(result.code, "game.wait_failed")
        self.assertTrue(result.action_required)
        self.assertEqual(waiter.calls, [100])
        self.assertEqual(len(mechanism.calls), 1)
        self.assertEqual(store.current.entries[-1].kind, JournalEventKind.FAILED)

    def test_mechanism_rejection_fails_closed_after_durable_substep(self):
        observations = Observations(observed("sample-1"), observed("sample-2"))
        value, store, mechanism, _ = service(
            observations,
            mechanism_result=GameCloseMechanismResult(
                False, "game.close_not_supported"
            ),
        )
        approval = value.preview("sleep-request-0001", user_confirmed=True)
        result = value.execute("sleep-request-0001", approval.approval_token)
        self.assertEqual(result.code, "game.close_not_supported")
        self.assertTrue(result.action_required)
        self.assertTrue(mechanism.preceded_by_durable_substep)
        self.assertEqual(store.current.entries[-1].kind, JournalEventKind.FAILED)

    def test_approval_is_single_use_and_expires(self):
        now = [0.0]
        tokens = iter(("game-close-approval-0001", "game-close-approval-0002"))
        approvals = GameCloseApprovalStore(
            ttl_seconds=10,
            monotonic=lambda: now[0],
            token_factory=lambda: next(tokens),
        )
        first = approvals.issue("sleep-operation-0001", observed("sample-1"))
        approvals.consume(first.token)
        with self.assertRaisesRegex(ValueError, "expired or was already used"):
            approvals.consume(first.token)

        second = approvals.issue("sleep-operation-0001", observed("sample-2"))
        now[0] = 10.1
        with self.assertRaisesRegex(ValueError, "expired or was already used"):
            approvals.consume(second.token)

    def test_inactive_parent_or_ambiguous_game_never_issues_authority(self):
        inactive, _, mechanism, _ = service(
            Observations(), sleep=Sleep(parent="")
        )
        blocked = inactive.preview("sleep-request-0001", user_confirmed=True)
        self.assertEqual(blocked.blockers, ("sleep.game_close_step_inactive",))
        self.assertEqual(mechanism.calls, [])

        ambiguous, _, mechanism, _ = service(
            Observations(
                GameSessionObservation(
                    GameState.RUNNING, "ambiguous", "sample-1", None
                )
            )
        )
        blocked = ambiguous.preview("sleep-request-0001", user_confirmed=True)
        self.assertEqual(blocked.blockers, ("game.identity_unverified",))
        self.assertEqual(mechanism.calls, [])

    def test_verified_triggerable_save_blocks_close_until_save_child_exists(self):
        value, _, mechanism, _ = service(
            Observations(),
            sleep=Sleep(
                save_capability=GameSaveCapability.VERIFIED_TRIGGERABLE_AUTOSAVE
            ),
        )
        preview = value.preview("sleep-request-0001", user_confirmed=True)
        self.assertEqual(
            preview.blockers, ("game.verified_save_step_required",)
        )
        self.assertEqual(mechanism.calls, [])

    def test_verified_save_completion_unlocks_exact_game_close(self):
        value, _, mechanism, _ = service(
            Observations(observed("sample-1")),
            sleep=Sleep(
                save_capability=GameSaveCapability.VERIFIED_TRIGGERABLE_AUTOSAVE,
                save_completed=True,
            ),
        )
        preview = value.preview("sleep-request-0001", user_confirmed=False)
        self.assertTrue(preview.ready)
        self.assertEqual(preview.steam_app_id, "1234")
        self.assertEqual(mechanism.calls, [])


if __name__ == "__main__":
    unittest.main()
