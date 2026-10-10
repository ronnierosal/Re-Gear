"""Pure fixture reconciliation candidates. This module cannot execute a plan."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .emulator_save_inventory import (
    SHA256, SaveDataKind, SaveManifest, optional_bool, token,
)


class BaselineState(StrEnum):
    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"
    CORRUPT = "corrupt"


@dataclass(frozen=True, slots=True)
class LastSyncedBaseline:
    state: BaselineState
    manifest: SaveManifest | None = None
    confirmation_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, BaselineState):
            raise ValueError("invalid baseline state")
        if self.manifest is not None and not isinstance(self.manifest, SaveManifest):
            raise ValueError("invalid baseline manifest")
        if self.confirmation_id is not None:
            token(self.confirmation_id)


@dataclass(frozen=True, slots=True)
class ReconciliationEvidence:
    emulator_closed: bool | None = None
    download_complete: bool | None = None
    native_backup_sha256: str | None = None
    carrier_backup_sha256: str | None = None

    def __post_init__(self) -> None:
        optional_bool(self.emulator_closed)
        optional_bool(self.download_complete)
        for digest in (self.native_backup_sha256, self.carrier_backup_sha256):
            if digest is not None and (
                type(digest) is not str or SHA256.fullmatch(digest) is None
            ):
                raise ValueError("invalid supplied backup hash")


class ReconciliationKind(StrEnum):
    UNCHANGED = "unchanged"
    IMPORT_CANDIDATE = "import_candidate"
    EXPORT_CANDIDATE = "export_candidate"
    CONFLICT = "conflict"
    DEFERRED = "deferred"


@dataclass(frozen=True, slots=True)
class ReconciliationPlan:
    kind: ReconciliationKind
    reason: str
    native_sha256: str | None
    carrier_sha256: str | None
    preserve_both: bool = True
    requires_user_choice: bool = False
    fixture_only: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ReconciliationKind):
            raise ValueError("invalid reconciliation kind")
        token(self.reason)
        for digest in (self.native_sha256, self.carrier_sha256):
            if digest is not None and (
                type(digest) is not str or SHA256.fullmatch(digest) is None
            ):
                raise ValueError("invalid plan hash")
        if self.preserve_both is not True or self.fixture_only is not True:
            raise ValueError("plans must preserve both copies and stay fixture-only")
        if type(self.requires_user_choice) is not bool or (
            self.requires_user_choice != (self.kind is ReconciliationKind.CONFLICT)
        ):
            raise ValueError("conflict requires user choice")


def plan_save_reconciliation(
    native: SaveManifest | None,
    carrier: SaveManifest | None,
    baseline: LastSyncedBaseline | None,
    evidence: ReconciliationEvidence,
) -> ReconciliationPlan:
    """Compare complete atomic units against an explicitly confirmed baseline.

    Equality does not confirm a Steam upload or advance the last-synced baseline.
    Missing members never imply deletion. Candidates need supplied independent
    backups of BOTH current copies, closed-emulator and download-before-import
    evidence, even when the direction is export-before-upload.
    """
    if not isinstance(evidence, ReconciliationEvidence):
        raise ValueError("invalid reconciliation evidence")
    if any(value is not None and not isinstance(value, SaveManifest) for value in (native, carrier)):
        raise ValueError("invalid reconciliation manifest")
    if baseline is not None and not isinstance(baseline, LastSyncedBaseline):
        raise ValueError("invalid last-synced baseline")

    def result(kind: ReconciliationKind, reason: str) -> ReconciliationPlan:
        return ReconciliationPlan(
            kind, reason, native.sha256 if native else None,
            carrier.sha256 if carrier else None,
            requires_user_choice=kind is ReconciliationKind.CONFLICT,
        )

    def defer(reason: str) -> ReconciliationPlan:
        return result(ReconciliationKind.DEFERRED, reason)

    if native is None or carrier is None:
        return defer("copy_missing")
    if (
        baseline is None or baseline.state is not BaselineState.CONFIRMED
        or baseline.manifest is None or baseline.confirmation_id is None
    ):
        return defer("baseline_unconfirmed")
    prior = baseline.manifest
    if not all(manifest.complete for manifest in (native, carrier, prior)):
        return defer("save_unit_incomplete")
    if not native.binding == carrier.binding == prior.binding:
        return defer("binding_mismatch")
    prior_names = {member.name for member in prior.members}
    if any(
        not prior_names.issubset({member.name for member in copy.members})
        for copy in (native, carrier)
    ):
        return defer("members_removed_without_decision")
    binding = native.binding
    if binding.game_ids_confirmed is not True or binding.game_id_provenance is None:
        return defer("game_identity_unconfirmed")
    if binding.data_kind is not SaveDataKind.ORDINARY_SAVE:
        return defer("save_state_out_of_scope")
    if binding.emulator_version is None or binding.format_version is None:
        return defer("version_unknown")
    if evidence.emulator_closed is not True:
        return defer("emulator_not_confirmed_closed")
    if evidence.download_complete is not True:
        return defer("download_not_confirmed")
    if native.sha256 == carrier.sha256:
        return result(ReconciliationKind.UNCHANGED, "equal_bytes_no_sync_ack")
    if native.sha256 != prior.sha256 and carrier.sha256 != prior.sha256:
        return result(ReconciliationKind.CONFLICT, "both_copies_changed")
    if (
        evidence.native_backup_sha256 != native.sha256
        or evidence.carrier_backup_sha256 != carrier.sha256
    ):
        return defer("independent_backups_unconfirmed")
    if native.sha256 == prior.sha256:
        return result(ReconciliationKind.IMPORT_CANDIDATE, "only_carrier_changed")
    return result(ReconciliationKind.EXPORT_CANDIDATE, "only_native_changed")
