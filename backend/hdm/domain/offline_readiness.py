"""Pure, deliberately conservative offline-play readiness classification.

This is a glanceable local assessment, not a promise that a game will work
offline.  Steam, a publisher launcher, DRM, anti-cheat, and the game itself
remain the authority at launch time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .models import GameState

MAX_BLOCKERS = 16
MAX_EVIDENCE_AGE_MS = 24 * 60 * 60 * 1000
PUBLIC_REASON_CODES = frozenset(
    {
        "local_readiness_confirmed",
        "missing_local_content",
        "local_storage_unavailable",
        "install_integrity_unconfirmed",
        "game_not_installed",
        "download_pending",
        "update_pending",
        "cloud_save_pending",
        "cloud_save_conflict",
        "third_party_launcher",
        "drm",
        "anti_cheat",
        "game_owned_online_requirement",
        "install_unknown",
        "download_state_unknown",
        "steam_entitlement_unknown",
        "cloud_save_unknown",
        "offline_evidence_source_unreviewed",
        "offline_evidence_privacy_unreviewed",
        "offline_evidence_cost_unbenchmarked",
        "offline_evidence_cost_exceeds_budget",
        "offline_evidence_stale",
        "offline_evidence_game_active",
        "offline_evidence_game_unknown",
        "offline_evidence_context_changed",
        "offline_evidence_unavailable",
    }
)


class OfflineReadinessStatus(StrEnum):
    READY_TO_TRY_OFFLINE = "ready_to_try_offline"
    NEEDS_ATTENTION = "needs_attention"
    ONLINE_CHECK_NEEDED = "online_check_needed"
    UNKNOWN = "unknown"


class InstallState(StrEnum):
    INSTALLED = "installed"
    NOT_INSTALLED = "not_installed"
    UNKNOWN = "unknown"


class DownloadState(StrEnum):
    CURRENT = "current"
    PENDING_DOWNLOAD = "pending_download"
    PENDING_UPDATE = "pending_update"
    UNKNOWN = "unknown"


class SteamEntitlementState(StrEnum):
    RECENT_SIGN_IN_AND_LICENSE = "recent_sign_in_and_license"
    SIGN_IN_OR_LICENSE_UNCONFIRMED = "sign_in_or_license_unconfirmed"
    UNKNOWN = "unknown"


class CloudSaveState(StrEnum):
    SYNCED = "synced"
    PENDING = "pending"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


class OnlineCheckRequirement(StrEnum):
    THIRD_PARTY_LAUNCHER = "third_party_launcher"
    DRM = "drm"
    ANTI_CHEAT = "anti_cheat"
    GAME_OWNED_ONLINE_REQUIREMENT = "game_owned_online_requirement"


class LocalOfflineBlocker(StrEnum):
    MISSING_LOCAL_CONTENT = "missing_local_content"
    LOCAL_STORAGE_UNAVAILABLE = "local_storage_unavailable"
    INSTALL_INTEGRITY_UNCONFIRMED = "install_integrity_unconfirmed"


class OfflineEvidenceAdmissionKind(StrEnum):
    ADMIT = "admit"
    DEFER = "defer"
    REJECT = "reject"


class OfflineEvidenceSourceKind(StrEnum):
    LOCAL_STEAM_METADATA = "local_steam_metadata"
    LOCAL_LAUNCHER_METADATA = "local_launcher_metadata"


class OfflineEvidenceField(StrEnum):
    INSTALL = "install"
    DOWNLOAD = "download"
    ENTITLEMENT = "entitlement"
    CLOUD_SAVE = "cloud_save"
    LOCAL_BLOCKERS = "local_blockers"
    ONLINE_REQUIREMENTS = "online_requirements"


class OfflineEvidenceSourceReviewKind(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class OfflineEvidenceSourceDeclaration:
    """Review-only declaration; it carries no path, title, AppID, or command."""

    kind: OfflineEvidenceSourceKind
    read_only: bool
    uses_network: bool
    persists_data: bool
    identity_minimized: bool
    fields: tuple[OfflineEvidenceField, ...]

    def __post_init__(self) -> None:
        if not self.fields or len(self.fields) > len(OfflineEvidenceField):
            raise ValueError("offline evidence source fields are invalid")
        if len(set(self.fields)) != len(self.fields):
            raise ValueError("offline evidence source fields are duplicated")


@dataclass(frozen=True, slots=True)
class OfflineEvidenceSourceReview:
    kind: OfflineEvidenceSourceReviewKind
    reason_code: str

    def __post_init__(self) -> None:
        if self.reason_code not in PUBLIC_REASON_CODES:
            raise ValueError("offline evidence source review reason is not public")


@dataclass(frozen=True, slots=True)
class OfflineEvidenceCollectionContract:
    """Review and cost declaration for a future local evidence source.

    This is not a Steam integration. It carries no account, AppID, title, path,
    or source command; a delivery owner must retain those private details and
    supply only categorical ``OfflineReadinessEvidence`` after admission.
    """

    reviewed: bool
    local_only: bool
    identity_minimized: bool
    interval_ms: int
    measured_collection_cost_ms: int
    benchmarked: bool
    max_evidence_age_ms: int

    def __post_init__(self) -> None:
        if self.interval_ms < 1_000:
            raise ValueError("offline evidence interval must be at least one second")
        if self.measured_collection_cost_ms <= 0:
            raise ValueError("offline evidence cost must be positive")
        if not 1_000 <= self.max_evidence_age_ms <= MAX_EVIDENCE_AGE_MS:
            raise ValueError("offline evidence freshness bound is invalid")


@dataclass(frozen=True, slots=True)
class OfflineEvidenceAdmission:
    kind: OfflineEvidenceAdmissionKind
    reason_code: str
    defer_for_ms: int = 0

    def __post_init__(self) -> None:
        if self.reason_code not in PUBLIC_REASON_CODES:
            raise ValueError("offline evidence admission reason is not public")
        if self.kind is OfflineEvidenceAdmissionKind.DEFER:
            if self.defer_for_ms <= 0:
                raise ValueError("deferred offline evidence needs a delay")
        elif self.defer_for_ms:
            raise ValueError("non-deferred offline evidence cannot have a delay")


@dataclass(frozen=True, slots=True)
class OfflineReadinessObservation:
    """One private-time categorical result from an already admitted source."""

    observed_at_monotonic_ms: int
    evidence: "OfflineReadinessEvidence"

    def __post_init__(self) -> None:
        if type(self.observed_at_monotonic_ms) is not int or self.observed_at_monotonic_ms < 0:
            raise ValueError("offline readiness observation time is invalid")
        if not isinstance(self.evidence, OfflineReadinessEvidence):
            raise ValueError("offline readiness observation evidence is invalid")


@dataclass(frozen=True, slots=True)
class OfflineReadinessEvidence:
    """Categorical, local-only evidence for one game; no account data or paths."""

    install: InstallState = InstallState.UNKNOWN
    download: DownloadState = DownloadState.UNKNOWN
    steam_entitlement: SteamEntitlementState = SteamEntitlementState.UNKNOWN
    cloud_save: CloudSaveState = CloudSaveState.UNKNOWN
    local_blockers: tuple[LocalOfflineBlocker, ...] = field(default_factory=tuple)
    online_check_requirements: tuple[OnlineCheckRequirement, ...] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        for value, expected in (
            (self.install, InstallState),
            (self.download, DownloadState),
            (self.steam_entitlement, SteamEntitlementState),
            (self.cloud_save, CloudSaveState),
        ):
            if not isinstance(value, expected):
                raise ValueError("offline readiness evidence category is invalid")
        for values, expected in (
            (self.local_blockers, LocalOfflineBlocker),
            (self.online_check_requirements, OnlineCheckRequirement),
        ):
            if type(values) is not tuple or any(not isinstance(v, expected) for v in values):
                raise ValueError("offline readiness evidence list is invalid")
        if len(self.local_blockers) > MAX_BLOCKERS or len(
            self.online_check_requirements
        ) > MAX_BLOCKERS:
            raise ValueError("offline readiness evidence exceeds its bound")
        if len(set(self.local_blockers)) != len(self.local_blockers):
            raise ValueError("offline readiness local blockers are duplicated")
        if len(set(self.online_check_requirements)) != len(
            self.online_check_requirements
        ):
            raise ValueError("offline readiness online checks are duplicated")


@dataclass(frozen=True, slots=True)
class OfflineReadinessAssessment:
    status: OfflineReadinessStatus
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.status, OfflineReadinessStatus):
            raise ValueError("offline readiness status is invalid")
        if not self.reason_codes or len(self.reason_codes) > MAX_BLOCKERS:
            raise ValueError("offline readiness reasons are invalid")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("offline readiness reasons are duplicated")
        if not set(self.reason_codes).issubset(PUBLIC_REASON_CODES):
            raise ValueError("offline readiness reasons are not public codes")


def classify_offline_readiness(
    evidence: OfflineReadinessEvidence,
) -> OfflineReadinessAssessment:
    """Fail closed: incomplete evidence is never promoted to ready."""

    attention = _attention_reasons(evidence)
    if attention:
        return OfflineReadinessAssessment(
            OfflineReadinessStatus.NEEDS_ATTENTION, tuple(attention)
        )
    if evidence.online_check_requirements:
        return OfflineReadinessAssessment(
            OfflineReadinessStatus.ONLINE_CHECK_NEEDED,
            tuple(item.value for item in evidence.online_check_requirements),
        )
    unknown = _unknown_reasons(evidence)
    if unknown:
        return OfflineReadinessAssessment(OfflineReadinessStatus.UNKNOWN, tuple(unknown))
    return OfflineReadinessAssessment(
        OfflineReadinessStatus.READY_TO_TRY_OFFLINE,
        ("local_readiness_confirmed",),
    )


def admit_offline_evidence_collection(
    contract: OfflineEvidenceCollectionContract,
    game_state: GameState,
) -> OfflineEvidenceAdmission:
    """Gate a future local collector without starting it or reading Steam data."""
    if not contract.reviewed:
        return OfflineEvidenceAdmission(
            OfflineEvidenceAdmissionKind.REJECT,
            "offline_evidence_source_unreviewed",
        )
    if not contract.local_only or not contract.identity_minimized:
        return OfflineEvidenceAdmission(
            OfflineEvidenceAdmissionKind.REJECT,
            "offline_evidence_privacy_unreviewed",
        )
    if not contract.benchmarked:
        return OfflineEvidenceAdmission(
            OfflineEvidenceAdmissionKind.REJECT,
            "offline_evidence_cost_unbenchmarked",
        )
    if contract.measured_collection_cost_ms * 10 > contract.interval_ms:
        return OfflineEvidenceAdmission(
            OfflineEvidenceAdmissionKind.REJECT,
            "offline_evidence_cost_exceeds_budget",
        )
    if game_state is GameState.RUNNING:
        return OfflineEvidenceAdmission(
            OfflineEvidenceAdmissionKind.DEFER,
            "offline_evidence_game_active",
            defer_for_ms=30_000,
        )
    if game_state is not GameState.IDLE:
        return OfflineEvidenceAdmission(
            OfflineEvidenceAdmissionKind.DEFER,
            "offline_evidence_game_unknown",
            defer_for_ms=15_000,
        )
    return OfflineEvidenceAdmission(
        OfflineEvidenceAdmissionKind.ADMIT,
        "local_readiness_confirmed",
    )


def review_offline_evidence_source(
    declaration: OfflineEvidenceSourceDeclaration,
) -> OfflineEvidenceSourceReview:
    """Approve only a local, read-only, identity-minimized declared source."""
    if not declaration.read_only or declaration.uses_network or declaration.persists_data:
        return OfflineEvidenceSourceReview(
            OfflineEvidenceSourceReviewKind.REJECTED,
            "offline_evidence_privacy_unreviewed",
        )
    if not declaration.identity_minimized:
        return OfflineEvidenceSourceReview(
            OfflineEvidenceSourceReviewKind.REJECTED,
            "offline_evidence_privacy_unreviewed",
        )
    return OfflineEvidenceSourceReview(
        OfflineEvidenceSourceReviewKind.APPROVED,
        "local_readiness_confirmed",
    )


def admit_reviewed_offline_evidence_source(
    declaration: OfflineEvidenceSourceDeclaration,
    contract: OfflineEvidenceCollectionContract,
    game_state: GameState,
) -> OfflineEvidenceAdmission:
    """Compose source review with the existing bounded collection admission."""
    review = review_offline_evidence_source(declaration)
    if review.kind is OfflineEvidenceSourceReviewKind.REJECTED:
        return OfflineEvidenceAdmission(OfflineEvidenceAdmissionKind.REJECT, review.reason_code)
    return admit_offline_evidence_collection(contract, game_state)


def classify_fresh_offline_readiness(
    observation: OfflineReadinessObservation,
    contract: OfflineEvidenceCollectionContract,
    *,
    now_monotonic_ms: int,
) -> OfflineReadinessAssessment:
    """Fail closed when a supplied categorical result is stale or from no gate."""
    admission = admit_offline_evidence_collection(contract, GameState.IDLE)
    if admission.kind is not OfflineEvidenceAdmissionKind.ADMIT:
        return OfflineReadinessAssessment(
            OfflineReadinessStatus.UNKNOWN, (admission.reason_code,)
        )
    age_ms = now_monotonic_ms - observation.observed_at_monotonic_ms
    if age_ms < 0 or age_ms > contract.max_evidence_age_ms:
        return OfflineReadinessAssessment(
            OfflineReadinessStatus.UNKNOWN, ("offline_evidence_stale",)
        )
    return classify_offline_readiness(observation.evidence)


def offline_readiness_to_public_dict(
    assessment: OfflineReadinessAssessment,
) -> dict[str, Any]:
    """Serialize only categorical guidance; omit game, account, path, and time data."""

    return {
        "schema_version": 1,
        "status": assessment.status.value,
        "reason_codes": list(assessment.reason_codes),
    }


def _attention_reasons(evidence: OfflineReadinessEvidence) -> list[str]:
    reasons = [item.value for item in evidence.local_blockers]
    if evidence.install is InstallState.NOT_INSTALLED:
        reasons.append("game_not_installed")
    if evidence.download is DownloadState.PENDING_DOWNLOAD:
        reasons.append("download_pending")
    elif evidence.download is DownloadState.PENDING_UPDATE:
        reasons.append("update_pending")
    if evidence.cloud_save is CloudSaveState.PENDING:
        reasons.append("cloud_save_pending")
    elif evidence.cloud_save is CloudSaveState.CONFLICT:
        reasons.append("cloud_save_conflict")
    return reasons


def _unknown_reasons(evidence: OfflineReadinessEvidence) -> list[str]:
    reasons: list[str] = []
    if evidence.install is InstallState.UNKNOWN:
        reasons.append("install_unknown")
    if evidence.download is DownloadState.UNKNOWN:
        reasons.append("download_state_unknown")
    if evidence.steam_entitlement is not SteamEntitlementState.RECENT_SIGN_IN_AND_LICENSE:
        reasons.append("steam_entitlement_unknown")
    if evidence.cloud_save is CloudSaveState.UNKNOWN:
        reasons.append("cloud_save_unknown")
    return reasons
