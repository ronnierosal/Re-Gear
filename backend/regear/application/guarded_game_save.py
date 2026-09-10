"""Exact-recipe, proof-verified game save as a canonical sleep child."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable

from ..domain.control_plane import WorkflowState
from ..domain.game_save import (
    GameSaveProofObservation,
    GameSaveProofState,
    VerifiedGameSaveRecipe,
)
from ..domain.game_session import ActiveGameIdentity, GameSessionObservation
from ..domain.transition_journal import (
    JournalEventKind,
    SAFE_TOKEN,
    TransitionJournal,
    append_journal_entry,
)
from ..ports.game_save import (
    GameSaveMechanismPort,
    GameSaveProofObservationPort,
    VerifiedGameSaveRecipePort,
)
from ..ports.game_session import GameSessionObservationPort
from ..ports.runtime_transition import DeadlineWaitPort
from ..ports.transition import MonotonicClockPort
from ..ports.transition_journal import TransitionJournalPort
from .canonical_sleep import CanonicalSleepWorkflowService
from .process_release import TOKEN_RE


@dataclass(frozen=True, slots=True)
class GameSaveApproval:
    token: str
    parent_operation_id: str
    identity: ActiveGameIdentity
    recipe: VerifiedGameSaveRecipe
    game_generation: str
    game_sample_id: str
    proof_state: GameSaveProofState
    proof_generation: str
    proof_sample_id: str
    expires_in_seconds: int


@dataclass(frozen=True, slots=True)
class GuardedGameSavePlan:
    ready: bool
    steam_app_id: str = ""
    execution_token: str = ""
    expires_in_seconds: int = 0
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GuardedGameSaveExecution:
    accepted: bool
    code: str
    parent_operation_id: str = ""
    save_verified: bool = False
    action_required: bool = False


class GameSaveApprovalStore:
    def __init__(
        self,
        *,
        ttl_seconds: float = 120.0,
        max_tokens: int = 3,
        monotonic: Callable[[], float] = time.monotonic,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        if ttl_seconds <= 0 or ttl_seconds > 300:
            raise ValueError("game-save approval TTL is invalid")
        if max_tokens <= 0 or max_tokens > 10:
            raise ValueError("game-save approval bound is invalid")
        self._ttl_seconds = ttl_seconds
        self._max_tokens = max_tokens
        self._monotonic = monotonic
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(18))
        self._values: dict[str, tuple[float, GameSaveApproval]] = {}
        self._lock = threading.Lock()

    def issue(
        self,
        *,
        parent_operation_id: str,
        identity: ActiveGameIdentity,
        recipe: VerifiedGameSaveRecipe,
        game: GameSessionObservation,
        proof: GameSaveProofObservation,
    ) -> GameSaveApproval:
        if not TOKEN_RE.fullmatch(parent_operation_id):
            raise ValueError("game-save parent operation identity is invalid")
        if not game.exact or game.identity != identity or not proof.exact:
            raise ValueError("exact game-save evidence is required")
        with self._lock:
            self._expire_locked()
            while len(self._values) >= self._max_tokens:
                oldest = min(self._values, key=lambda token: self._values[token][0])
                self._values.pop(oldest)
            token = self._token_factory()
            if not TOKEN_RE.fullmatch(token) or token in self._values:
                raise ValueError("game-save approval token is invalid")
            approval = GameSaveApproval(
                token,
                parent_operation_id,
                identity,
                recipe,
                game.generation,
                game.sample_id,
                proof.state,
                proof.generation,
                proof.sample_id,
                max(1, int(self._ttl_seconds)),
            )
            self._values[token] = (self._monotonic(), approval)
            return approval

    def consume(self, token: str) -> GameSaveApproval:
        if not TOKEN_RE.fullmatch(token):
            raise ValueError("game-save approval token is invalid")
        with self._lock:
            self._expire_locked()
            value = self._values.pop(token, None)
            if value is None:
                raise ValueError("game-save approval expired or was already used")
            return value[1]

    def _expire_locked(self) -> None:
        cutoff = self._monotonic() - self._ttl_seconds
        for token in [
            token for token, (created, _) in self._values.items() if created < cutoff
        ]:
            self._values.pop(token, None)


class GuardedGameSaveService:
    """Run one reviewed recipe only after consent is bound by canonical sleep."""

    def __init__(
        self,
        *,
        sleep: CanonicalSleepWorkflowService,
        games: GameSessionObservationPort,
        recipes: VerifiedGameSaveRecipePort,
        proofs: GameSaveProofObservationPort,
        mechanism: GameSaveMechanismPort,
        approvals: GameSaveApprovalStore,
        journal_store: TransitionJournalPort,
        clock: MonotonicClockPort,
        waiter: DeadlineWaitPort,
        occurred_at: Callable[[], str],
        save_deadline_ms: int = 5_000,
        poll_interval_ms: int = 100,
    ) -> None:
        if save_deadline_ms <= 0 or save_deadline_ms > 30_000:
            raise ValueError("game-save deadline is invalid")
        if poll_interval_ms <= 0 or poll_interval_ms > 250:
            raise ValueError("game-save poll interval is invalid")
        self._sleep = sleep
        self._games = games
        self._recipes = recipes
        self._proofs = proofs
        self._mechanism = mechanism
        self._approvals = approvals
        self._journal_store = journal_store
        self._clock = clock
        self._waiter = waiter
        self._occurred_at = occurred_at
        self._deadline_ms = save_deadline_ms
        self._poll_ms = poll_interval_ms
        self._lock = threading.Lock()

    def prepare(self, request_id: str) -> GuardedGameSavePlan:
        try:
            parent, host_profile_id, egpu_profile_id = (
                self._sleep.game_save_requirements(request_id)
            )
        except Exception:
            parent = host_profile_id = egpu_profile_id = ""
        if not parent:
            return GuardedGameSavePlan(
                False, blockers=("sleep.game_save_step_inactive",)
            )
        game = self._observe_game()
        if game is None or not game.exact or game.identity is None:
            return GuardedGameSavePlan(False, blockers=("game.identity_unverified",))
        recipe = self._resolve_recipe(
            game.identity, host_profile_id, egpu_profile_id
        )
        if recipe is None:
            return GuardedGameSavePlan(
                False, game.identity.steam_app_id,
                blockers=("game.verified_save_recipe_unavailable",),
            )
        proof = self._observe_proof(recipe, game.identity)
        if proof is None or not proof.exact:
            return GuardedGameSavePlan(
                False, game.identity.steam_app_id,
                blockers=("game.save_proof_unavailable",),
            )
        try:
            approval = self._approvals.issue(
                parent_operation_id=parent,
                identity=game.identity,
                recipe=recipe,
                game=game,
                proof=proof,
            )
        except Exception:
            return GuardedGameSavePlan(
                False, game.identity.steam_app_id,
                blockers=("game.save_approval_unavailable",),
            )
        return GuardedGameSavePlan(
            True,
            game.identity.steam_app_id,
            approval.token,
            approval.expires_in_seconds,
        )

    def execute(
        self, request_id: str, execution_token: str
    ) -> GuardedGameSaveExecution:
        if not self._lock.acquire(blocking=False):
            return GuardedGameSaveExecution(
                False, "game.save_concurrent", action_required=True
            )
        try:
            return self._execute_locked(request_id, execution_token)
        finally:
            self._lock.release()

    def _execute_locked(
        self, request_id: str, execution_token: str
    ) -> GuardedGameSaveExecution:
        try:
            approval = self._approvals.consume(execution_token)
        except ValueError:
            return GuardedGameSaveExecution(False, "game.save_approval_invalid")
        try:
            parent, host_profile_id, egpu_profile_id = (
                self._sleep.game_save_requirements(request_id)
            )
        except Exception:
            parent = host_profile_id = egpu_profile_id = ""
        if (
            not parent
            or parent != approval.parent_operation_id
            or host_profile_id != approval.recipe.host_profile_id
            or egpu_profile_id != approval.recipe.egpu_profile_id
        ):
            return GuardedGameSaveExecution(
                False,
                "game.save_parent_changed",
                approval.parent_operation_id,
                action_required=True,
            )
        game = self._observe_game()
        if (
            game is None
            or game.sample_id == approval.game_sample_id
            or game.generation != approval.game_generation
            or not game.exact
            or game.identity != approval.identity
        ):
            return self._fail(
                approval.parent_operation_id, "game.identity_changed"
            )
        recipe = self._resolve_recipe(
            approval.identity, host_profile_id, egpu_profile_id
        )
        if recipe != approval.recipe:
            return self._fail(
                approval.parent_operation_id, "game.save_recipe_changed"
            )
        proof = self._observe_proof(recipe, approval.identity)
        if (
            proof is None
            or not proof.exact
            or proof.sample_id == approval.proof_sample_id
            or proof.generation != approval.proof_generation
            or proof.state is not approval.proof_state
        ):
            return self._fail(
                approval.parent_operation_id, "game.save_proof_changed"
            )
        if self._append(
            approval.parent_operation_id,
            JournalEventKind.SUBSTEP_STARTED,
            "game.save_substep_started",
        ) is None:
            return GuardedGameSaveExecution(
                False,
                "game.journal_persist_failed",
                approval.parent_operation_id,
                action_required=True,
            )
        try:
            mechanism = self._mechanism.request_save(recipe, approval.identity)
        except Exception:
            return self._fail(
                approval.parent_operation_id, "game.save_mechanism_failed"
            )
        if not mechanism.accepted:
            return self._fail(approval.parent_operation_id, mechanism.code)

        started = self._clock.now_ms()
        previous_game_sample = game.sample_id
        previous_proof_sample = proof.sample_id
        while self._clock.now_ms() - started < self._deadline_ms:
            current_game = self._observe_game()
            current_proof = self._observe_proof(recipe, approval.identity)
            if current_game is None or current_proof is None:
                return self._fail(
                    approval.parent_operation_id, "game.save_rescan_unavailable"
                )
            if (
                current_game.sample_id == previous_game_sample
                or current_proof.sample_id == previous_proof_sample
            ):
                if not self._wait():
                    return self._fail(
                        approval.parent_operation_id, "game.save_wait_failed"
                    )
                continue
            previous_game_sample = current_game.sample_id
            previous_proof_sample = current_proof.sample_id
            if (
                not current_game.exact
                or current_game.identity != approval.identity
                or current_game.generation != approval.game_generation
            ):
                return self._fail(
                    approval.parent_operation_id, "game.identity_changed"
                )
            if not current_proof.exact:
                return self._fail(
                    approval.parent_operation_id, "game.save_proof_unavailable"
                )
            if (
                current_proof.generation != approval.proof_generation
                and current_proof.state is GameSaveProofState.VERIFIED
            ):
                if self._append(
                    approval.parent_operation_id,
                    JournalEventKind.SUBSTEP_VERIFIED,
                    "game.save_substep_verified",
                ) is None:
                    return GuardedGameSaveExecution(
                        False,
                        "game.journal_persist_failed",
                        approval.parent_operation_id,
                        action_required=True,
                    )
                if not self._sleep.mark_verified_game_save_completed(
                    request_id, approval.parent_operation_id
                ):
                    return self._fail(
                        approval.parent_operation_id,
                        "game.save_completion_rejected",
                    )
                return GuardedGameSaveExecution(
                    True,
                    "game.save_verified",
                    approval.parent_operation_id,
                    save_verified=True,
                )
            if not self._wait():
                return self._fail(
                    approval.parent_operation_id, "game.save_wait_failed"
                )
        return self._fail(
            approval.parent_operation_id, "game.save_verification_timeout"
        )

    def _resolve_recipe(
        self,
        identity: ActiveGameIdentity,
        host_profile_id: str,
        egpu_profile_id: str,
    ) -> VerifiedGameSaveRecipe | None:
        try:
            recipe = self._recipes.resolve(
                steam_app_id=identity.steam_app_id,
                host_profile_id=host_profile_id,
                egpu_profile_id=egpu_profile_id,
            )
        except Exception:
            return None
        if recipe is None or (
            recipe.steam_app_id != identity.steam_app_id
            or recipe.host_profile_id != host_profile_id
            or recipe.egpu_profile_id != egpu_profile_id
        ):
            return None
        return recipe

    def _observe_game(self) -> GameSessionObservation | None:
        try:
            return self._games.observe()
        except Exception:
            return None

    def _observe_proof(
        self,
        recipe: VerifiedGameSaveRecipe,
        identity: ActiveGameIdentity,
    ) -> GameSaveProofObservation | None:
        try:
            return self._proofs.observe(recipe, identity)
        except Exception:
            return None

    def _append(
        self,
        parent: str,
        kind: JournalEventKind,
        code: str,
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
                raise ValueError("game-save parent journal changed")
            active = next(
                (
                    entry
                    for entry in reversed(journal.entries)
                    if entry.kind is JournalEventKind.STEP_STARTED
                ),
                None,
            )
            if active is None or dict(active.details).get("step_code") != "closing_game":
                raise ValueError("game-save parent step changed")
            updated = append_journal_entry(
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
                    (("step_code", "game_save.verified"),)
                    if kind
                    in {
                        JournalEventKind.SUBSTEP_STARTED,
                        JournalEventKind.SUBSTEP_VERIFIED,
                    }
                    else ()
                ),
            )
            self._journal_store.save(updated)
            return updated
        except (OSError, ValueError):
            return None

    def _fail(self, parent: str, code: str) -> GuardedGameSaveExecution:
        safe_code = code if SAFE_TOKEN.fullmatch(code) else "game.save_failed"
        journal = self._append(parent, JournalEventKind.FAILED, safe_code)
        if journal is None:
            safe_code = "game.journal_persist_failed"
        return GuardedGameSaveExecution(
            False, safe_code, parent, action_required=True
        )

    def _wait(self) -> bool:
        try:
            self._waiter.wait_ms(self._poll_ms)
            return True
        except Exception:
            return False
