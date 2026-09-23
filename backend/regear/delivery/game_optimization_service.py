"""Automatic game optimization, composed over the Game Profile Engine.

    player intent (stored) ─┐
    lifecycle (stored, per game x mode) ─┼─> prepare_launch ─> engine apply/restore
    catalog (admitted for this mode) ─┘         │
                                                └─> lifecycle records the answer

The engine still does everything that touches a game's file: locating it,
backups, provenance, conflict detection, atomic writes and restore. This layer
decides only *whether* this launch should ask the engine for anything, and
*which* plan -- the staged candidate, the accepted plan, or the player's
original -- and records what the engine said. It adds no second writer and
no second conflict rule.

Nothing here is wired to a caller. There is no launch hook, telemetry
collector, Auto TDP control or UI: observation verdicts and candidates arrive
through ``record_window`` and ``propose`` from whoever owns them.

``prepare_launch`` never raises and never blocks: every path returns an
outcome whose ``may_launch`` is True. A write happens only after the lifecycle
has durably marked it in flight, so a crash mid-write is found on reopen and
treated as uncertain rather than replayed.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable, Mapping

from ..domain.game_optimization_preferences import (
    EffectiveIntent,
    GamePreference,
    OptimizationPreferences,
    resolve_intent,
)
from ..domain.game_optimization_state import (
    MANAGED_MODES,
    DispatchKind,
    DispatchResult,
    GameOptimizationState,
    InFlight,
    LaneKey,
    LearningPolicy,
    OptimizationContext,
    Phase,
    QueuedPlan,
    WindowVerdict,
    apply_intent,
    assess,
    begin_dispatch,
    clear_override,
    finish_dispatch,
    initial,
    next_dispatch,
    observe,
    player_edited,
    propose,
    recover,
)
from ..domain.graphics_schema import GameSchema
from ..domain.mode_profiles import ExperienceTarget
from ..domain.models import OperatingMode
from ..domain.performance_plan import FrameGenerationRef
from ..domain.semantic_profiles import GameMapping
from .game_optimization_store import (
    GameOptimizationStore,
    LoadState,
    StoreError,
)
from .game_profile_catalog import CatalogLoad
from .game_profile_engine import EngineOutcome, EngineResult, GameProfileEngine, ProfileRegistry
from .graphics_profile_service import GameRunState, RestoreOutcome, RestoreResult


class LaunchAction(StrEnum):
    #: Nothing asked of the engine: automatic management is off, withheld,
    #: or has nothing due for this launch.
    PASSTHROUGH = "optimization.passthrough"
    APPLIED_CANDIDATE = "optimization.applied_candidate"
    REAPPLIED_ACCEPTED = "optimization.reapplied_accepted"
    RESTORED_ORIGINAL = "optimization.restored_original"
    #: A dispatch was due and did not land; the lifecycle recorded why.
    NOT_LANDED = "optimization.not_landed"


@dataclass(frozen=True, slots=True)
class LaunchPreparation:
    action: LaunchAction
    phase: Phase | None = None
    reasons: tuple[str, ...] = ()
    engine: EngineOutcome | None = None
    restore: RestoreOutcome | None = None
    #: Passed through untouched for whoever launches the game.
    frame_generation: FrameGenerationRef | None = None

    @property
    def may_launch(self) -> bool:
        # A profile that cannot be applied is an outcome, never a reason a
        # game fails to start. There is no other value.
        return True


@dataclass(frozen=True, slots=True)
class ServiceOutcome:
    ok: bool
    detail: str = ""
    state: GameOptimizationState | None = None


EngineFactory = Callable[[ProfileRegistry], GameProfileEngine]


@dataclass(frozen=True, slots=True)
class ReviewedAdapters:
    """Reviewed in-code mappings and schemas. Catalog entries point at these."""

    mappings: Mapping[str, GameMapping] = field(default_factory=dict)
    schemas: Mapping[str, GameSchema] = field(default_factory=dict)


_ENGINE_TO_DISPATCH = {
    EngineResult.APPLIED: DispatchResult.LANDED,
    EngineResult.ALREADY_MATCHES: DispatchResult.LANDED,
    EngineResult.ADVISOR: DispatchResult.ADVISOR,
    EngineResult.UNKNOWN: DispatchResult.UNSUPPORTED,
    EngineResult.QUEUED_NEXT_LAUNCH: DispatchResult.DEFERRED,
    EngineResult.CONFLICT: DispatchResult.CONFLICT,
    EngineResult.NOT_LOCATED: DispatchResult.NOT_APPLIED,
    EngineResult.ROLLED_BACK: DispatchResult.NOT_APPLIED,
    EngineResult.FAILED: DispatchResult.NOT_APPLIED,
}
_RESTORE_TO_DISPATCH = {
    RestoreResult.RESTORED: DispatchResult.LANDED,
    # Nothing Re-Gear wrote is left to take back: the original is in place.
    RestoreResult.NOTHING_TO_RESTORE: DispatchResult.LANDED,
    RestoreResult.CONFLICT: DispatchResult.CONFLICT,
    RestoreResult.DEFERRED: DispatchResult.DEFERRED,
    RestoreResult.FAILED: DispatchResult.NOT_APPLIED,
}


class GameOptimizationService:
    def __init__(
        self,
        store: GameOptimizationStore,
        catalog: CatalogLoad,
        adapters: ReviewedAdapters,
        engine_factory: EngineFactory,
        policy: LearningPolicy | None = None,
    ) -> None:
        self._store = store
        self._catalog = catalog
        self._adapters = adapters
        self._engine_factory = engine_factory
        self._policy = policy or LearningPolicy()
        self._lock = threading.Lock()

    # ------------------------------------------------------------ intent

    def intent(self, steam_app_id: str) -> EffectiveIntent:
        lookup = self._store.load_preferences()
        return resolve_intent(self._preferences(lookup), steam_app_id)

    def set_global(self, enabled: bool) -> ServiceOutcome:
        return self._change_preferences(lambda current: current.with_global(enabled), None)

    def set_default_preference(self, preference: ExperienceTarget) -> ServiceOutcome:
        return self._change_preferences(
            lambda current: current.with_default_preference(preference), None
        )

    def set_game(self, steam_app_id: str, preference: GamePreference) -> ServiceOutcome:
        return self._change_preferences(
            lambda current: current.with_game(steam_app_id, preference), steam_app_id
        )

    def reset_untrusted_preferences(self) -> ServiceOutcome:
        """Explicitly replace unreadable preferences with the opted-out default."""
        with self._lock:
            lookup = self._store.load_preferences()
            if lookup.state is not LoadState.UNTRUSTED:
                return ServiceOutcome(False, "preferences are not untrusted")
            try:
                if not self._store.quarantine_preferences():
                    return ServiceOutcome(False, "preferences changed while resetting")
            except StoreError as error:
                return ServiceOutcome(False, str(error))
            return ServiceOutcome(True, "preferences reset to the opted-out default")

    def _change_preferences(self, change, steam_app_id: str | None) -> ServiceOutcome:
        with self._lock:
            lookup = self._store.load_preferences()
            if lookup.state is LoadState.UNTRUSTED:
                return ServiceOutcome(
                    False, f"stored preferences are untrusted ({lookup.detail}); reset them first"
                )
            current = lookup.value or OptimizationPreferences()
            try:
                updated = change(current)
                self._store.save_preferences(updated, current.revision)
            except (StoreError, ValueError) as error:
                return ServiceOutcome(False, str(error))
            # Disabling must cancel pending work now, not at the next launch
            # of each game: a queued candidate would otherwise still read as
            # pending wherever it is shown.
            for key in self._store.lanes():
                if steam_app_id is None or key.steam_app_id == steam_app_id:
                    self._update_lane(
                        key,
                        lambda state: apply_intent(
                            state, resolve_intent(updated, key.steam_app_id), self._policy
                        ),
                    )
            return ServiceOutcome(True, "preferences saved")

    @staticmethod
    def _preferences(lookup) -> OptimizationPreferences | None:
        if lookup.state is LoadState.ABSENT:
            return OptimizationPreferences()
        return lookup.value if lookup.trusted else None

    # ---------------------------------------------------------- lifecycle

    def state(self, steam_app_id: str, mode: OperatingMode):
        return self._store.load_state(LaneKey(steam_app_id, mode))

    def record_window(
        self, steam_app_id: str, mode: OperatingMode, qualified: bool, verdict: WindowVerdict
    ) -> ServiceOutcome:
        with self._lock:
            return self._update_lane(
                LaneKey(steam_app_id, mode),
                lambda state: observe(state, qualified, verdict, self._policy),
            )

    def propose(
        self, steam_app_id: str, mode: OperatingMode, candidate: QueuedPlan
    ) -> ServiceOutcome:
        with self._lock:
            key = LaneKey(steam_app_id, mode)
            loaded = self._load_lane(key)
            if isinstance(loaded, ServiceOutcome):
                return loaded
            state, revision = loaded
            proposal = propose(state, candidate, self._policy)
            if not proposal.staged:
                return ServiceOutcome(False, proposal.reason, state)
            return self._save(proposal.state, revision)

    def resume_automatic(self, steam_app_id: str, mode: OperatingMode) -> ServiceOutcome:
        """The player hands an edited game back. The engine's conflict rules still apply."""
        with self._lock:
            return self._update_lane(LaneKey(steam_app_id, mode), clear_override)

    def reset_untrusted_lane(self, steam_app_id: str, mode: OperatingMode) -> ServiceOutcome:
        """Explicit resolution for an unreadable lifecycle: move it aside, start over."""
        with self._lock:
            try:
                moved = self._store.quarantine(LaneKey(steam_app_id, mode))
            except StoreError as error:
                return ServiceOutcome(False, str(error))
            if not moved:
                return ServiceOutcome(False, "the lifecycle record is not untrusted")
            return ServiceOutcome(True, "untrusted lifecycle moved aside")

    def restore_original(
        self, steam_app_id: str, mode: OperatingMode, run_state: GameRunState
    ) -> RestoreOutcome:
        """Restore My Settings. Explicit; the game then belongs to the player."""
        with self._lock:
            engine = self._engine(mode)
            outcome = engine.restore(steam_app_id, run_state)
            if outcome.result is RestoreResult.RESTORED:
                self._update_lane(
                    LaneKey(steam_app_id, mode),
                    lambda state: player_edited(
                        state, self._policy, "the player restored their original settings"
                    ),
                )
            return outcome

    # -------------------------------------------------------------- launch

    def prepare_launch(
        self,
        steam_app_id: str,
        mode: OperatingMode,
        run_state: GameRunState,
        observed_game_version: str | None,
    ) -> LaunchPreparation:
        """Everything automatic optimization does before a game starts. Raises nothing."""
        try:
            with self._lock:
                return self._prepare(steam_app_id, mode, run_state, observed_game_version)
        except Exception as error:  # noqa: BLE001 - the launch must survive anything
            return LaunchPreparation(
                LaunchAction.PASSTHROUGH, reasons=(f"unexpected failure contained: {error!r}",)
            )

    def _prepare(
        self,
        steam_app_id: str,
        mode: OperatingMode,
        run_state: GameRunState,
        observed_game_version: str | None,
    ) -> LaunchPreparation:
        if mode not in MANAGED_MODES:
            return LaunchPreparation(
                LaunchAction.PASSTHROUGH,
                reasons=(f"mode is {mode.value}; automatic changes are withheld",),
            )
        intent = self.intent(steam_app_id)
        key = LaneKey(steam_app_id, mode)
        loaded = self._load_lane(key)
        if isinstance(loaded, ServiceOutcome):
            return LaunchPreparation(LaunchAction.PASSTHROUGH, reasons=(loaded.detail,))
        state, revision = loaded
        if not intent.automatic and revision == 0:
            # Never managed and not wanted: leave no record behind.
            return LaunchPreparation(LaunchAction.PASSTHROUGH, reasons=(intent.reason.value,))
        state = recover(state, self._policy)
        state = apply_intent(state, intent, self._policy)
        if intent.automatic:
            engine = self._engine(mode)
            decision = engine.decide(steam_app_id, mode, intent.preference, observed_game_version)
            context = self._context(steam_app_id, intent.preference, observed_game_version)
            state = assess(
                state, decision.tier, context, self._policy, "; ".join(decision.reasons)
            )
        dispatch = next_dispatch(state)
        if dispatch is None or run_state is not GameRunState.NOT_RUNNING:
            reasons = (state.reason,) if state.reason else ()
            if dispatch is not None:
                reasons = (f"game state is {run_state.value}; nothing is changed during play",)
            saved = self._persist(state, revision)
            if saved is not None:
                reasons = (*reasons, saved)
            return LaunchPreparation(LaunchAction.PASSTHROUGH, state.phase, reasons)
        # Mark the write in flight durably *before* it happens. If this save
        # fails, nothing is written: an unrecorded write is the one thing the
        # lifecycle could never reconcile.
        marked = begin_dispatch(state, dispatch)
        failure = self._persist(marked, revision)
        if failure is not None:
            return LaunchPreparation(LaunchAction.PASSTHROUGH, state.phase, (failure,))
        return self._dispatch(marked, dispatch, mode, run_state, observed_game_version)

    def _dispatch(
        self,
        state: GameOptimizationState,
        dispatch: InFlight,
        mode: OperatingMode,
        run_state: GameRunState,
        observed_game_version: str | None,
    ) -> LaunchPreparation:
        app_id = state.key.steam_app_id
        engine = self._engine(mode)
        engine_outcome = restore_outcome = None
        if dispatch.kind is DispatchKind.RESTORE_ORIGINAL:
            restore_outcome = engine.restore(app_id, run_state)
            result = _RESTORE_TO_DISPATCH[restore_outcome.result]
            detail = restore_outcome.detail
            action = LaunchAction.RESTORED_ORIGINAL
        else:
            queued = state.candidate if dispatch.kind is DispatchKind.APPLY_CANDIDATE else state.accepted
            assert queued is not None
            engine_outcome = engine.apply(
                app_id, mode, queued.preference, run_state, observed_game_version, queued.plan
            )
            result = _ENGINE_TO_DISPATCH[engine_outcome.result]
            detail = engine_outcome.detail or "; ".join(engine_outcome.reasons)
            action = (
                LaunchAction.APPLIED_CANDIDATE
                if dispatch.kind is DispatchKind.APPLY_CANDIDATE
                else LaunchAction.REAPPLIED_ACCEPTED
            )
        if result is not DispatchResult.LANDED:
            action = LaunchAction.NOT_LANDED
        finished = finish_dispatch(state, result, self._policy, detail)
        # If this save fails the in-flight mark stays on disk, and the next
        # open treats the write as uncertain. That is the intended fallback.
        failure = self._persist(finished, state.revision)
        reasons = (finished.reason,) + ((failure,) if failure else ())
        return LaunchPreparation(
            action,
            finished.phase,
            reasons,
            engine=engine_outcome,
            restore=restore_outcome,
            frame_generation=engine_outcome.frame_generation if engine_outcome else None,
        )

    # ------------------------------------------------------------ helpers

    def _engine(self, mode: OperatingMode) -> GameProfileEngine:
        documents = {}
        for app_id, entry in self._catalog.entries.items():
            document, _ = entry.admitted(mode)
            documents[app_id] = document
        registry = ProfileRegistry(documents, self._adapters.mappings, self._adapters.schemas)
        return self._engine_factory(registry)

    def _context(
        self, steam_app_id: str, preference: ExperienceTarget, observed_game_version: str | None
    ) -> OptimizationContext | None:
        entry = self._catalog.entries.get(steam_app_id)
        if entry is None or not observed_game_version:
            return None
        mapping = self._adapters.mappings.get(entry.document.mapping_id)
        if mapping is None:
            return None
        return OptimizationContext(
            preference,
            observed_game_version,
            entry.document.metadata.profile_version,
            mapping.adapter_version,
            mapping.schema_id,
        )

    def _load_lane(self, key: LaneKey):
        lookup = self._store.load_state(key)
        if lookup.state is LoadState.UNTRUSTED:
            return ServiceOutcome(
                False,
                f"lifecycle record is untrusted ({lookup.detail}); nothing is changed "
                "until it is explicitly reset",
            )
        if lookup.value is None:
            return initial(key), 0
        return lookup.value, lookup.value.revision

    def _update_lane(self, key: LaneKey, change) -> ServiceOutcome:
        loaded = self._load_lane(key)
        if isinstance(loaded, ServiceOutcome):
            return loaded
        state, revision = loaded
        return self._save(change(state), revision)

    def _save(self, state: GameOptimizationState, revision: int) -> ServiceOutcome:
        failure = self._persist(state, revision)
        if failure is not None:
            return ServiceOutcome(False, failure, state)
        return ServiceOutcome(True, state.reason, state)

    def _persist(self, state: GameOptimizationState, revision: int) -> str | None:
        if state.revision == revision:
            return None  # Unchanged; nothing to write.
        try:
            self._store.save_state(state, revision)
        except StoreError as error:
            return f"lifecycle state was not saved: {error}"
        return None
