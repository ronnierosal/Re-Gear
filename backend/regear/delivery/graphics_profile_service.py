"""The per-game graphics profile sequence, and the only place that writes.

discover -> read -> validate -> backup -> apply -> verify -> restore.

Two rules shape every path through this module.

A game's configuration is only ever rewritten while the game is not running,
and "not running" has to be asserted by the caller from real evidence. An
unknown run state refuses, because rewriting a file a running game has open
loses whatever it writes at exit and can leave it unreadable.

Nothing here raises at its caller. A profile that cannot be applied is an
outcome value, never an exception, so a failed profile application can never be
the reason a game does not launch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Mapping

from ..domain.graphics_config_format import (
    ConfigFormatError,
    adapter_for,
    unmanaged_remainder,
)
from ..domain.graphics_profiles import (
    GraphicsProfile,
    ManagedKey,
    SupportTier,
    plan_application,
    verify_application,
)
from ..domain.models import OperatingMode
from .graphics_backup import BackupError, BackupManager, BackupRecord, digest_of
from .graphics_config_locator import GraphicsConfigLocator, LocationOutcome
from .graphics_config_store import ConfigIoError, GraphicsConfigStore


class GameRunState(StrEnum):
    """What the caller knows about the game right now."""

    RUNNING = "running"
    NOT_RUNNING = "not_running"
    UNKNOWN = "unknown"


class ApplyResult(StrEnum):
    APPLIED = "graphics_profile.applied"
    ALREADY_MATCHES = "graphics_profile.already_matches"
    ADVISOR = "graphics_profile.advisor"
    REFUSED_GAME_RUNNING = "graphics_profile.refused_game_running"
    REFUSED_RUN_STATE_UNKNOWN = "graphics_profile.refused_run_state_unknown"
    NOT_LOCATED = "graphics_profile.not_located"
    FAILED = "graphics_profile.failed"
    ROLLED_BACK = "graphics_profile.rolled_back"


class RestoreResult(StrEnum):
    RESTORED = "graphics_profile.restored"
    NOTHING_TO_RESTORE = "graphics_profile.nothing_to_restore"
    REFUSED_GAME_RUNNING = "graphics_profile.restore_refused_game_running"
    FAILED = "graphics_profile.restore_failed"


@dataclass(frozen=True, slots=True)
class ApplyOutcome:
    result: ApplyResult
    detail: str = ""
    tier: SupportTier | None = None
    changed: tuple[str, ...] = ()
    advice: tuple[str, ...] = ()
    backup: BackupRecord | None = None
    before_digest: str | None = None
    after_digest: str | None = None

    @property
    def wrote(self) -> bool:
        return self.result is ApplyResult.APPLIED


@dataclass(frozen=True, slots=True)
class RestoreOutcome:
    result: RestoreResult
    detail: str = ""
    backup: BackupRecord | None = None
    byte_identical: bool = False


@dataclass(frozen=True, slots=True)
class ManagedKeyCatalog:
    """The keys Re-Gear is permitted to rewrite, per game."""

    by_app: Mapping[str, Mapping[str, ManagedKey]] = field(default_factory=dict)

    def for_app(self, steam_app_id: str) -> Mapping[str, ManagedKey]:
        return self.by_app.get(steam_app_id, {})


class GraphicsProfileService:
    """Apply, verify and restore one game's graphics profile."""

    def __init__(
        self,
        locator: GraphicsConfigLocator,
        backups: BackupManager,
        catalog: ManagedKeyCatalog,
        store: GraphicsConfigStore | None = None,
    ) -> None:
        self._locator = locator
        self._backups = backups
        self._catalog = catalog
        self._store = store or GraphicsConfigStore()

    def discover(
        self, profile: GraphicsProfile, relative_dir: str
    ) -> LocationOutcome:
        """Locate the configuration this profile describes. Read-only."""
        return self._locator.locate(
            profile.steam_app_id, profile.config_filename, profile.mode, relative_dir
        )

    def apply(
        self,
        profile: GraphicsProfile,
        relative_dir: str,
        run_state: GameRunState,
    ) -> ApplyOutcome:
        """Run the whole sequence for one profile, raising nothing."""
        if run_state is GameRunState.RUNNING:
            return ApplyOutcome(
                ApplyResult.REFUSED_GAME_RUNNING,
                "the game is running; its settings are not rewritten underneath it",
            )
        if run_state is not GameRunState.NOT_RUNNING:
            return ApplyOutcome(
                ApplyResult.REFUSED_RUN_STATE_UNKNOWN,
                "the game's run state is unknown, which fails closed",
            )
        located = self.discover(profile, relative_dir)
        if located.location is None:
            problem = located.problem.value if located.problem else "unknown"
            return ApplyOutcome(ApplyResult.NOT_LOCATED, f"{problem}: {located.detail}")
        location = located.location
        adapter = adapter_for(location.config_path.name)
        if adapter is None:
            return self._advisor(
                "no adapter reads this configuration format",
                (f"Adjust {location.config_path.name} in the game's own settings.",),
            )
        try:
            current = self._store.read(location.config_path)
        except ConfigIoError as error:
            return ApplyOutcome(ApplyResult.FAILED, str(error))
        try:
            document = adapter.parse(current.text)
        except ConfigFormatError as error:
            return self._advisor(
                error.detail,
                (
                    f"Re-Gear does not understand {location.config_path.name} well "
                    "enough to edit it safely; change these settings in the game.",
                ),
            )
        managed = self._catalog.for_app(profile.steam_app_id)
        plan = plan_application(document, profile, managed)
        if plan.tier is SupportTier.ADVISOR:
            return self._advisor(
                "; ".join(f"{key}:{refusal.value}" for key, refusal in plan.refusals),
                plan.advice,
            )
        before_digest = digest_of(current.payload)
        if not plan.changes:
            return ApplyOutcome(
                ApplyResult.ALREADY_MATCHES,
                "every managed key already holds the profile's value",
                tier=SupportTier.MANAGED,
                before_digest=before_digest,
                after_digest=before_digest,
            )
        before_remainder = unmanaged_remainder(document, profile.managed_addresses)
        try:
            backup = self._backups.capture(
                location.identity, location.config_path, profile.mode.value
            )
        except (BackupError, ValueError) as error:
            # No backup, no write. A change we could not undo is not a change
            # this milestone is allowed to make.
            return ApplyOutcome(ApplyResult.FAILED, f"backup refused: {error}")
        try:
            rendered = adapter.render(document.with_values(plan.changes))
            written = self._store.write(location.config_path, rendered)
        except (ConfigIoError, KeyError, ValueError) as error:
            return self._rollback(
                backup, location.config_path, f"write failed: {error}", before_digest
            )
        try:
            reread = self._store.read(location.config_path)
            verified_document = adapter.parse(reread.text)
        except (ConfigIoError, ConfigFormatError) as error:
            return self._rollback(
                backup,
                location.config_path,
                f"verification could not re-read the file: {error}",
                before_digest,
            )
        ok, problems = verify_application(verified_document, profile, before_remainder)
        if not ok or reread.payload != written:
            detail = "; ".join(problems) or "the file on disk is not what was written"
            return self._rollback(backup, location.config_path, detail, before_digest)
        return ApplyOutcome(
            ApplyResult.APPLIED,
            "",
            tier=SupportTier.MANAGED,
            changed=tuple(sorted(plan.changes)),
            backup=backup,
            before_digest=before_digest,
            after_digest=digest_of(reread.payload),
        )

    def restore(
        self,
        profile: GraphicsProfile,
        relative_dir: str,
        run_state: GameRunState,
        record: BackupRecord | None = None,
    ) -> RestoreOutcome:
        """Put back the most recent backup, byte-for-byte."""
        if run_state is not GameRunState.NOT_RUNNING:
            return RestoreOutcome(
                RestoreResult.REFUSED_GAME_RUNNING,
                "restoring requires the game to be known not running",
            )
        located = self.discover(profile, relative_dir)
        if located.location is None:
            problem = located.problem.value if located.problem else "unknown"
            return RestoreOutcome(RestoreResult.FAILED, f"{problem}: {located.detail}")
        location = located.location
        chosen = record or self._backups.latest(location.identity)
        if chosen is None:
            return RestoreOutcome(RestoreResult.NOTHING_TO_RESTORE)
        try:
            identical = self._backups.restore(chosen, location.config_path)
        except (BackupError, ValueError) as error:
            return RestoreOutcome(RestoreResult.FAILED, str(error), backup=chosen)
        if not identical:
            return RestoreOutcome(
                RestoreResult.FAILED,
                "the restored file does not match the backed-up bytes",
                backup=chosen,
            )
        return RestoreOutcome(RestoreResult.RESTORED, backup=chosen, byte_identical=True)

    def backups_for(self, profile: GraphicsProfile, relative_dir: str) -> tuple[BackupRecord, ...]:
        located = self.discover(profile, relative_dir)
        if located.location is None:
            return ()
        return self._backups.records(located.location.identity)

    @staticmethod
    def _advisor(detail: str, advice: tuple[str, ...]) -> ApplyOutcome:
        return ApplyOutcome(
            ApplyResult.ADVISOR, detail, tier=SupportTier.ADVISOR, advice=advice
        )

    def _rollback(
        self,
        backup: BackupRecord,
        path: Path,
        detail: str,
        before_digest: str,
    ) -> ApplyOutcome:
        """Undo a write that did not verify, and say whether the undo held."""
        try:
            identical = self._backups.restore(backup, path)
        except (BackupError, ValueError) as error:
            return ApplyOutcome(
                ApplyResult.FAILED,
                f"{detail}; rollback also failed: {error}",
                backup=backup,
                before_digest=before_digest,
            )
        suffix = "" if identical else "; rollback did not reproduce the original bytes"
        return ApplyOutcome(
            ApplyResult.ROLLED_BACK if identical else ApplyResult.FAILED,
            detail + suffix,
            backup=backup,
            before_digest=before_digest,
            after_digest=before_digest if identical else None,
        )


def mode_of(value: str) -> OperatingMode:
    """Parse a mode name, defaulting nothing: unknown stays unknown."""
    try:
        return OperatingMode(value)
    except ValueError:
        return OperatingMode.UNKNOWN
