"""The per-game graphics profile sequence, and the only place that writes.

discover -> read -> validate schema -> check provenance -> backup -> apply ->
verify -> restore.

Four rules shape every path through this module.

A game's configuration is only ever rewritten while the game is not running,
and "not running" has to be asserted by the caller from real evidence. An
unknown run state defers, because rewriting a file a running game has open
loses whatever it writes at exit and can leave it unreadable.

Re-Gear only replaces bytes it can prove it wrote. Every managed write records
the digest of exactly what it left on disk; if the file no longer matches, the
player edited it, and their newer choice wins -- on apply and on restore alike.
There is no silent rebaseline.

A file whose schema and version are not ones an adapter was written against is
Unknown. Unknown advises and writes nothing.

Nothing here raises at its caller. Every filesystem failure becomes an outcome
value, so a failed profile application can never be the reason a game does not
launch. `prepare_for_launch` is the entry point that makes that testable.
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
from ..domain.graphics_schema import GameSchema, SchemaAssessment, SchemaVerdict
from ..domain.models import OperatingMode
from .graphics_backup import BackupError, BackupManager, BackupRecord, digest_of
from .graphics_config_locator import GraphicsConfigLocator, LocationOutcome
from .graphics_config_store import ConfigIoError, GraphicsConfigStore
from .graphics_management_state import (
    ManagementRecord,
    ManagementStateError,
    ManagementStateStore,
)


class GameRunState(StrEnum):
    """What the caller knows about the game right now."""

    RUNNING = "running"
    NOT_RUNNING = "not_running"
    UNKNOWN = "unknown"


class ApplyResult(StrEnum):
    APPLIED = "graphics_profile.applied"
    ALREADY_MATCHES = "graphics_profile.already_matches"
    ADVISOR = "graphics_profile.advisor"
    UNSUPPORTED = "graphics_profile.unsupported"
    CONFLICT = "graphics_profile.conflict"
    DEFERRED = "graphics_profile.deferred"
    NOT_LOCATED = "graphics_profile.not_located"
    FAILED = "graphics_profile.failed"
    ROLLED_BACK = "graphics_profile.rolled_back"


class RestoreResult(StrEnum):
    RESTORED = "graphics_profile.restored"
    NOTHING_TO_RESTORE = "graphics_profile.nothing_to_restore"
    CONFLICT = "graphics_profile.restore_conflict"
    DEFERRED = "graphics_profile.restore_deferred"
    FAILED = "graphics_profile.restore_failed"


class LaunchDecision(StrEnum):
    """Whether the game may start. There is exactly one value."""

    ALLOWED = "graphics_profile.launch_allowed"


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
    restoration_available: bool = False

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
class LaunchOutcome:
    """What a pre-launch profile attempt did, and whether play may proceed."""

    decision: LaunchDecision
    apply_outcome: ApplyOutcome

    @property
    def may_launch(self) -> bool:
        return self.decision is LaunchDecision.ALLOWED


@dataclass(frozen=True, slots=True)
class ManagedKeyCatalog:
    """The keys Re-Gear may rewrite and the schema each game is supported at."""

    by_app: Mapping[str, Mapping[str, ManagedKey]] = field(default_factory=dict)
    schemas: Mapping[str, GameSchema] = field(default_factory=dict)

    def for_app(self, steam_app_id: str) -> Mapping[str, ManagedKey]:
        return self.by_app.get(steam_app_id, {})

    def schema_for(self, steam_app_id: str) -> GameSchema | None:
        return self.schemas.get(steam_app_id)


class GraphicsProfileService:
    """Apply, verify and restore one game's graphics profile."""

    def __init__(
        self,
        locator: GraphicsConfigLocator,
        backups: BackupManager,
        catalog: ManagedKeyCatalog,
        management: ManagementStateStore,
        store: GraphicsConfigStore | None = None,
    ) -> None:
        self._locator = locator
        self._backups = backups
        self._catalog = catalog
        self._management = management
        self._store = store or GraphicsConfigStore()

    # -- discovery -------------------------------------------------------

    def discover(self, profile: GraphicsProfile, relative_dir: str) -> LocationOutcome:
        """Locate the configuration this profile describes. Read-only."""
        try:
            return self._locator.locate(
                profile.steam_app_id, profile.config_filename, profile.mode, relative_dir
            )
        except OSError as error:  # pragma: no cover - defensive
            return LocationOutcome(None, None, f"discovery failed: {error}")

    # -- the launch boundary --------------------------------------------

    def prepare_for_launch(
        self, profile: GraphicsProfile, relative_dir: str, run_state: GameRunState
    ) -> LaunchOutcome:
        """Attempt a profile before a launch. Always allows the launch.

        This is the caller-visible contract, and the only one worth testing for
        "a failed profile never blocks play": whatever `apply` returns, and
        whatever the filesystem does underneath it, this returns ALLOWED.
        """
        try:
            outcome = self.apply(profile, relative_dir, run_state)
        except Exception as error:  # noqa: BLE001 - the launch must survive anything
            outcome = ApplyOutcome(
                ApplyResult.FAILED, f"unexpected failure contained: {error!r}"
            )
        return LaunchOutcome(LaunchDecision.ALLOWED, outcome)

    # -- apply -----------------------------------------------------------

    def apply(
        self, profile: GraphicsProfile, relative_dir: str, run_state: GameRunState
    ) -> ApplyOutcome:
        """Run the whole sequence for one profile, raising nothing."""
        if run_state is GameRunState.RUNNING:
            return ApplyOutcome(
                ApplyResult.DEFERRED,
                "the game is running; its settings are not rewritten underneath it, "
                "and this mode becomes available at its next launch",
            )
        if run_state is not GameRunState.NOT_RUNNING:
            return ApplyOutcome(
                ApplyResult.DEFERRED,
                "the game's run state is unknown, which fails closed",
            )
        located = self.discover(profile, relative_dir)
        if located.location is None:
            problem = located.problem.value if located.problem else "unknown"
            return ApplyOutcome(ApplyResult.NOT_LOCATED, f"{problem}: {located.detail}")
        location = located.location
        adapter = adapter_for(location.config_path.name)
        if adapter is None:
            return self._unsupported(
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
            return self._unsupported(
                error.detail,
                (
                    f"Re-Gear does not understand {location.config_path.name} well "
                    "enough to edit it safely; change these settings in the game.",
                ),
            )
        schema = self._catalog.schema_for(profile.steam_app_id)
        # No schema registered is the same evidence position as a schema that
        # did not match: Re-Gear has not been written against this file.
        assessment = (
            schema.assess(document)
            if schema is not None
            else SchemaAssessment(
                SchemaVerdict.VERSION_ABSENT,
                "no supported schema is registered for this game",
            )
        )
        managed = self._catalog.for_app(profile.steam_app_id)
        plan = plan_application(document, profile, managed, assessment)
        if plan.tier is SupportTier.UNKNOWN:
            return self._unsupported(assessment.detail or "schema unrecognised", plan.advice)
        if plan.tier is SupportTier.ADVISOR:
            return ApplyOutcome(
                ApplyResult.ADVISOR,
                "; ".join(f"{key}:{refusal.value}" for key, refusal in plan.refusals),
                tier=SupportTier.ADVISOR,
                advice=plan.advice,
                restoration_available=self._baseline_available(location.identity),
            )
        before_digest = digest_of(current.payload)

        # Provenance, before anything is written: are these Re-Gear's bytes?
        provenance = self._management.load(location.identity)
        conflict = self._conflict(provenance, before_digest, location.identity)
        if conflict is not None:
            return conflict

        if not plan.changes:
            return ApplyOutcome(
                ApplyResult.ALREADY_MATCHES,
                "every managed key already holds the profile's value",
                tier=SupportTier.MANAGED,
                before_digest=before_digest,
                after_digest=before_digest,
                restoration_available=self._baseline_available(location.identity),
            )
        before_remainder = unmanaged_remainder(document, profile.managed_addresses)
        try:
            backup = self._backups.capture(
                location.identity, location.config_path, profile.mode.value
            )
        except (BackupError, ValueError, OSError) as error:
            # No backup, no write. A change we could not undo is not a change
            # this milestone is allowed to make.
            return ApplyOutcome(ApplyResult.FAILED, f"backup refused: {error}")
        try:
            rendered = adapter.render(document.with_values(plan.changes))
            written = self._store.write(location.config_path, rendered)
        except (ConfigIoError, KeyError, ValueError, OSError) as error:
            return self._rollback(
                backup, location.config_path, f"write failed: {error}", before_digest
            )
        try:
            reread = self._store.read(location.config_path)
            verified_document = adapter.parse(reread.text)
        except (ConfigIoError, ConfigFormatError, OSError) as error:
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

        after_digest = digest_of(reread.payload)
        baseline = self._baseline_for(location.identity, backup)
        try:
            self._management.save(
                ManagementRecord(
                    identity=location.identity,
                    target_path=str(location.config_path),
                    managed_digest=after_digest,
                    baseline_payload_name=baseline.payload_name if baseline else "",
                    baseline_digest=baseline.digest if baseline else "",
                    mode=profile.mode.value,
                    profile_version=profile.profile_version,
                    schema_id=profile.schema_id or (schema.schema_id if schema else ""),
                    schema_version=assessment.observed_version or "",
                    schema_signature=assessment.signature,
                )
            )
        except (ManagementStateError, ValueError, OSError) as error:
            # A write we cannot record is a write we could not later tell from
            # a player's own edit, so it is undone rather than left unattributed.
            return self._rollback(
                backup,
                location.config_path,
                f"management state could not be recorded: {error}",
                before_digest,
            )
        return ApplyOutcome(
            ApplyResult.APPLIED,
            "",
            tier=SupportTier.MANAGED,
            changed=tuple(sorted(plan.changes)),
            backup=backup,
            before_digest=before_digest,
            after_digest=after_digest,
            restoration_available=baseline is not None,
        )

    # -- restore ---------------------------------------------------------

    def restore(
        self,
        profile: GraphicsProfile,
        relative_dir: str,
        run_state: GameRunState,
        record: BackupRecord | None = None,
        accept_player_edits: bool = False,
    ) -> RestoreOutcome:
        """Restore My Settings: put the pre-management original back.

        The default is the pinned baseline, not the newest backup: a player
        asking for their settings back means the ones they had before Re-Gear,
        not the profile Re-Gear wrote last time. A file that no longer matches
        what Re-Gear wrote is a conflict, and restoring over it would discard
        the player's newer edit -- so it refuses unless the caller explicitly
        says the player chose to discard them.
        """
        if run_state is not GameRunState.NOT_RUNNING:
            return RestoreOutcome(
                RestoreResult.DEFERRED,
                "restoring requires the game to be known not running",
            )
        located = self.discover(profile, relative_dir)
        if located.location is None:
            problem = located.problem.value if located.problem else "unknown"
            return RestoreOutcome(RestoreResult.FAILED, f"{problem}: {located.detail}")
        location = located.location
        try:
            chosen = record or self._backups.baseline(location.identity)
        except (BackupError, ValueError, OSError) as error:
            return RestoreOutcome(RestoreResult.FAILED, str(error))
        if chosen is None:
            return RestoreOutcome(RestoreResult.NOTHING_TO_RESTORE)
        if chosen.identity != location.identity or chosen.source_path != str(
            location.config_path
        ):
            return RestoreOutcome(
                RestoreResult.FAILED,
                "the chosen backup does not belong to this configuration file",
                backup=chosen,
            )
        if not accept_player_edits:
            try:
                current = self._store.read(location.config_path)
            except (ConfigIoError, OSError) as error:
                return RestoreOutcome(RestoreResult.FAILED, str(error), backup=chosen)
            provenance = self._management.load(location.identity)
            conflict = self._conflict(
                provenance, digest_of(current.payload), location.identity
            )
            if conflict is not None:
                return RestoreOutcome(
                    RestoreResult.CONFLICT,
                    conflict.detail,
                    backup=chosen,
                )
        try:
            identical = self._backups.restore(chosen, location.config_path)
        except (BackupError, ValueError, OSError) as error:
            return RestoreOutcome(RestoreResult.FAILED, str(error), backup=chosen)
        if not identical:
            return RestoreOutcome(
                RestoreResult.FAILED,
                "the restored file does not match the backed-up bytes",
                backup=chosen,
            )
        try:
            self._management.forget(location.identity)
        except (ManagementStateError, ValueError, OSError) as error:
            # The bytes are the player's again; a stale record would only make
            # the next apply think it wrote them.
            return RestoreOutcome(
                RestoreResult.FAILED,
                f"restored, but the management record could not be cleared: {error}",
                backup=chosen,
                byte_identical=True,
            )
        return RestoreOutcome(RestoreResult.RESTORED, backup=chosen, byte_identical=True)

    def stop_managing(
        self, profile: GraphicsProfile, relative_dir: str
    ) -> ManagementRecord | None:
        """Stop claiming authorship without touching the file.

        Opt-out and restore are separate acts: this leaves the current settings
        exactly as they are, keeps the baseline, and makes the next apply treat
        the file as the player's.
        """
        located = self.discover(profile, relative_dir)
        if located.location is None:
            return None
        try:
            return self._management.stop_managing(located.location.identity)
        except (ManagementStateError, ValueError, OSError):
            return None

    def backups_for(
        self, profile: GraphicsProfile, relative_dir: str
    ) -> tuple[BackupRecord, ...]:
        located = self.discover(profile, relative_dir)
        if located.location is None:
            return ()
        try:
            return self._backups.records(located.location.identity)
        except (BackupError, ValueError, OSError):
            return ()

    # -- internals -------------------------------------------------------

    def _conflict(
        self,
        provenance: ManagementRecord | None,
        current_digest: str,
        identity: str,
    ) -> ApplyOutcome | None:
        """Refuse when the bytes on disk are not the ones Re-Gear last wrote."""
        if provenance is None:
            return None  # Never managed: the file is the player's baseline.
        if not provenance.managing:
            return ApplyOutcome(
                ApplyResult.CONFLICT,
                "Re-Gear was asked to stop managing this configuration",
                restoration_available=self._baseline_available(identity),
            )
        if provenance.managed_digest != current_digest:
            return ApplyOutcome(
                ApplyResult.CONFLICT,
                "the configuration changed since Re-Gear last wrote it; the "
                "player's newer settings are kept",
                restoration_available=self._baseline_available(identity),
            )
        return None

    def _baseline_for(self, identity: str, fallback: BackupRecord) -> BackupRecord | None:
        try:
            return self._backups.baseline(identity) or (
                fallback if fallback.baseline else None
            )
        except (BackupError, ValueError, OSError):
            return None

    def _baseline_available(self, identity: str) -> bool:
        try:
            return self._backups.baseline(identity) is not None
        except (BackupError, ValueError, OSError):
            return False

    @staticmethod
    def _unsupported(detail: str, advice: tuple[str, ...]) -> ApplyOutcome:
        return ApplyOutcome(
            ApplyResult.UNSUPPORTED, detail, tier=SupportTier.UNKNOWN, advice=advice
        )

    def _rollback(
        self, backup: BackupRecord, path: Path, detail: str, before_digest: str
    ) -> ApplyOutcome:
        """Undo a write that did not verify, and say whether the undo held.

        The rollback is itself guarded: the bytes on disk must still be the
        ones this attempt wrote. If something else changed the file in between,
        writing a now-stale backup over it would destroy that change, so the
        failure is reported without a rollback instead.
        """
        try:
            current = self._store.read(path)
        except (ConfigIoError, OSError):
            current = None
        if current is not None and digest_of(current.payload) == before_digest:
            return ApplyOutcome(
                ApplyResult.ROLLED_BACK,
                detail + "; the file was already unchanged",
                backup=backup,
                before_digest=before_digest,
                after_digest=before_digest,
            )
        try:
            identical = self._backups.restore(backup, path)
        except (BackupError, ValueError, OSError) as error:
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
