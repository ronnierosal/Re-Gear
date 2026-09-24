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

import dataclasses
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
from .graphics_backup import (
    BackupChangedError,
    BackupError,
    BackupManager,
    BackupRecord,
    BaselineState,
    digest_of,
)
from .graphics_config_locator import GraphicsConfigLocator, LocationOutcome
from .graphics_config_store import (
    ConfigChangedError,
    ConfigIoError,
    GraphicsConfigStore,
)
from .graphics_management_state import (
    Lifecycle,
    ManagementLookup,
    ManagementRecord,
    ManagementState,
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


class OriginalEvidence(StrEnum):
    """What a restore established about the bytes it put back.

    Deliberately not a boolean defaulting to True. The previous field claimed
    an enrolled original had been restored on every path that restored nothing
    at all, and inferred originalness from *missing* provenance -- the same
    claim-by-default mistake the binding check exists to prevent. This starts
    at NOT_ESTABLISHED and is only ever raised by positive evidence.
    """

    #: Nothing was restored, or nothing proves what was.
    NOT_ESTABLISHED = "graphics_profile.original_not_established"
    #: Restored, verified, and matching the digest this target was enrolled with.
    ENROLLED_ORIGINAL = "graphics_profile.enrolled_original"
    #: Restored, but knowably not the enrolled original: an explicitly chosen
    #: older backup, or a recovery performed without usable provenance.
    HISTORICAL_UNVERIFIED = "graphics_profile.historical_unverified"


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
    #: What this outcome actually establishes about the restored bytes. Starts
    #: at NOT_ESTABLISHED, including on every failed, deferred and
    #: nothing-to-restore path, because those restored nothing to describe.
    original_evidence: OriginalEvidence = OriginalEvidence.NOT_ESTABLISHED

    @property
    def restored_enrolled_original(self) -> bool:
        """True only where the enrolled original was proven to be back."""
        return self.original_evidence is OriginalEvidence.ENROLLED_ORIGINAL


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
    #: Profile versions this build accepts per game. A version number being a
    #: positive integer says nothing about whether this build understands it.
    profile_versions: Mapping[str, tuple[int, ...]] = field(default_factory=dict)

    def for_app(self, steam_app_id: str) -> Mapping[str, ManagedKey]:
        return self.by_app.get(steam_app_id, {})

    def schema_for(self, steam_app_id: str) -> GameSchema | None:
        return self.schemas.get(steam_app_id)

    def accepts_profile_version(self, steam_app_id: str, version: int) -> bool:
        return version in self.profile_versions.get(steam_app_id, (1,))


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
        # The profile must be the one this catalog's adapter was written for.
        # A profile carrying another schema's id, or a version this build does
        # not accept, is not evidence about this file -- recording it after the
        # fact is not the same as admitting it beforehand.
        binding = self._binding_refusal(profile, schema)
        if binding is not None:
            return binding
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
        lookup = self._management.load(location.identity)
        conflict = self._conflict(lookup, before_digest, location.identity)
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
            baseline_state = self._backups.baseline(location.identity)
        except (BackupError, ValueError, OSError) as error:
            return ApplyOutcome(ApplyResult.FAILED, f"backup store is unusable: {error}")
        baseline_refusal = self._baseline_refusal(baseline_state, lookup)
        if baseline_refusal is not None:
            return baseline_refusal
        try:
            backup = self._backups.capture(
                location.identity, location.config_path, profile.mode.value
            )
        except (BackupError, ValueError, OSError) as error:
            # No backup, no write. A change we could not undo is not a change
            # this milestone is allowed to make.
            return ApplyOutcome(ApplyResult.FAILED, f"backup refused: {error}")
        baseline = self._baseline_record(location.identity, backup)
        # Built before the write so that a rollback can record its own outcome
        # even on a first enrollment, where no record exists yet to transition.
        template = ManagementRecord(
            identity=location.identity,
            target_path=str(location.config_path),
            managed_digest=before_digest,
            baseline_payload_name=baseline.payload_name if baseline else "",
            baseline_digest=baseline.digest if baseline else "",
            mode=profile.mode.value,
            profile_version=profile.profile_version,
            schema_id=profile.schema_id or (schema.schema_id if schema else ""),
            schema_version=assessment.observed_version or "",
            schema_signature=assessment.signature,
        )
        written: bytes | None = None
        try:
            rendered = adapter.render(document.with_values(plan.changes))
            # The bytes read at the top are carried all the way down: the store
            # re-reads the target immediately before replacing it, so work done
            # in between (backup, render) cannot mask a change that arrived
            # meanwhile.
            written = self._store.write(
                location.config_path, rendered, expected=current.payload
            )
        except ConfigChangedError as error:
            # Nothing was replaced, so there is nothing to roll back.
            return ApplyOutcome(
                ApplyResult.CONFLICT,
                str(error),
                before_digest=before_digest,
                after_digest=before_digest,
                backup=backup,
                restoration_available=baseline_state.verified or backup.baseline,
            )
        except (ConfigIoError, KeyError, ValueError, OSError) as error:
            return self._rollback(
                backup, location.config_path, f"write failed: {error}", before_digest,
                None, template,
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
                digest_of(written),
                template,
            )
        ok, problems = verify_application(verified_document, profile, before_remainder)
        if not ok or reread.payload != written:
            detail = "; ".join(problems) or "the file on disk is not what was written"
            return self._rollback(
                backup, location.config_path, detail, before_digest,
                digest_of(written), template,
            )

        after_digest = digest_of(reread.payload)
        try:
            self._management.save(
                dataclasses.replace(template, managed_digest=after_digest)
            )
        except (ManagementStateError, ValueError, OSError) as error:
            # A write we cannot record is a write we could not later tell from
            # a player's own edit, so it is undone rather than left unattributed.
            return self._rollback(
                backup,
                location.config_path,
                f"management state could not be recorded: {error}",
                before_digest,
                after_digest,
                template,
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
            baseline_state = self._backups.baseline(location.identity)
        except (BackupError, ValueError, OSError) as error:
            return RestoreOutcome(RestoreResult.FAILED, str(error))
        if record is None and not baseline_state.verified:
            if baseline_state.state is BaselineState.NONE:
                return RestoreOutcome(RestoreResult.NOTHING_TO_RESTORE)
            return RestoreOutcome(
                RestoreResult.FAILED,
                baseline_state.detail or baseline_state.state.value,
                backup=baseline_state.record,
            )
        chosen = record or baseline_state.record
        if chosen is None:
            return RestoreOutcome(RestoreResult.NOTHING_TO_RESTORE)
        enrolled = self._management.load(location.identity).record
        if record is None:
            # Restore My Settings claims to return the player's own settings,
            # so the baseline must be the one this target was enrolled with.
            # A discard-edits flag authorises discarding edits; it does not
            # authorise silently redefining what "the original" means, so this
            # check is deliberately outside that branch.
            problem = self._binding_problem(baseline_state, enrolled)
            if problem is not None:
                return RestoreOutcome(
                    RestoreResult.FAILED,
                    f"refusing to restore: {problem}, so Re-Gear cannot produce "
                    "the settings this configuration was enrolled with",
                    backup=baseline_state.record,
                )
        if chosen.identity != location.identity or chosen.source_path != str(
            location.config_path
        ):
            return RestoreOutcome(
                RestoreResult.FAILED,
                "the chosen backup does not belong to this configuration file",
                backup=chosen,
            )
        try:
            current = self._store.read(location.config_path)
        except (ConfigIoError, OSError) as error:
            return RestoreOutcome(RestoreResult.FAILED, str(error), backup=chosen)
        if not accept_player_edits:
            # Restoring needs proof of authorship, and "the record is gone" is
            # not proof. Only a trusted record whose digest matches the file
            # permits an unattended restore.
            lookup = self._management.load(location.identity)
            conflict = self._conflict(
                lookup, digest_of(current.payload), location.identity
            )
            if conflict is not None:
                return RestoreOutcome(
                    RestoreResult.CONFLICT, conflict.detail, backup=chosen
                )
            if not lookup.trusted:
                return RestoreOutcome(
                    RestoreResult.CONFLICT,
                    "Re-Gear cannot prove it wrote the current settings, so they "
                    "are kept; restoring anyway is an explicit choice",
                    backup=chosen,
                )
        try:
            identical = self._backups.restore(
                chosen, location.config_path, expected=current.payload
            )
        except BackupChangedError as error:
            return RestoreOutcome(RestoreResult.CONFLICT, str(error), backup=chosen)
        except (BackupError, ValueError, OSError) as error:
            return RestoreOutcome(RestoreResult.FAILED, str(error), backup=chosen)
        if not identical:
            return RestoreOutcome(
                RestoreResult.FAILED,
                "the restored file does not match the backed-up bytes",
                backup=chosen,
            )
        try:
            # Not forgotten: a completed restore is a known outcome, and the
            # digest of what it left is what lets the next apply re-enroll
            # instead of reading a missing record as lost evidence.
            self._management.settle(
                location.identity, Lifecycle.RESTORED, chosen.digest
            )
        except (ManagementStateError, ValueError, OSError) as error:
            return RestoreOutcome(
                RestoreResult.FAILED,
                f"restored, but the management record could not be updated: {error}",
                backup=chosen,
                byte_identical=True,
            )
        # Positive evidence only: a successful, verified restore of a record
        # whose digest matches a trusted enrollment. Missing provenance, an
        # empty enrolled digest and an explicitly chosen older backup are all
        # absence of proof, and are reported as such.
        proven = (
            record is None
            and enrolled is not None
            and bool(enrolled.baseline_digest)
            and chosen.digest == enrolled.baseline_digest
        )
        evidence = (
            OriginalEvidence.ENROLLED_ORIGINAL
            if proven
            else OriginalEvidence.HISTORICAL_UNVERIFIED
        )
        detail = (
            ""
            if proven
            else (
                "restored a backup this session cannot match to the settings "
                "this configuration was enrolled with; treat it as a historical "
                "recovery, not as Restore My Settings"
            )
        )
        return RestoreOutcome(
            RestoreResult.RESTORED,
            detail,
            backup=chosen,
            byte_identical=True,
            original_evidence=evidence,
        )

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

    def resume_managing(
        self, profile: GraphicsProfile, relative_dir: str
    ) -> ManagementRecord | None:
        """Re-enroll a target the player opted out of. Explicit, never inferred."""
        located = self.discover(profile, relative_dir)
        if located.location is None:
            return None
        try:
            return self._management.resume_managing(located.location.identity)
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
        lookup: ManagementLookup,
        current_digest: str,
        identity: str,
    ) -> ApplyOutcome | None:
        """Refuse when the bytes on disk are not provably Re-Gear's.

        The three provenance states are not interchangeable. ABSENT is a first
        enrollment only when the backup history agrees that nothing was ever
        managed here; an absent record beside existing backups means the record
        was lost, which is untrusted, not new. UNTRUSTED is always a conflict:
        something was recorded and can no longer be believed, and deleting or
        corrupting a file must never become a way to license an overwrite.
        """
        available = self._baseline_available(identity)
        if lookup.state is ManagementState.ABSENT:
            if not self._has_history(identity):
                return None  # Genuinely new target: first enrollment proceeds.
            return ApplyOutcome(
                ApplyResult.CONFLICT,
                "this configuration has been managed before but its management "
                "record is missing, so the current settings are not provably "
                "Re-Gear's and are kept",
                restoration_available=available,
            )
        if lookup.state is ManagementState.UNTRUSTED:
            return ApplyOutcome(
                ApplyResult.CONFLICT,
                f"the management record cannot be trusted ({lookup.detail}), so "
                "the current settings are kept",
                restoration_available=available,
            )
        record = lookup.record
        assert record is not None
        if record.lifecycle is Lifecycle.STOPPED:
            return ApplyOutcome(
                ApplyResult.CONFLICT,
                "Re-Gear was asked to stop managing this configuration; resuming "
                "is an explicit choice",
                restoration_available=available,
            )
        if record.settled:
            # A completed rollback or restore left the file with the player and
            # said exactly what it left. If those bytes are still there, nothing
            # is in doubt and this is a re-enrollment, not a conflict.
            if record.managed_digest == current_digest:
                return None
            return ApplyOutcome(
                ApplyResult.CONFLICT,
                "the configuration changed after Re-Gear handed it back; the "
                "player's newer settings are kept",
                restoration_available=available,
            )
        if record.managed_digest != current_digest:
            return ApplyOutcome(
                ApplyResult.CONFLICT,
                "the configuration changed since Re-Gear last wrote it; the "
                "player's newer settings are kept",
                restoration_available=available,
            )
        return None

    @staticmethod
    def _binding_problem(baseline_state, record: ManagementRecord | None) -> str | None:
        """Why the stored original is not the one this target was enrolled with.

        Shared by apply and restore on purpose. These two checks drifted apart
        once already: apply refused a replaced original while Restore My
        Settings happily handed the replacement back as the player's own
        settings, which is the more damaging half of the same bug.
        """
        if record is None or not record.baseline_digest:
            return None
        if baseline_state.state is BaselineState.NONE:
            return (
                "this configuration has been managed before and its recorded "
                "original is no longer in the backup store"
            )
        if baseline_state.state in (BaselineState.CORRUPT, BaselineState.LOST):
            return baseline_state.detail or baseline_state.state.value
        if (
            baseline_state.record is not None
            and baseline_state.record.digest != record.baseline_digest
        ):
            return "the stored original is not the one this target was enrolled with"
        return None

    def _baseline_refusal(
        self, baseline_state, lookup: ManagementLookup
    ) -> ApplyOutcome | None:
        """Refuse a managed write whose original could not be produced again.

        Backup metadata alone is not the whole evidence. A target whose
        management record names a baseline is a target that *has* one, so an
        empty backup directory there is a lost original rather than a first
        enrollment -- and letting capture label the current managed bytes as a
        new "original" would quietly redefine the player's settings as whatever
        Re-Gear last wrote. The recorded digest must also match the baseline
        actually found, so a valid but foreign replacement is refused too.
        """
        record = lookup.record
        problem = self._binding_problem(baseline_state, record)
        if problem is not None:
            return ApplyOutcome(
                ApplyResult.FAILED,
                f"refusing to write: {problem}, so a new write could not be "
                "undone and the current settings must not be recorded as the "
                "player's original",
                restoration_available=False,
            )
        if baseline_state.state in (BaselineState.CORRUPT, BaselineState.LOST):
            return ApplyOutcome(
                ApplyResult.FAILED,
                f"refusing to write: {baseline_state.detail or baseline_state.state.value}",
                restoration_available=False,
            )
        if baseline_state.state is BaselineState.NONE:
            if lookup.state is ManagementState.UNTRUSTED:
                return ApplyOutcome(
                    ApplyResult.FAILED,
                    "refusing to write: the management record cannot be trusted "
                    f"({lookup.detail}) and no original is held",
                    restoration_available=False,
                )
            return None  # Genuinely first enrollment.
        return None

    def _binding_refusal(
        self, profile: GraphicsProfile, schema: GameSchema | None
    ) -> ApplyOutcome | None:
        """Refuse a profile written for another schema or an unaccepted version."""
        if not self._catalog.accepts_profile_version(
            profile.steam_app_id, profile.profile_version
        ):
            return self._unsupported(
                f"profile version {profile.profile_version} is not one this build "
                "accepts for this game",
                (
                    "This graphics profile was written by a different version of "
                    "Re-Gear; it will not be applied.",
                ),
            )
        if profile.schema_id and (schema is None or profile.schema_id != schema.schema_id):
            registered = schema.schema_id if schema is not None else "none"
            return self._unsupported(
                f"profile targets schema {profile.schema_id!r} but {registered!r} "
                "is registered for this game",
                (
                    "This graphics profile was written for a different "
                    "configuration layout; it will not be applied.",
                ),
            )
        return None

    def _has_history(self, identity: str) -> bool:
        """Whether anything was ever backed up for this target."""
        try:
            return bool(self._backups.records(identity))
        except (BackupError, ValueError, OSError):
            # An unreadable store is not evidence that nothing was managed.
            return True

    def _baseline_record(
        self, identity: str, fallback: BackupRecord
    ) -> BackupRecord | None:
        try:
            lookup = self._backups.baseline(identity)
        except (BackupError, ValueError, OSError):
            return None
        if lookup.verified:
            return lookup.record
        return fallback if fallback.baseline else None

    def _baseline_available(self, identity: str) -> bool:
        """Only a baseline whose bytes verify may be advertised as restorable."""
        try:
            return self._backups.baseline(identity).verified
        except (BackupError, ValueError, OSError):
            return False

    @staticmethod
    def _unsupported(detail: str, advice: tuple[str, ...]) -> ApplyOutcome:
        return ApplyOutcome(
            ApplyResult.UNSUPPORTED, detail, tier=SupportTier.UNKNOWN, advice=advice
        )

    def _rollback(
        self,
        backup: BackupRecord,
        path: Path,
        detail: str,
        before_digest: str,
        written_digest: str | None,
        template: ManagementRecord,
    ) -> ApplyOutcome:
        """Undo this attempt's write, and only ever this attempt's write.

        A rollback is authorship-checked like any other write. The file on disk
        must be provably this attempt's product -- either the exact bytes it
        installed (`written_digest`), or still the exact bytes it started from,
        in which case nothing needs undoing. Anything else belongs to somebody
        else: a previous revision of this method restored the backup over any
        content that merely differed from the starting bytes, which destroyed an
        external edit that arrived mid-attempt. Content that is not ours is kept
        and reported as a conflict, and a file we cannot read is not permission
        to overwrite it either.
        """
        try:
            current = self._store.read(path)
        except (ConfigIoError, OSError) as error:
            return ApplyOutcome(
                ApplyResult.FAILED,
                f"{detail}; the file could not be re-read, so it was left as it is "
                f"rather than overwritten: {error}",
                backup=backup,
                before_digest=before_digest,
            )
        current_digest = digest_of(current.payload)
        if current_digest == before_digest:
            # Nothing was replaced, so nothing needs undoing -- but this is
            # still a completed attempt that left the file with the player, and
            # recording that is what makes an ordinary retry possible.
            self._settle(
                dataclasses.replace(
                    template,
                    managed_digest=before_digest,
                    lifecycle=Lifecycle.ROLLED_BACK,
                )
            )
            return ApplyOutcome(
                ApplyResult.ROLLED_BACK,
                detail + "; the file was already unchanged",
                backup=backup,
                before_digest=before_digest,
                after_digest=before_digest,
            )
        if written_digest is None or current_digest != written_digest:
            return ApplyOutcome(
                ApplyResult.CONFLICT,
                f"{detail}; the file now holds content Re-Gear did not write, so "
                "it was kept rather than rolled back",
                backup=backup,
                before_digest=before_digest,
                after_digest=current_digest,
                restoration_available=self._baseline_available(backup.identity),
            )
        try:
            identical = self._backups.restore(backup, path, expected=current.payload)
        except BackupChangedError as error:
            return ApplyOutcome(
                ApplyResult.CONFLICT,
                f"{detail}; {error}, so the newer content was kept",
                backup=backup,
                before_digest=before_digest,
            )
        except (BackupError, ValueError, OSError) as error:
            return ApplyOutcome(
                ApplyResult.FAILED,
                f"{detail}; rollback also failed: {error}",
                backup=backup,
                before_digest=before_digest,
            )
        suffix = "" if identical else "; rollback did not reproduce the original bytes"
        if identical:
            # A completed rollback is a known state, not a missing record: the
            # file is the player's and we know its digest, so an ordinary retry
            # after a transient failure is not a permanent conflict. Written
            # from the template rather than by transition, because a first
            # enrollment has no earlier record to transition.
            self._settle(
                dataclasses.replace(
                    template,
                    managed_digest=before_digest,
                    lifecycle=Lifecycle.ROLLED_BACK,
                )
            )
        return ApplyOutcome(
            ApplyResult.ROLLED_BACK if identical else ApplyResult.FAILED,
            detail + suffix,
            backup=backup,
            before_digest=before_digest,
            after_digest=before_digest if identical else None,
        )

    def _settle(self, record: ManagementRecord) -> None:
        """Best-effort lifecycle note. Failing to write it only costs a retry."""
        try:
            self._management.save(record)
        except (ManagementStateError, ValueError, OSError):
            return


def mode_of(value: str) -> OperatingMode:
    """Parse a mode name, defaulting nothing: unknown stays unknown."""
    try:
        return OperatingMode(value)
    except ValueError:
        return OperatingMode.UNKNOWN
