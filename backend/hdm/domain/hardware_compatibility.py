"""Pure hardware compatibility catalog and intentional promotion gates."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import StrEnum


TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")
MAX_HARDWARE_PROMOTIONS = 64


class HardwareCatalogStatus(StrEnum):
    UNTESTED = "untested"
    CERTIFIED = "certified"
    VERIFIED = "verified"
    EXPERIMENTAL = "experimental"
    UNSUPPORTED = "unsupported"
    KNOWN_ISSUE = "known_issue"


class HardwareCapability(StrEnum):
    COMBINATION = "combination"
    PROFILE_IDENTITY = "profile_identity"
    EGPU_DETECTION = "egpu_detection"
    EXTERNAL_DISPLAY_OUTPUT = "external_display_output"
    DISPLAY_HANDOFF = "display_handoff"
    AUDIO_HANDOFF = "audio_handoff"
    DOCKED_IGPU = "docked_igpu"
    DISCONNECT_BEFORE_SLEEP = "disconnect_before_sleep"
    SLEEP_WITH_EGPU = "sleep_with_egpu"
    LIVE_REMOVAL = "live_removal"
    CONTROLLER_HANDOFF = "controller_handoff"
    BUILTIN_CONTROLLER_SUPPRESSION = "builtin_controller_suppression"
    EXTERNAL_CONTROLLER_POWER_OFF = "external_controller_power_off"


class HardwareEvidenceKind(StrEnum):
    SIMULATION = "simulation"
    READ_ONLY_HARDWARE_TEST = "read_only_hardware_test"
    SUPERVISED_HARDWARE_TEST = "supervised_hardware_test"


_MUTATING_CAPABILITIES = frozenset(
    {
        HardwareCapability.DISPLAY_HANDOFF,
        HardwareCapability.AUDIO_HANDOFF,
        HardwareCapability.DOCKED_IGPU,
        HardwareCapability.DISCONNECT_BEFORE_SLEEP,
        HardwareCapability.SLEEP_WITH_EGPU,
        HardwareCapability.LIVE_REMOVAL,
        HardwareCapability.CONTROLLER_HANDOFF,
        HardwareCapability.BUILTIN_CONTROLLER_SUPPRESSION,
        HardwareCapability.EXTERNAL_CONTROLLER_POWER_OFF,
    }
)


@dataclass(frozen=True, slots=True)
class HardwareEvidence:
    evidence_id: str
    capability: HardwareCapability
    outcome: HardwareCatalogStatus
    kind: HardwareEvidenceKind
    intentional_test: bool
    reviewed: bool
    host_profile_id: str
    egpu_profile_id: str
    regear_version: str
    steamos_version: str
    tested_at: str
    rollback_or_recovery_verified: bool = False
    expected_removal_verified: bool = False
    portable_recovery_verified: bool = False
    kernel_errors_absent: bool = False

    def __post_init__(self) -> None:
        for value in (
            self.evidence_id,
            self.host_profile_id,
            self.egpu_profile_id,
            self.regear_version,
            self.steamos_version,
        ):
            if not TOKEN_RE.fullmatch(value):
                raise ValueError("hardware evidence identity is invalid")
        if not self.tested_at:
            raise ValueError("hardware evidence timestamp is required")
        if self.outcome is HardwareCatalogStatus.UNTESTED:
            raise ValueError("hardware evidence outcome cannot be untested")


@dataclass(frozen=True, slots=True)
class HardwareCapabilityClaim:
    capability: HardwareCapability
    status: HardwareCatalogStatus
    evidence_id: str

    def __post_init__(self) -> None:
        if self.capability is HardwareCapability.COMBINATION:
            raise ValueError("combination status is not a capability claim")
        if self.status is HardwareCatalogStatus.CERTIFIED:
            raise ValueError("individual capabilities use verified, not certified")
        if self.status is HardwareCatalogStatus.UNTESTED:
            raise ValueError("untested capabilities are represented by no claim")
        if not TOKEN_RE.fullmatch(self.evidence_id):
            raise ValueError("hardware claim evidence identity is invalid")


@dataclass(frozen=True, slots=True)
class HardwarePromotion:
    capability: HardwareCapability
    from_status: HardwareCatalogStatus
    to_status: HardwareCatalogStatus
    evidence_id: str

    def __post_init__(self) -> None:
        if not TOKEN_RE.fullmatch(self.evidence_id):
            raise ValueError("hardware promotion evidence identity is invalid")
        if self.to_status is HardwareCatalogStatus.UNTESTED:
            raise ValueError("hardware promotion cannot target untested")
        if (
            self.capability is not HardwareCapability.COMBINATION
            and self.to_status is HardwareCatalogStatus.CERTIFIED
        ):
            raise ValueError("individual capability cannot be certified")


@dataclass(frozen=True, slots=True)
class HardwareCompatibilityRecord:
    catalog_id: str
    host_profile_id: str
    egpu_profile_id: str
    combination_status: HardwareCatalogStatus = HardwareCatalogStatus.UNTESTED
    claims: tuple[HardwareCapabilityClaim, ...] = field(default_factory=tuple)
    promotions: tuple[HardwarePromotion, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for value in (self.catalog_id, self.host_profile_id, self.egpu_profile_id):
            if not TOKEN_RE.fullmatch(value):
                raise ValueError("hardware compatibility identity is invalid")
        if len(self.promotions) > MAX_HARDWARE_PROMOTIONS:
            raise ValueError("hardware promotion history exceeds its bound")
        capabilities = tuple(claim.capability for claim in self.claims)
        if len(capabilities) != len(set(capabilities)):
            raise ValueError("hardware capability claims must be unique")
        states = {
            capability: HardwareCatalogStatus.UNTESTED
            for capability in HardwareCapability
        }
        for promotion in self.promotions:
            if promotion.from_status is not states[promotion.capability]:
                raise ValueError("hardware promotion history is not contiguous")
            states[promotion.capability] = promotion.to_status
        if states[HardwareCapability.COMBINATION] is not self.combination_status:
            raise ValueError("combination status lacks matching promotion history")
        claims_by_capability = {claim.capability: claim for claim in self.claims}
        for capability in HardwareCapability:
            if capability is HardwareCapability.COMBINATION:
                continue
            claim = claims_by_capability.get(capability)
            if states[capability] is HardwareCatalogStatus.UNTESTED:
                if claim is not None:
                    raise ValueError("hardware claim lacks matching promotion history")
                continue
            if claim is None or claim.status is not states[capability]:
                raise ValueError("hardware claim lacks matching promotion history")
            matching = next(
                (
                    promotion
                    for promotion in reversed(self.promotions)
                    if promotion.capability is capability
                ),
                None,
            )
            if matching is None or claim.evidence_id != matching.evidence_id:
                raise ValueError("hardware claim evidence does not match promotion history")

    def status_for(self, capability: HardwareCapability) -> HardwareCatalogStatus:
        if capability is HardwareCapability.COMBINATION:
            return self.combination_status
        return next(
            (
                claim.status
                for claim in self.claims
                if claim.capability is capability
            ),
            HardwareCatalogStatus.UNTESTED,
        )


def promote_hardware_combination(
    record: HardwareCompatibilityRecord,
    status: HardwareCatalogStatus,
    evidence: HardwareEvidence,
) -> HardwareCompatibilityRecord:
    _require_evidence(record, evidence, HardwareCapability.COMBINATION)
    if status is not evidence.outcome:
        raise ValueError("combination status does not match reviewed evidence")
    if status in {
        HardwareCatalogStatus.CERTIFIED,
        HardwareCatalogStatus.VERIFIED,
    } and evidence.kind is not HardwareEvidenceKind.SUPERVISED_HARDWARE_TEST:
        raise ValueError("verified combination status requires supervised hardware evidence")
    return replace(
        record,
        combination_status=status,
        promotions=_append_promotion(
            record,
            HardwareCapability.COMBINATION,
            record.combination_status,
            status,
            evidence.evidence_id,
        ),
    )


def promote_hardware_capability(
    record: HardwareCompatibilityRecord,
    capability: HardwareCapability,
    status: HardwareCatalogStatus,
    evidence: HardwareEvidence,
) -> HardwareCompatibilityRecord:
    if capability is HardwareCapability.COMBINATION:
        raise ValueError("use combination promotion for combination status")
    if status in {
        HardwareCatalogStatus.UNTESTED,
        HardwareCatalogStatus.CERTIFIED,
    }:
        raise ValueError("hardware capability status is invalid")
    _require_evidence(record, evidence, capability)
    if status is not evidence.outcome:
        raise ValueError("capability status does not match reviewed evidence")
    if (
        status is HardwareCatalogStatus.VERIFIED
        and capability in _MUTATING_CAPABILITIES
    ):
        if evidence.kind is not HardwareEvidenceKind.SUPERVISED_HARDWARE_TEST:
            raise ValueError("verified mutating capability requires supervised hardware evidence")
        if not evidence.rollback_or_recovery_verified:
            raise ValueError("verified mutating capability requires recovery evidence")
    if capability is HardwareCapability.LIVE_REMOVAL and status is HardwareCatalogStatus.VERIFIED:
        if not (
            evidence.expected_removal_verified
            and evidence.portable_recovery_verified
            and evidence.kernel_errors_absent
        ):
            raise ValueError("live removal requires expected removal, portable recovery, and clean kernel evidence")

    current = record.status_for(capability)
    claims = tuple(claim for claim in record.claims if claim.capability is not capability)
    claims = (
        *claims,
        HardwareCapabilityClaim(capability, status, evidence.evidence_id),
    )
    return replace(
        record,
        claims=tuple(sorted(claims, key=lambda claim: claim.capability.value)),
        promotions=_append_promotion(
            record,
            capability,
            current,
            status,
            evidence.evidence_id,
        ),
    )


def _require_evidence(
    record: HardwareCompatibilityRecord,
    evidence: HardwareEvidence,
    capability: HardwareCapability,
) -> None:
    if evidence.capability is not capability:
        raise ValueError("hardware evidence capability does not match")
    if evidence.kind is HardwareEvidenceKind.SIMULATION:
        raise ValueError("simulation cannot promote hardware compatibility")
    if not evidence.intentional_test or not evidence.reviewed:
        raise ValueError("hardware evidence requires intentional review")
    if (
        evidence.host_profile_id != record.host_profile_id
        or evidence.egpu_profile_id != record.egpu_profile_id
    ):
        raise ValueError("hardware evidence profile does not match")
    if any(
        item.evidence_id == evidence.evidence_id and item.capability is capability
        for item in record.promotions
    ):
        raise ValueError("hardware evidence was already used for this capability")


def _append_promotion(
    record: HardwareCompatibilityRecord,
    capability: HardwareCapability,
    from_status: HardwareCatalogStatus,
    to_status: HardwareCatalogStatus,
    evidence_id: str,
) -> tuple[HardwarePromotion, ...]:
    if len(record.promotions) >= MAX_HARDWARE_PROMOTIONS:
        raise ValueError("hardware promotion history is full")
    return (
        *record.promotions,
        HardwarePromotion(capability, from_status, to_status, evidence_id),
    )
