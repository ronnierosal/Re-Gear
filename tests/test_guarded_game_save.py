from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.guarded_game_save import (  # noqa: E402
    GameSaveApprovalStore,
    GuardedGameSaveService,
)
from regear.application.sleep_workflow_journal import start_sleep_journal  # noqa: E402
from regear.domain.control_plane import PlacementState  # noqa: E402
from regear.domain.game_compatibility import GameSaveCapability  # noqa: E402
from regear.domain.game_save import (  # noqa: E402
    GameSaveProofObservation,
    GameSaveProofState,
    VerifiedGameSaveRecipe,
)
from regear.domain.game_session import (  # noqa: E402
    ActiveGameIdentity,
    GameSessionObservation,
)
from regear.domain.models import GameState  # noqa: E402
from regear.domain.sleep_workflow import SleepFlow, SleepFlowStage  # noqa: E402
from regear.domain.transition_journal import (  # noqa: E402
    JournalEventKind,
    journal_to_dict,
)
from regear.ports.game_save import GameSaveMechanismResult  # noqa: E402


IDENTITY = ActiveGameIdentity(
    "1234", ("app-steam-app1234-fixture.scope",)
)
RECIPE = VerifiedGameSaveRecipe(
    "recipe-verified-0001",
    "evidence-reviewed-0001",
    "1234",
    "test-host",
    "test-egpu",
)


def game(sample, *, generation="game-generation", identity=IDENTITY):
    return GameSessionObservation(
        GameState.RUNNING, generation, sample, identity
    )


def proof(sample, *, generation="proof-generation-1", state=None):
    return GameSaveProofObservation(
        state or GameSaveProofState.UNVERIFIED, generation, sample
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
        save_capability=GameSaveCapability.VERIFIED_TRIGGERABLE_AUTOSAVE,
    )


class Values:
    def __init__(self, *values):
        self.values = list(values)

    def observe(self, *_args):
        if not self.values:
            raise OSError("observation unavailable")
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


class Sleep:
    def __init__(self, store, *, mark=True):
        self.store = store
        self.mark = mark
        self.completed = False

    def game_save_requirements(self, request_id):
        if request_id != "sleep-request-0001" or self.completed:
            return "", "", ""
        return "sleep-operation-0001", "test-host", "test-egpu"

    def mark_verified_game_save_completed(self, request_id, parent):
        self.completed = bool(
            self.mark
            and request_id == "sleep-request-0001"
            and parent == "sleep-operation-0001"
            and self.store.current.entries[-1].kind
            is JournalEventKind.SUBSTEP_VERIFIED
        )
        return self.completed


class Recipes:
    def __init__(self, value=RECIPE):
        self.value = value
        self.calls = []

    def resolve(self, **values):
        self.calls.append(values)
        return self.value


class Mechanism:
    def __init__(self, store, result=None, *, fail=False):
        self.store = store
        self.result = result or GameSaveMechanismResult(
            True, "game.save_requested"
        )
        self.fail = fail
        self.calls = []
        self.preceded_by_durable_substep = False

    def request_save(self, recipe, identity):
        self.calls.append((recipe, identity))
        self.preceded_by_durable_substep = (
            self.store.current.entries[-1].kind
            is JournalEventKind.SUBSTEP_STARTED
        )
        if self.fail:
            raise OSError("save mechanism unavailable")
        return self.result


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


def service(
    games,
    proofs,
    *,
    recipe=RECIPE,
    mechanism_result=None,
    mechanism_fail=False,
    mark=True,
    wait_fail=False,
    deadline=500,
):
    store = JournalStore()
    sleep = Sleep(store, mark=mark)
    clock = Clock()
    waiter = Waiter(clock, fail=wait_fail)
    mechanism = Mechanism(
        store, mechanism_result, fail=mechanism_fail
    )
    value = GuardedGameSaveService(
        sleep=sleep,
        games=games,
        recipes=Recipes(recipe),
        proofs=proofs,
        mechanism=mechanism,
        approvals=GameSaveApprovalStore(
            monotonic=lambda: 0,
            token_factory=lambda: "game-save-approval-0001",
        ),
        journal_store=store,
        clock=clock,
        waiter=waiter,
        occurred_at=lambda: "test",
        save_deadline_ms=deadline,
        poll_interval_ms=100,
    )
    return value, store, sleep, mechanism, waiter


class GuardedGameSaveTests(unittest.TestCase):
    def test_exact_recipe_and_new_proof_complete_same_sleep_child(self):
        value, store, sleep, mechanism, _ = service(
            Values(game("game-1"), game("game-2"), game("game-3")),
            Values(
                proof("proof-1"),
                proof("proof-2"),
                proof(
                    "proof-3",
                    generation="proof-generation-2",
                    state=GameSaveProofState.VERIFIED,
                ),
            ),
        )
        plan = value.prepare("sleep-request-0001")
        self.assertTrue(plan.ready)
        result = value.execute("sleep-request-0001", plan.execution_token)
        self.assertTrue(result.accepted)
        self.assertTrue(result.save_verified)
        self.assertTrue(sleep.completed)
        self.assertTrue(mechanism.preceded_by_durable_substep)
        self.assertEqual(
            store.current.entries[-1].kind,
            JournalEventKind.SUBSTEP_VERIFIED,
        )
        serialized = json.dumps(journal_to_dict(store.current))
        for private in (
            "1234",
            "app-steam",
            RECIPE.recipe_id,
            RECIPE.evidence_id,
            RECIPE.host_profile_id,
            RECIPE.egpu_profile_id,
        ):
            self.assertNotIn(private, serialized)

    def test_missing_or_mismatched_recipe_never_issues_authority(self):
        for recipe in (
            None,
            VerifiedGameSaveRecipe(
                "recipe-verified-0002",
                "evidence-reviewed-0002",
                "5678",
                "test-host",
                "test-egpu",
            ),
        ):
            with self.subTest(recipe=recipe):
                value, store, _, mechanism, _ = service(
                    Values(game("game-1")), Values(), recipe=recipe
                )
                plan = value.prepare("sleep-request-0001")
                self.assertFalse(plan.ready)
                self.assertEqual(
                    plan.blockers,
                    ("game.verified_save_recipe_unavailable",),
                )
                self.assertEqual(mechanism.calls, [])
                self.assertFalse(store.current.terminal)

    def test_unknown_save_proof_never_issues_authority(self):
        value, store, _, mechanism, _ = service(
            Values(game("game-1")),
            Values(
                proof(
                    "proof-1",
                    state=GameSaveProofState.UNKNOWN,
                )
            ),
        )
        plan = value.prepare("sleep-request-0001")
        self.assertEqual(plan.blockers, ("game.save_proof_unavailable",))
        self.assertEqual(mechanism.calls, [])
        self.assertFalse(store.current.terminal)

    def test_game_or_proof_change_before_action_fails_closed(self):
        changed_identity = ActiveGameIdentity(
            "5678", ("app-steam-app5678-other.scope",)
        )
        cases = (
            (
                Values(game("game-1"), game("game-2", identity=changed_identity)),
                Values(proof("proof-1")),
                "game.identity_changed",
            ),
            (
                Values(game("game-1"), game("game-2")),
                Values(
                    proof("proof-1"),
                    proof("proof-2", generation="proof-changed"),
                ),
                "game.save_proof_changed",
            ),
        )
        for games, proofs, code in cases:
            with self.subTest(code=code):
                value, store, _, mechanism, _ = service(games, proofs)
                plan = value.prepare("sleep-request-0001")
                result = value.execute(
                    "sleep-request-0001", plan.execution_token
                )
                self.assertEqual(result.code, code)
                self.assertEqual(mechanism.calls, [])
                self.assertEqual(
                    store.current.entries[-1].kind, JournalEventKind.FAILED
                )

    def test_mechanism_refusal_is_terminal_after_durable_substep(self):
        value, store, _, mechanism, _ = service(
            Values(game("game-1"), game("game-2")),
            Values(proof("proof-1"), proof("proof-2")),
            mechanism_result=GameSaveMechanismResult(
                False, "game.save_not_supported"
            ),
        )
        plan = value.prepare("sleep-request-0001")
        result = value.execute("sleep-request-0001", plan.execution_token)
        self.assertEqual(result.code, "game.save_not_supported")
        self.assertTrue(result.action_required)
        self.assertTrue(mechanism.preceded_by_durable_substep)
        self.assertEqual(store.current.entries[-1].kind, JournalEventKind.FAILED)

    def test_verification_timeout_is_bounded(self):
        value, store, _, mechanism, waiter = service(
            Values(
                game("game-1"),
                game("game-2"),
                game("game-3"),
                game("game-4"),
                game("game-5"),
            ),
            Values(
                proof("proof-1"),
                proof("proof-2"),
                proof("proof-3"),
                proof("proof-4"),
                proof("proof-5"),
            ),
            deadline=300,
        )
        plan = value.prepare("sleep-request-0001")
        result = value.execute("sleep-request-0001", plan.execution_token)
        self.assertEqual(result.code, "game.save_verification_timeout")
        self.assertEqual(waiter.calls, [100, 100, 100])
        self.assertEqual(len(mechanism.calls), 1)
        self.assertEqual(store.current.entries[-1].kind, JournalEventKind.FAILED)

    def test_wait_failure_is_terminal_and_never_escapes(self):
        value, store, _, mechanism, waiter = service(
            Values(game("game-1"), game("game-2"), game("game-3")),
            Values(proof("proof-1"), proof("proof-2"), proof("proof-3")),
            wait_fail=True,
        )
        plan = value.prepare("sleep-request-0001")
        result = value.execute("sleep-request-0001", plan.execution_token)
        self.assertEqual(result.code, "game.save_wait_failed")
        self.assertEqual(waiter.calls, [100])
        self.assertEqual(len(mechanism.calls), 1)
        self.assertEqual(store.current.entries[-1].kind, JournalEventKind.FAILED)

    def test_canonical_completion_rejection_terminalizes_parent(self):
        value, store, sleep, mechanism, _ = service(
            Values(game("game-1"), game("game-2"), game("game-3")),
            Values(
                proof("proof-1"),
                proof("proof-2"),
                proof(
                    "proof-3",
                    generation="proof-generation-2",
                    state=GameSaveProofState.VERIFIED,
                ),
            ),
            mark=False,
        )
        plan = value.prepare("sleep-request-0001")
        result = value.execute("sleep-request-0001", plan.execution_token)
        self.assertEqual(result.code, "game.save_completion_rejected")
        self.assertFalse(sleep.completed)
        self.assertEqual(len(mechanism.calls), 1)
        self.assertEqual(store.current.entries[-1].kind, JournalEventKind.FAILED)

    def test_approval_is_single_use(self):
        approvals = GameSaveApprovalStore(
            monotonic=lambda: 0,
            token_factory=lambda: "game-save-approval-0001",
        )
        approval = approvals.issue(
            parent_operation_id="sleep-operation-0001",
            identity=IDENTITY,
            recipe=RECIPE,
            game=game("game-1"),
            proof=proof("proof-1"),
        )
        approvals.consume(approval.token)
        with self.assertRaisesRegex(ValueError, "already used"):
            approvals.consume(approval.token)

    def test_approval_expires(self):
        now = [0.0]
        approvals = GameSaveApprovalStore(
            ttl_seconds=10,
            monotonic=lambda: now[0],
            token_factory=lambda: "game-save-approval-0001",
        )
        approval = approvals.issue(
            parent_operation_id="sleep-operation-0001",
            identity=IDENTITY,
            recipe=RECIPE,
            game=game("game-1"),
            proof=proof("proof-1"),
        )
        now[0] = 10.1
        with self.assertRaisesRegex(ValueError, "expired"):
            approvals.consume(approval.token)


if __name__ == "__main__":
    unittest.main()
