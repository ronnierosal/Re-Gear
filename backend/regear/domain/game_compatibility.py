"""Pure game compatibility catalog contracts and promotion policy.

Observed telemetry is evidence, never authority. A catalog status can only move
away from untested through an intentional, reviewed hardware test whose exact
profiles match the record.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import StrEnum


TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")
STEAM_APP_ID_RE = re.compile(r"^[1-9][0-9]{0,9}$")
MAX_PROMOTIONS = 32


class GameSaveCapability(StrEnum):
    UNTESTED = "untested"
    VERIFIED_TRIGGERABLE_AUTOSAVE = "verified_triggerable_autosave"
    VERIFIED_SAVE_ON_EXIT = "verified_save_on_exit"
    GRACEFUL_EXIT_VERIFIED = "graceful_exit_verified"
    MANUAL_SAVE_RECOMMENDED = "manual_save_recommended"
    MANUAL_SAVE_REQUIRED = "manual_save_required"
    UNSAFE_UNKNOWN = "unsafe_unknown"


class EgpuHandoffStatus(StrEnum):
    UNTESTED = "untested"
    VERIFIED = "verified"
    VERIFIED_WITH_WORKAROUND = "verified_with_workaround"
    FALLS_BACK_TO_IGPU = "falls_back_to_igpu"
    KNOWN_ISSUE = "known_issue"
    UNSUPPORTED = "unsupported"


class CompatibilityEvidenceKind(StrEnum):
    SIMULATION = "simulation"
    HARDWARE_TEST = "hardware_test"


class ObservedRenderGpu(StrEnum):
    INTERNAL = "internal"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


class SaveTestOutcome(StrEnum):
    NOT_TESTED = "not_tested"
    TRIGGERABLE_AUTOSAVE_VERIFIED = "triggerable_autosave_verified"
    SAVE_ON_EXIT_VERIFIED = "save_on_exit_verified"
    GRACEFUL_EXIT_VERIFIED = "graceful_exit_verified"
    MANUAL_SAVE_RECOMMENDED = "manual_save_recommended"
    MANUAL_SAVE_REQUIRED = "manual_save_required"
    UNSAFE_UNKNOWN = "unsafe_unknown"


@dataclass(frozen=True, slots=True)
class CompatibilityEvidence:
    evidence_id: str
    game_catalog_id: str
    steam_app_id: str
    kind: CompatibilityEvidenceKind
    intentional_test: bool
    reviewed: bool
    host_profile_id: str
    egpu_profile_id: str
    regear_version: str
    steamos_version: str
    tested_at: str
    observed_render_gpu: ObservedRenderGpu = ObservedRenderGpu.UNKNOWN
    save_outcome: SaveTestOutcome = SaveTestOutcome.NOT_TESTED

    def __post_init__(self) -> None:
        for value in (
            self.evidence_id,
            self.game_catalog_id,
            self.host_profile_id,
            self.egpu_profile_id,
            self.regear_version,
            self.steamos_version,
        ):
            if not TOKEN_RE.fullmatch(value):
                raise ValueError("compatibility evidence identity is invalid")
        if not self.tested_at:
            raise ValueError("compatibility test timestamp is required")
        if self.steam_app_id and not STEAM_APP_ID_RE.fullmatch(self.steam_app_id):
            raise ValueError("compatibility evidence Steam AppID is invalid")


@dataclass(frozen=True, slots=True)
class CompatibilityPromotion:
    evidence_id: str
    dimension: str
    from_status: str
    to_status: str

    def __post_init__(self) -> None:
        if self.dimension not in {"egpu_handoff", "save_sleep"}:
            raise ValueError("compatibility promotion dimension is invalid")
        for value in (self.evidence_id, self.from_status, self.to_status):
            if not TOKEN_RE.fullmatch(value):
                raise ValueError("compatibility promotion value is invalid")
        status_type = (
            EgpuHandoffStatus
            if self.dimension == "egpu_handoff"
            else GameSaveCapability
        )
        status_type(self.from_status)
        if status_type(self.to_status).value == "untested":
            raise ValueError("compatibility promotion cannot target untested")


@dataclass(frozen=True, slots=True)
class GameCompatibilityRecord:
    catalog_id: str
    title: str
    host_profile_id: str
    egpu_profile_id: str
    steam_app_id: str = ""
    egpu_handoff: EgpuHandoffStatus = EgpuHandoffStatus.UNTESTED
    save_sleep: GameSaveCapability = GameSaveCapability.UNTESTED
    promotions: tuple[CompatibilityPromotion, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for value in (
            self.catalog_id,
            self.host_profile_id,
            self.egpu_profile_id,
        ):
            if not TOKEN_RE.fullmatch(value):
                raise ValueError("compatibility record identity is invalid")
        if not self.title or len(self.title) > 160 or any(
            character in self.title for character in "\r\n\0"
        ):
            raise ValueError("compatibility title is invalid")
        if self.steam_app_id and not STEAM_APP_ID_RE.fullmatch(self.steam_app_id):
            raise ValueError("Steam AppID is invalid")
        if len(self.promotions) > MAX_PROMOTIONS:
            raise ValueError("compatibility promotion history exceeds its bound")
        states = {
            "egpu_handoff": EgpuHandoffStatus.UNTESTED.value,
            "save_sleep": GameSaveCapability.UNTESTED.value,
        }
        for promotion in self.promotions:
            if promotion.from_status != states[promotion.dimension]:
                raise ValueError("compatibility promotion history is not contiguous")
            states[promotion.dimension] = promotion.to_status
        if states["egpu_handoff"] != self.egpu_handoff.value:
            raise ValueError("eGPU handoff status lacks matching promotion history")
        if states["save_sleep"] != self.save_sleep.value:
            raise ValueError("save/sleep status lacks matching promotion history")


def promote_egpu_handoff(
    record: GameCompatibilityRecord,
    status: EgpuHandoffStatus,
    evidence: CompatibilityEvidence,
) -> GameCompatibilityRecord:
    _require_reviewed_hardware_evidence(record, evidence, "egpu_handoff")
    if status is EgpuHandoffStatus.UNTESTED:
        raise ValueError("compatibility status cannot be promoted to untested")
    if status in {
        EgpuHandoffStatus.VERIFIED,
        EgpuHandoffStatus.VERIFIED_WITH_WORKAROUND,
    } and evidence.observed_render_gpu is not ObservedRenderGpu.EXTERNAL:
        raise ValueError("verified eGPU handoff requires observed external rendering")
    if (
        status is EgpuHandoffStatus.FALLS_BACK_TO_IGPU
        and evidence.observed_render_gpu is not ObservedRenderGpu.INTERNAL
    ):
        raise ValueError("iGPU fallback requires observed internal rendering")
    return replace(
        record,
        egpu_handoff=status,
        promotions=_append_promotion(
            record,
            evidence,
            "egpu_handoff",
            record.egpu_handoff.value,
            status.value,
        ),
    )


def promote_save_sleep(
    record: GameCompatibilityRecord,
    status: GameSaveCapability,
    evidence: CompatibilityEvidence,
) -> GameCompatibilityRecord:
    _require_reviewed_hardware_evidence(record, evidence, "save_sleep")
    if status is GameSaveCapability.UNTESTED:
        raise ValueError("compatibility status cannot be promoted to untested")
    required_outcome = {
        GameSaveCapability.VERIFIED_TRIGGERABLE_AUTOSAVE:
            SaveTestOutcome.TRIGGERABLE_AUTOSAVE_VERIFIED,
        GameSaveCapability.VERIFIED_SAVE_ON_EXIT:
            SaveTestOutcome.SAVE_ON_EXIT_VERIFIED,
        GameSaveCapability.GRACEFUL_EXIT_VERIFIED:
            SaveTestOutcome.GRACEFUL_EXIT_VERIFIED,
        GameSaveCapability.MANUAL_SAVE_RECOMMENDED:
            SaveTestOutcome.MANUAL_SAVE_RECOMMENDED,
        GameSaveCapability.MANUAL_SAVE_REQUIRED:
            SaveTestOutcome.MANUAL_SAVE_REQUIRED,
        GameSaveCapability.UNSAFE_UNKNOWN:
            SaveTestOutcome.UNSAFE_UNKNOWN,
    }[status]
    if evidence.save_outcome is not required_outcome:
        raise ValueError("save/sleep status does not match reviewed evidence")
    return replace(
        record,
        save_sleep=status,
        promotions=_append_promotion(
            record,
            evidence,
            "save_sleep",
            record.save_sleep.value,
            status.value,
        ),
    )


def _require_reviewed_hardware_evidence(
    record: GameCompatibilityRecord,
    evidence: CompatibilityEvidence,
    dimension: str,
) -> None:
    if evidence.kind is not CompatibilityEvidenceKind.HARDWARE_TEST:
        raise ValueError("simulation cannot promote compatibility status")
    if not evidence.intentional_test or not evidence.reviewed:
        raise ValueError("compatibility evidence requires intentional review")
    if (
        evidence.game_catalog_id != record.catalog_id
        or evidence.steam_app_id != record.steam_app_id
    ):
        raise ValueError("compatibility evidence game identity does not match")
    if (
        evidence.host_profile_id != record.host_profile_id
        or evidence.egpu_profile_id != record.egpu_profile_id
    ):
        raise ValueError("compatibility evidence profile does not match")
    if any(
        item.evidence_id == evidence.evidence_id and item.dimension == dimension
        for item in record.promotions
    ):
        raise ValueError("compatibility evidence was already used for this dimension")


def _append_promotion(
    record: GameCompatibilityRecord,
    evidence: CompatibilityEvidence,
    dimension: str,
    from_status: str,
    to_status: str,
) -> tuple[CompatibilityPromotion, ...]:
    if len(record.promotions) >= MAX_PROMOTIONS:
        raise ValueError("compatibility promotion history is full")
    return (
        *record.promotions,
        CompatibilityPromotion(
            evidence_id=evidence.evidence_id,
            dimension=dimension,
            from_status=from_status,
            to_status=to_status,
        ),
    )


def save_warning_required(capability: GameSaveCapability) -> bool:
    return capability in {
        GameSaveCapability.UNTESTED,
        GameSaveCapability.MANUAL_SAVE_RECOMMENDED,
        GameSaveCapability.MANUAL_SAVE_REQUIRED,
        GameSaveCapability.UNSAFE_UNKNOWN,
    }
