"""The Game Profile Engine: Steam game + mode + preference -> game settings.

    game identified -> mode supplied -> profile resolved -> support decided
        -> (Managed) translated to keys -> foundation apply/verify/restore
        -> (Advisor) plain-language recommendations, nothing written
        -> (running) request kept for next launch, nothing written

This module is orchestration only. Everything that touches a file -- locating
the configuration, backups, provenance, atomic writes, conflict detection,
restoration -- is the accepted graphics-profile foundation, used unchanged.
The engine adds the layer above it: per-mode semantic profiles, game
mappings, version-aware support levels, and the performance-plan intake.

It consumes mode; it never observes or changes it. It consumes a resolved
performance plan; it never resolves one, and never knows which provider, if
any, will generate frames. And, like everything under it, it never raises at
its caller: a profile that cannot be applied is an outcome, never the reason
a game fails to launch.
"""

from __future__ import annotations

import dataclasses
import stat
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping

from ..domain.graphics_profiles import GraphicsProfile, SupportTier
from ..domain.graphics_schema import GameSchema
from ..domain.mode_profiles import ExperienceTarget
from ..domain.models import OperatingMode
from ..domain.performance_plan import FrameGenerationRef, PerformancePlan
from ..domain.semantic_profiles import (
    GameMapping,
    GameProfileDocument,
    SupportDecision,
    decide_support,
)
from .graphics_backup import BackupManager
from .graphics_config_locator import GraphicsConfigLocator
from .graphics_config_store import GraphicsConfigStore
from .graphics_management_state import ManagementRecord, ManagementStateStore
from .graphics_profile_service import (
    ApplyOutcome,
    ApplyResult,
    GameRunState,
    GraphicsProfileService,
    ManagedKeyCatalog,
    RestoreOutcome,
    RestoreResult,
)


class EngineResult(StrEnum):
    APPLIED = "game_profile.applied"
    ALREADY_MATCHES = "game_profile.already_matches"
    ADVISOR = "game_profile.advisor"
    UNKNOWN = "game_profile.unknown"
    QUEUED_NEXT_LAUNCH = "game_profile.queued_next_launch"
    CONFLICT = "game_profile.conflict"
    NOT_LOCATED = "game_profile.not_located"
    ROLLED_BACK = "game_profile.rolled_back"
    FAILED = "game_profile.failed"


@dataclass(frozen=True, slots=True)
class NextLaunchRequest:
    """What to resolve again when the game is next launched.

    Carries the request, not a computed plan: context may have changed by
    then, so the profile is resolved afresh rather than replayed. Persisting
    it is left to a later slice; here it is returned to the caller.
    """

    steam_app_id: str
    mode: OperatingMode
    preference: ExperienceTarget
    plan: PerformancePlan | None = None


@dataclass(frozen=True, slots=True)
class EngineOutcome:
    result: EngineResult
    support: SupportTier
    detail: str = ""
    reasons: tuple[str, ...] = ()
    recommendations: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()
    next_launch: NextLaunchRequest | None = None
    #: Passed through untouched for whoever launches the game. The engine
    #: applied only the plan's real-frame cap; it never interprets this.
    frame_generation: FrameGenerationRef | None = None
    apply_outcome: ApplyOutcome | None = None
    #: The plan in the player's terms, including a selected rate below the
    #: request and the display it will be shown on. Informational only: the
    #: engine writes none of it beyond the game-owned settings.
    plan_notes: tuple[str, ...] = ()

    @property
    def wrote(self) -> bool:
        return self.result is EngineResult.APPLIED


@dataclass(frozen=True, slots=True)
class ProfileRegistry:
    """The profiles, mappings and schemas this build knows. Supplied, fixed."""

    documents: Mapping[str, GameProfileDocument] = field(default_factory=dict)
    mappings: Mapping[str, GameMapping] = field(default_factory=dict)
    schemas: Mapping[str, GameSchema] = field(default_factory=dict)

    def document(self, steam_app_id: str) -> GameProfileDocument | None:
        return self.documents.get(steam_app_id)

    def mapping_for(self, document: GameProfileDocument | None) -> GameMapping | None:
        return self.mappings.get(document.mapping_id) if document is not None else None


class GameProfileEngine:
    def __init__(
        self,
        locator: GraphicsConfigLocator,
        backups: BackupManager,
        management: ManagementStateStore,
        registry: ProfileRegistry,
        store: GraphicsConfigStore | None = None,
        allow_fixture_profiles: bool = False,
    ) -> None:
        self._locator = locator
        self._backups = backups
        self._management = management
        self._registry = registry
        self._store = store
        self._allow_fixture = allow_fixture_profiles

    def decide(
        self,
        steam_app_id: str,
        mode: OperatingMode,
        preference: ExperienceTarget,
        observed_game_version: str | None,
        plan: PerformancePlan | None = None,
    ) -> SupportDecision:
        """The support level and profile for a request. Pure; writes nothing."""
        document = self._registry.document(steam_app_id)
        mapping = self._registry.mapping_for(document)
        semantic = None
        if document is not None and plan is not None:
            base = document.profile(mode, preference)
            semantic = plan.apply_to(base) if base is not None else None
        return decide_support(
            document,
            mapping,
            mode,
            preference,
            observed_game_version,
            self._allow_fixture,
            semantic,
        )

    def apply(
        self,
        steam_app_id: str,
        mode: OperatingMode,
        preference: ExperienceTarget,
        run_state: GameRunState,
        observed_game_version: str | None,
        plan: PerformancePlan | None = None,
    ) -> EngineOutcome:
        """Resolve and, only if Managed, apply. Raises nothing."""
        try:
            outcome = self._apply(
                steam_app_id, mode, preference, run_state, observed_game_version, plan
            )
            if plan is None:
                return outcome
            return dataclasses.replace(outcome, plan_notes=plan.explain())
        except Exception as error:  # noqa: BLE001 - the launch must survive anything
            return EngineOutcome(
                EngineResult.FAILED,
                SupportTier.UNKNOWN,
                f"unexpected failure contained: {error!r}",
            )

    def _apply(
        self,
        steam_app_id: str,
        mode: OperatingMode,
        preference: ExperienceTarget,
        run_state: GameRunState,
        observed_game_version: str | None,
        plan: PerformancePlan | None,
    ) -> EngineOutcome:
        passthrough = plan.frame_generation if plan is not None else None
        # A running or ambiguous game keeps its settings. A mode change during
        # play is honoured at the next launch, resolved afresh then.
        if run_state is not GameRunState.NOT_RUNNING:
            return EngineOutcome(
                EngineResult.QUEUED_NEXT_LAUNCH,
                SupportTier.UNKNOWN,
                f"game state is {run_state.value}; settings are not changed during play",
                next_launch=NextLaunchRequest(steam_app_id, mode, preference, plan),
                frame_generation=passthrough,
            )
        decision = self.decide(steam_app_id, mode, preference, observed_game_version, plan)
        if decision.tier is SupportTier.UNKNOWN:
            return EngineOutcome(
                EngineResult.UNKNOWN, SupportTier.UNKNOWN, reasons=decision.reasons,
                frame_generation=passthrough,
            )
        if not decision.managed:
            return EngineOutcome(
                EngineResult.ADVISOR,
                SupportTier.ADVISOR,
                reasons=decision.reasons,
                recommendations=decision.recommendations,
                frame_generation=passthrough,
            )
        document = self._registry.document(steam_app_id)
        mapping = self._registry.mapping_for(document)
        assert document is not None and mapping is not None
        assert decision.graphics_profile is not None
        service = self._service(steam_app_id, mapping)
        locked = self._read_only(service, decision.graphics_profile, mapping.relative_dir)
        if locked is not None:
            return EngineOutcome(
                EngineResult.ADVISOR,
                SupportTier.ADVISOR,
                locked,
                reasons=(locked,),
                recommendations=decision.recommendations,
                frame_generation=passthrough,
            )
        outcome = service.apply(decision.graphics_profile, mapping.relative_dir, run_state)
        return self._translate(outcome, decision, passthrough)

    @staticmethod
    def _read_only(
        service: GraphicsProfileService, profile: GraphicsProfile, relative_dir: str
    ) -> str | None:
        """Respect a configuration the player locked read-only.

        An atomic replace would succeed regardless -- it replaces the directory
        entry and never opens the file for writing -- so the foundation cannot
        see this. Players lock config files precisely to stop anything from
        changing them, so a locked file is advice, not a target.
        """
        located = service.discover(profile, relative_dir)
        if located.location is None:
            return None  # The foundation reports not-located itself.
        try:
            mode = located.location.config_path.stat().st_mode
        except OSError:
            return None  # Unreadable is the foundation's failure to report.
        if not mode & stat.S_IWUSR:
            return (
                "the configuration file is read-only; it may have been locked on "
                "purpose, so Re-Gear recommends settings instead of replacing it"
            )
        return None

    def restore(
        self,
        steam_app_id: str,
        run_state: GameRunState,
        accept_player_edits: bool = False,
    ) -> RestoreOutcome:
        """Restore My Settings through the foundation, unchanged."""
        located = self._locating(steam_app_id)
        if located is None:
            return RestoreOutcome(RestoreResult.FAILED, "no mapping locates this game")
        service, profile, relative_dir = located
        return service.restore(
            profile, relative_dir, run_state, accept_player_edits=accept_player_edits
        )

    def stop_managing(self, steam_app_id: str) -> ManagementRecord | None:
        located = self._locating(steam_app_id)
        if located is None:
            return None
        service, profile, relative_dir = located
        return service.stop_managing(profile, relative_dir)

    def _translate(
        self,
        outcome: ApplyOutcome,
        decision: SupportDecision,
        passthrough: FrameGenerationRef | None,
    ) -> EngineOutcome:
        advice = decision.recommendations
        mapping = {
            ApplyResult.APPLIED: (EngineResult.APPLIED, SupportTier.MANAGED),
            ApplyResult.ALREADY_MATCHES: (EngineResult.ALREADY_MATCHES, SupportTier.MANAGED),
            # The file no longer looks like what the mapping was written for:
            # a game update, most likely. Managed falls back to Advisor, and
            # the player still gets the recommendation in plain terms.
            ApplyResult.UNSUPPORTED: (EngineResult.ADVISOR, SupportTier.ADVISOR),
            ApplyResult.ADVISOR: (EngineResult.ADVISOR, SupportTier.ADVISOR),
            ApplyResult.CONFLICT: (EngineResult.CONFLICT, SupportTier.MANAGED),
            ApplyResult.DEFERRED: (EngineResult.QUEUED_NEXT_LAUNCH, SupportTier.MANAGED),
            ApplyResult.NOT_LOCATED: (EngineResult.NOT_LOCATED, SupportTier.UNKNOWN),
            ApplyResult.ROLLED_BACK: (EngineResult.ROLLED_BACK, SupportTier.MANAGED),
            ApplyResult.FAILED: (EngineResult.FAILED, SupportTier.MANAGED),
        }
        result, tier = mapping[outcome.result]
        return EngineOutcome(
            result,
            tier,
            outcome.detail,
            reasons=decision.reasons,
            recommendations=advice,
            changed=outcome.changed,
            frame_generation=passthrough,
            apply_outcome=outcome,
        )

    def _service(self, steam_app_id: str, mapping: GameMapping) -> GraphicsProfileService:
        schema = self._registry.schemas.get(mapping.schema_id)
        catalog = ManagedKeyCatalog(
            {steam_app_id: mapping.managed_keys()},
            {steam_app_id: schema} if schema is not None else {},
            {steam_app_id: (self._document_version(steam_app_id),)},
        )
        return GraphicsProfileService(
            self._locator, self._backups, catalog, self._management, self._store
        )

    def _document_version(self, steam_app_id: str) -> int:
        document = self._registry.document(steam_app_id)
        return document.metadata.profile_version if document is not None else 1

    def _locating(
        self, steam_app_id: str
    ) -> tuple[GraphicsProfileService, GraphicsProfile, str] | None:
        document = self._registry.document(steam_app_id)
        mapping = self._registry.mapping_for(document)
        if document is None or mapping is None:
            return None
        keys = mapping.managed_keys()
        if not keys:
            return None
        # The foundation locates a file through a profile; restore and stop
        # only use its identity and filename. The single placeholder setting
        # below is never written.
        locator_profile = GraphicsProfile(
            steam_app_id=steam_app_id,
            mode=OperatingMode.PORTABLE,
            config_filename=mapping.config_filename,
            settings={next(iter(sorted(keys))): ""},
            profile_version=document.metadata.profile_version,
            schema_id=mapping.schema_id,
        )
        return self._service(steam_app_id, mapping), locator_profile, mapping.relative_dir
