"""The bounded learning lifecycle for one game in one mode.

    UNKNOWN -> BASELINE -> LEARNING -> TESTING_PROFILE -> VALIDATING
                                          (next launch)       |
                         OPTIMIZED_LOCKED <--- accepted ------+
                                |                             |
                    context or qualified degradation     rejected or
                                v                        inconclusive
                       NEEDS_REVALIDATION               -> LEARNING, original
                                                           restored next launch

    USER_OVERRIDE, OPTIMIZATION_DISABLED, ADVISOR_ONLY, UNSUPPORTED
    reachable from anywhere; the first two dominate everything pending.

What this module decides is *when* a change may be tried and *what the
evidence already said about it*. It never decides what evidence means: window
verdicts arrive from outside, already classified, and the thresholds come from
an injected, versioned ``LearningPolicy``. Evidence assessment and policy
values belong to the performance resolver; this is the bookkeeping that keeps
them honest.

Four rules shape every transition:

* **Uncertain is never success.** An unqualified or INCONCLUSIVE window moves
  no counter toward acceptance. A validation that runs out of windows is
  inconclusive, which is a rejection, not a pass.
* **One candidate at a time, between launches.** A candidate is staged for the
  next launch and written then; nothing is written during play, and a game is
  never restarted to finish an experiment.
* **Bounded.** A context gets a fixed number of attempts; once they are spent
  the lifecycle stops proposing and says so, instead of tuning forever.
* **Nothing uncertain is replayed.** A write is marked in flight before it
  starts. A lifecycle reopened with that mark still set crashed mid-write: the
  attempt is recorded as uncertain and is never retried or assumed to have
  landed.

While a candidate is validating or a plan is locked, each launch dispatches
it again as a check. That is how a player's edit is noticed before any window
is judged against settings that are no longer Re-Gear's.

Disable and player edits dominate. Every pending change is cancelled, and a
player's edit is never overwritten -- the engine's conflict check is the final
authority, and a conflict it reports puts the lifecycle in USER_OVERRIDE until
the player explicitly hands the game back.

Everything is pure. Each transition returns a new state with a higher revision.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from enum import StrEnum

from .game_compatibility import STEAM_APP_ID_RE
from .game_optimization_preferences import EffectiveIntent
from .graphics_profiles import SupportTier
from .mode_profiles import ExperienceTarget
from .models import OperatingMode
from .performance_plan import PerformancePlan


STATE_VERSION = 1
CANDIDATE_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
MAX_REASON = 240
#: Modes a lifecycle can exist for. UNKNOWN and DEGRADED withhold automatic
#: application altogether; they never get a lane of their own.
MANAGED_MODES = (
    OperatingMode.PORTABLE,
    OperatingMode.BOOSTED_HANDHELD,
    OperatingMode.TV_DOCKED,
)


class Phase(StrEnum):
    UNKNOWN = "unknown"
    BASELINE = "baseline"
    LEARNING = "learning"
    TESTING_PROFILE = "testing_profile"
    VALIDATING = "validating"
    OPTIMIZED_LOCKED = "optimized_locked"
    NEEDS_REVALIDATION = "needs_revalidation"
    USER_OVERRIDE = "user_override"
    ADVISOR_ONLY = "advisor_only"
    UNSUPPORTED = "unsupported"
    OPTIMIZATION_DISABLED = "optimization_disabled"


#: Phases only an explicit player act leaves.
DOMINANT = (Phase.USER_OVERRIDE, Phase.OPTIMIZATION_DISABLED)


class WindowVerdict(StrEnum):
    """An externally assessed verdict on one observation window."""

    MEETS_TARGET = "meets_target"
    BELOW_TARGET = "below_target"
    INCONCLUSIVE = "inconclusive"


class AttemptOutcome(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"
    NOT_APPLIED = "not_applied"
    UNCERTAIN = "uncertain"
    CANCELLED = "cancelled"
    CONFLICT = "conflict"


class DispatchKind(StrEnum):
    APPLY_CANDIDATE = "apply_candidate"
    REAPPLY_ACCEPTED = "reapply_accepted"
    RESTORE_ORIGINAL = "restore_original"


class DispatchResult(StrEnum):
    """What the engine reported for one dispatch, in lifecycle terms."""

    #: The intended bytes are on disk (written now, or already there).
    LANDED = "landed"
    #: The game was running or its state unknown: nothing written, try later.
    DEFERRED = "deferred"
    #: The player changed the file since Re-Gear last wrote it.
    CONFLICT = "conflict"
    ADVISOR = "advisor"
    UNSUPPORTED = "unsupported"
    #: Failed, rolled back or not located: nothing of ours landed.
    NOT_APPLIED = "not_applied"


@dataclass(frozen=True, slots=True)
class LearningPolicy:
    """Thresholds for the lifecycle. Values belong to the resolver's policy.

    ``policy_version`` 0 marks these defaults as unreviewed placeholders: they
    make the mechanics testable and are not a claim about how many windows a
    real game needs.
    """

    policy_version: int = 0
    #: Qualified windows of ordinary play before a candidate may be staged.
    learning_windows: int = 3
    #: Qualified MEETS_TARGET windows that accept a candidate.
    accept_windows: int = 3
    #: Qualified BELOW_TARGET windows that reject a candidate, and that mark
    #: a locked profile as degraded.
    reject_windows: int = 2
    #: Windows of any kind a validation may take before it is inconclusive.
    validation_window_budget: int = 8
    #: Candidates tried per context before the lifecycle stops proposing.
    attempt_budget: int = 3
    history_limit: int = 8

    def __post_init__(self) -> None:
        for name in (
            "learning_windows",
            "accept_windows",
            "reject_windows",
            "validation_window_budget",
            "attempt_budget",
            "history_limit",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or not 0 < value <= 1000:
                raise ValueError(f"{name} must be a small positive integer")
        if self.validation_window_budget < self.accept_windows:
            raise ValueError("the validation budget cannot be smaller than acceptance")


@dataclass(frozen=True, slots=True)
class OptimizationContext:
    """Everything whose change invalidates evidence gathered under it."""

    preference: ExperienceTarget
    game_version: str
    profile_version: int
    adapter_version: int
    schema_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.preference, ExperienceTarget):
            raise ValueError("context preference is an experience target")
        if not self.game_version or not self.schema_id:
            raise ValueError("a context names its game version and schema")
        for value in (self.profile_version, self.adapter_version):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError("context versions start at 1")

    def changed_fields(self, other: OptimizationContext | None) -> tuple[str, ...]:
        if other is None:
            return ()
        return tuple(
            item.name
            for item in dataclasses.fields(self)
            if getattr(self, item.name) != getattr(other, item.name)
        )


@dataclass(frozen=True, slots=True)
class QueuedPlan:
    """One candidate: which profile, resolved against which plan, if any."""

    candidate_id: str
    preference: ExperienceTarget
    plan: PerformancePlan | None = None

    def __post_init__(self) -> None:
        if not CANDIDATE_ID_RE.fullmatch(self.candidate_id):
            raise ValueError("a candidate id is a short plain identifier")
        if not isinstance(self.preference, ExperienceTarget):
            raise ValueError("a candidate preference is an experience target")


@dataclass(frozen=True, slots=True)
class Attempt:
    candidate_id: str
    outcome: AttemptOutcome
    detail: str = ""


@dataclass(frozen=True, slots=True)
class InFlight:
    """A dispatch that started and has not reported. Persisted before it runs."""

    kind: DispatchKind
    candidate_id: str = ""


@dataclass(frozen=True, slots=True)
class LaneKey:
    steam_app_id: str
    mode: OperatingMode

    def __post_init__(self) -> None:
        if not isinstance(self.steam_app_id, str) or not STEAM_APP_ID_RE.fullmatch(
            self.steam_app_id
        ):
            raise ValueError("a lifecycle needs a Steam app id")
        if self.mode not in MANAGED_MODES:
            raise ValueError("a lifecycle exists only for a known, healthy mode")

    @property
    def identity(self) -> str:
        return f"{self.steam_app_id}.{self.mode.value}"


@dataclass(frozen=True, slots=True)
class GameOptimizationState:
    key: LaneKey
    phase: Phase = Phase.UNKNOWN
    context: OptimizationContext | None = None
    #: The last accepted plan and the context it was accepted under. Kept as
    #: evidence through revalidation; reapplied only while the context holds.
    accepted: QueuedPlan | None = None
    accepted_context: OptimizationContext | None = None
    #: Staged (TESTING_PROFILE) or under validation (VALIDATING).
    candidate: QueuedPlan | None = None
    restore_pending: bool = False
    in_flight: InFlight | None = None
    learning_windows: int = 0
    excluded_windows: int = 0
    meets: int = 0
    below: int = 0
    windows: int = 0
    degraded: int = 0
    attempts_used: int = 0
    history: tuple[Attempt, ...] = ()
    reason: str = ""
    revision: int = 0

    def exhausted(self, policy: LearningPolicy) -> bool:
        return self.attempts_used >= policy.attempt_budget

    def learning_complete(self, policy: LearningPolicy) -> bool:
        return self.learning_windows >= policy.learning_windows


def initial(key: LaneKey) -> GameOptimizationState:
    return GameOptimizationState(key)


def _next(state: GameOptimizationState, **changes) -> GameOptimizationState:
    reason = changes.get("reason", state.reason)
    changes["reason"] = reason[:MAX_REASON]
    return dataclasses.replace(state, revision=state.revision + 1, **changes)


def _record(
    state: GameOptimizationState, policy: LearningPolicy, attempt: Attempt
) -> tuple[Attempt, ...]:
    detail = attempt.detail[:MAX_REASON]
    history = (*state.history, dataclasses.replace(attempt, detail=detail))
    return history[-policy.history_limit :]


def _cancel_candidate(
    state: GameOptimizationState, policy: LearningPolicy, detail: str
) -> dict:
    """Changes that drop the current candidate, remembering that it was dropped."""
    if state.candidate is None:
        return {"candidate": None}
    return {
        "candidate": None,
        "history": _record(
            state, policy, Attempt(state.candidate.candidate_id, AttemptOutcome.CANCELLED, detail)
        ),
    }


_RESET_COUNTERS = {"meets": 0, "below": 0, "windows": 0}


# ---------------------------------------------------------------- intent


def apply_intent(
    state: GameOptimizationState, intent: EffectiveIntent, policy: LearningPolicy
) -> GameOptimizationState:
    """The player's effective intent. Disable dominates everything pending.

    Disabling writes nothing and restores nothing: Restore My Settings stays a
    separate act. Re-enabling returns to UNKNOWN so the next launch reassesses
    from scratch; an accepted plan is reused only if the context still holds,
    and even then the engine's conflict check decides whether it may land.
    """
    if intent.steam_app_id != state.key.steam_app_id:
        raise ValueError("intent is for another game")
    if not intent.automatic:
        if state.phase is Phase.OPTIMIZATION_DISABLED:
            return state
        return _next(
            state,
            phase=Phase.OPTIMIZATION_DISABLED,
            restore_pending=False,
            reason=intent.reason.value,
            **_cancel_candidate(state, policy, intent.reason.value),
            **_RESET_COUNTERS,
        )
    if state.phase is Phase.OPTIMIZATION_DISABLED:
        return _next(state, phase=Phase.UNKNOWN, reason=intent.reason.value)
    return state


def clear_override(state: GameOptimizationState) -> GameOptimizationState:
    """The player explicitly hands a game they edited back to Re-Gear."""
    if state.phase is not Phase.USER_OVERRIDE:
        return state
    return _next(state, phase=Phase.UNKNOWN, reason="player returned the game to automatic")


# --------------------------------------------------------------- support


def assess(
    state: GameOptimizationState,
    tier: SupportTier,
    context: OptimizationContext | None,
    policy: LearningPolicy,
    detail: str = "",
) -> GameOptimizationState:
    """The engine's support decision and the context observed at this launch."""
    if state.phase in DOMINANT:
        return state
    if tier is not SupportTier.MANAGED or context is None:
        phase = Phase.ADVISOR_ONLY if tier is SupportTier.ADVISOR else Phase.UNSUPPORTED
        if state.phase is phase and state.candidate is None:
            return state
        return _next(
            state,
            phase=phase,
            reason=detail or f"support is {tier.value}",
            **_cancel_candidate(state, policy, f"support is {tier.value}"),
            **_RESET_COUNTERS,
        )
    changed = context.changed_fields(state.context)
    if changed:
        # New context: evidence gathered under the old one no longer admits
        # anything. The accepted plan is kept as evidence, never reapplied.
        text = "context changed: " + ", ".join(changed)
        phase = Phase.NEEDS_REVALIDATION if state.accepted is not None else Phase.BASELINE
        return _next(
            state,
            phase=phase,
            context=context,
            learning_windows=0,
            excluded_windows=0,
            degraded=0,
            attempts_used=0,
            reason=text,
            **_cancel_candidate(state, policy, text),
            **_RESET_COUNTERS,
        )
    if state.phase in (Phase.UNKNOWN, Phase.ADVISOR_ONLY, Phase.UNSUPPORTED):
        if state.accepted is not None and state.accepted_context == context:
            phase = Phase.OPTIMIZED_LOCKED
        elif state.accepted is not None:
            phase = Phase.NEEDS_REVALIDATION
        elif state.learning_windows:
            phase = Phase.LEARNING
        else:
            phase = Phase.BASELINE
        return _next(state, phase=phase, context=context, reason="managed support confirmed")
    return state


# ---------------------------------------------------------- observations


def observe(
    state: GameOptimizationState,
    qualified: bool,
    verdict: WindowVerdict,
    policy: LearningPolicy,
) -> GameOptimizationState:
    """One externally assessed observation window from ordinary play."""
    if state.phase in (Phase.BASELINE, Phase.LEARNING):
        if not qualified:
            return _next(state, excluded_windows=state.excluded_windows + 1)
        return _next(
            state, phase=Phase.LEARNING, learning_windows=state.learning_windows + 1
        )
    if state.phase is Phase.VALIDATING:
        return _validate(state, qualified, verdict, policy)
    if state.phase is Phase.OPTIMIZED_LOCKED:
        if not qualified or verdict is WindowVerdict.INCONCLUSIVE:
            return state
        if verdict is WindowVerdict.MEETS_TARGET:
            return state if state.degraded == 0 else _next(state, degraded=0)
        degraded = state.degraded + 1
        if degraded >= policy.reject_windows:
            return _next(
                state,
                phase=Phase.NEEDS_REVALIDATION,
                degraded=0,
                attempts_used=0,
                reason="repeated qualified degradation under the locked plan",
            )
        return _next(state, degraded=degraded)
    return state


def _validate(
    state: GameOptimizationState,
    qualified: bool,
    verdict: WindowVerdict,
    policy: LearningPolicy,
) -> GameOptimizationState:
    assert state.candidate is not None
    meets, below = state.meets, state.below
    if qualified and verdict is WindowVerdict.MEETS_TARGET:
        meets += 1
    elif qualified and verdict is WindowVerdict.BELOW_TARGET:
        below += 1
    windows = state.windows + 1
    candidate = state.candidate
    # Each window moves at most one counter, so the order below only matters
    # for clarity: a rejection is decided the moment it is reached.
    if below >= policy.reject_windows:
        return _abandon(state, policy, AttemptOutcome.REJECTED, "qualified windows fell below target")
    if meets >= policy.accept_windows:
        return _next(
            state,
            phase=Phase.OPTIMIZED_LOCKED,
            accepted=candidate,
            accepted_context=state.context,
            candidate=None,
            degraded=0,
            reason=f"accepted after {meets} qualified windows",
            history=_record(
                state, policy, Attempt(candidate.candidate_id, AttemptOutcome.ACCEPTED)
            ),
            **_RESET_COUNTERS,
        )
    if windows >= policy.validation_window_budget:
        return _abandon(
            state,
            policy,
            AttemptOutcome.INCONCLUSIVE,
            f"no decision within {policy.validation_window_budget} windows",
        )
    return _next(state, meets=meets, below=below, windows=windows)


def _abandon(
    state: GameOptimizationState,
    policy: LearningPolicy,
    outcome: AttemptOutcome,
    detail: str,
) -> GameOptimizationState:
    """A written candidate failed validation: put the original back next launch."""
    assert state.candidate is not None
    return _next(
        state,
        phase=Phase.LEARNING,
        candidate=None,
        restore_pending=True,
        reason=detail,
        history=_record(state, policy, Attempt(state.candidate.candidate_id, outcome, detail)),
        **_RESET_COUNTERS,
    )


# ------------------------------------------------------------ candidates


@dataclass(frozen=True, slots=True)
class Proposal:
    state: GameOptimizationState
    staged: bool
    reason: str = ""


def propose(
    state: GameOptimizationState, candidate: QueuedPlan, policy: LearningPolicy
) -> Proposal:
    """Stage one candidate for the next launch, if the lifecycle allows one."""
    if state.phase not in (Phase.LEARNING, Phase.NEEDS_REVALIDATION):
        return Proposal(state, False, f"no candidate is accepted in {state.phase.value}")
    if state.context is None or candidate.preference is not state.context.preference:
        return Proposal(state, False, "the candidate is for another preference")
    if state.restore_pending:
        return Proposal(state, False, "the original must be restored before another candidate")
    if state.phase is Phase.LEARNING and not state.learning_complete(policy):
        return Proposal(state, False, "not enough qualified windows of ordinary play yet")
    if state.exhausted(policy):
        return Proposal(
            state,
            False,
            f"attempt budget of {policy.attempt_budget} is spent for this context; "
            "keeping the current settings",
        )
    staged = _next(
        state,
        phase=Phase.TESTING_PROFILE,
        candidate=candidate,
        attempts_used=state.attempts_used + 1,
        reason=f"candidate {candidate.candidate_id} staged for the next launch",
        **_RESET_COUNTERS,
    )
    return Proposal(staged, True)


# -------------------------------------------------------------- dispatch


def next_dispatch(state: GameOptimizationState) -> InFlight | None:
    """What the next launch should do for this lane, if anything."""
    if state.in_flight is not None or state.phase in DOMINANT:
        return None
    if state.restore_pending:
        return InFlight(DispatchKind.RESTORE_ORIGINAL)
    # While validating, every launch re-dispatches the candidate as a check:
    # the engine answers ALREADY_MATCHES while it is intact and CONFLICT once
    # the player has changed it, so windows never judge the player's settings.
    if state.phase in (Phase.TESTING_PROFILE, Phase.VALIDATING) and state.candidate is not None:
        return InFlight(DispatchKind.APPLY_CANDIDATE, state.candidate.candidate_id)
    if (
        state.phase is Phase.OPTIMIZED_LOCKED
        and state.accepted is not None
        and state.accepted_context == state.context
    ):
        return InFlight(DispatchKind.REAPPLY_ACCEPTED, state.accepted.candidate_id)
    return None


def begin_dispatch(state: GameOptimizationState, dispatch: InFlight) -> GameOptimizationState:
    """Mark a dispatch in flight. Must be durably saved before the write starts."""
    if next_dispatch(state) != dispatch:
        raise ValueError("that dispatch is not the one this lifecycle is due")
    return _next(state, in_flight=dispatch)


def finish_dispatch(
    state: GameOptimizationState,
    result: DispatchResult,
    policy: LearningPolicy,
    detail: str = "",
) -> GameOptimizationState:
    """Record the engine's answer for the dispatch in flight."""
    dispatch = state.in_flight
    if dispatch is None:
        raise ValueError("no dispatch is in flight")
    cleared = dataclasses.replace(state, in_flight=None)
    if result is DispatchResult.DEFERRED:
        return _next(cleared, reason=detail or "game was running; retried next launch")
    if result is DispatchResult.CONFLICT:
        return player_edited(cleared, policy, detail or "the player changed the settings")
    if result in (DispatchResult.ADVISOR, DispatchResult.UNSUPPORTED):
        tier = SupportTier.ADVISOR if result is DispatchResult.ADVISOR else SupportTier.UNKNOWN
        after = assess(cleared, tier, cleared.context, policy, detail)
        return _next(cleared) if after is cleared else after
    if dispatch.kind is DispatchKind.RESTORE_ORIGINAL:
        if result is DispatchResult.LANDED:
            return _next(cleared, restore_pending=False, reason="original settings restored")
        return _next(cleared, reason=detail or "restore did not complete; retried next launch")
    if dispatch.kind is DispatchKind.REAPPLY_ACCEPTED:
        return _next(cleared, reason=detail or f"accepted plan {result.value}")
    assert state.candidate is not None
    if state.phase is Phase.VALIDATING:
        # A verification: the evidence so far stands if the candidate is intact,
        # and a failed check writes nothing, so it neither counts nor restores.
        return _next(cleared, reason=detail or f"candidate check: {result.value}")
    if result is DispatchResult.LANDED:
        return _next(
            cleared,
            phase=Phase.VALIDATING,
            reason=f"candidate {state.candidate.candidate_id} applied; validating",
            **_RESET_COUNTERS,
        )
    # NOT_APPLIED: nothing of ours landed, so there is nothing to validate or
    # restore. The attempt still counts against the budget.
    phase = Phase.NEEDS_REVALIDATION if state.accepted is not None else Phase.LEARNING
    return _next(
        cleared,
        phase=phase,
        candidate=None,
        reason=detail or "candidate could not be applied",
        history=_record(
            state,
            policy,
            Attempt(state.candidate.candidate_id, AttemptOutcome.NOT_APPLIED, detail),
        ),
    )


def player_edited(
    state: GameOptimizationState, policy: LearningPolicy, detail: str
) -> GameOptimizationState:
    """The player's edit wins. Nothing pending survives, nothing is restored."""
    history = state.history
    if state.candidate is not None:
        history = _record(
            state, policy, Attempt(state.candidate.candidate_id, AttemptOutcome.CONFLICT, detail)
        )
    return _next(
        state,
        phase=Phase.USER_OVERRIDE,
        candidate=None,
        restore_pending=False,
        in_flight=None,
        history=history,
        reason=detail,
        **_RESET_COUNTERS,
    )


def recover(state: GameOptimizationState, policy: LearningPolicy) -> GameOptimizationState:
    """Reopen after a crash. An in-flight write is uncertain and never replayed.

    Whether its bytes landed is the engine's provenance to answer, not this
    record's to assume, so the lifecycle neither validates nor restores on the
    strength of it: it asks for revalidation and counts the attempt.
    """
    dispatch = state.in_flight
    if dispatch is None:
        return state
    detail = f"{dispatch.kind.value} was interrupted; not replayed"
    history = _record(
        state, policy, Attempt(dispatch.candidate_id or "-", AttemptOutcome.UNCERTAIN, detail)
    )
    if dispatch.kind is DispatchKind.RESTORE_ORIGINAL:
        # Restoring is idempotent and returns the player's own bytes; it stays
        # due, and the engine's conflict check still guards it.
        return _next(state, in_flight=None, history=history, reason=detail)
    phase = state.phase
    if phase in (Phase.TESTING_PROFILE, Phase.VALIDATING, Phase.OPTIMIZED_LOCKED):
        phase = Phase.NEEDS_REVALIDATION
    return _next(
        state,
        phase=phase,
        in_flight=None,
        candidate=None,
        history=history,
        reason=detail,
        **_RESET_COUNTERS,
    )
