"""Conservative runtime profile, capability, and diagnostic resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from ..domain.control_plane import (
    CapabilitySupport,
    EgpuCapabilities,
    EffectiveCapabilities,
    HostCapabilities,
    UNKNOWN_EGPU_CAPABILITIES,
    UNKNOWN_HOST_CAPABILITIES,
    compose_capabilities,
)
from ..domain.models import Confidence, GpuRole, ObservedSnapshot, SupportTier
from .ally_x import CAPABILITIES as ALLY_X_CAPABILITIES
from .ally_x import PROFILE_ID as ALLY_X_PROFILE_ID
from .gpd_g1 import CAPABILITIES as GPD_G1_CAPABILITIES
from .gpd_g1 import PROFILE_ID as GPD_G1_PROFILE_ID
from .gpd_g1 import STABLE_ID_PATTERN


class ProfileResolutionStatus(StrEnum):
    EXACT = "exact"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class CapabilityAxis(StrEnum):
    EGPU_SUPPORT = "egpu_support"
    EGPU_TRANSPORT = "egpu_transport"
    EXTERNAL_DISPLAY_OUTPUT = "external_display_output"
    DISPLAY_HANDOFF = "display_handoff"
    EXTERNAL_AUDIO_OUTPUT = "external_audio_output"
    AUDIO_HANDOFF = "audio_handoff"
    INTERNAL_CONTROLLER_SUPPRESSION = "internal_controller_suppression"
    EXTERNAL_CONTROLLER_PROMOTION = "external_controller_promotion"
    EXTERNAL_CONTROLLER_DISCONNECT = "external_controller_disconnect"
    EXTERNAL_CONTROLLER_POWER_OFF = "external_controller_power_off"
    POWER_BUTTON_INTERCEPTION = "power_button_interception"
    SLEEP_BEHAVIOR = "sleep_behavior"
    REMOVAL_BEHAVIOR = "removal_behavior"


class CapabilityEvidenceBasis(StrEnum):
    EXACT_HOST_PROFILE = "exact_host_profile"
    EXACT_EGPU_PROFILE = "exact_egpu_profile"
    COMPOSED_EXACT_PROFILES = "composed_exact_profiles"
    INCOMPLETE_PROFILE_SET = "incomplete_profile_set"


@dataclass(frozen=True, slots=True)
class HostProfileDefinition:
    """A profile already established by independent host discovery."""

    profile_id: str
    capabilities: HostCapabilities

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise ValueError("host profile definition is incomplete")
        if self.capabilities.profile_id != self.profile_id:
            raise ValueError("host profile capability identity does not match")


@dataclass(frozen=True, slots=True)
class EgpuProfileDefinition:
    """A stable-ID matcher plus capability metadata for one explicit eGPU."""

    profile_id: str
    stable_id_pattern: re.Pattern[str]
    capabilities: EgpuCapabilities

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise ValueError("eGPU profile definition is incomplete")
        if self.capabilities.profile_id != self.profile_id:
            raise ValueError("eGPU profile capability identity does not match")


@dataclass(frozen=True, slots=True)
class RuntimeProfileCatalog:
    """Explicit hardware entries only; unknown profiles never inherit a match."""

    hosts: tuple[HostProfileDefinition, ...]
    egpus: tuple[EgpuProfileDefinition, ...]

    def __post_init__(self) -> None:
        host_ids = tuple(item.profile_id for item in self.hosts)
        egpu_ids = tuple(item.profile_id for item in self.egpus)
        if len(host_ids) != len(set(host_ids)) or len(egpu_ids) != len(set(egpu_ids)):
            raise ValueError("runtime profile IDs must be unique")

    def host(self, profile_id: str) -> HostProfileDefinition | None:
        return next((item for item in self.hosts if item.profile_id == profile_id), None)

    def egpu(self, stable_id: str) -> EgpuProfileDefinition | None:
        matches = tuple(
            item for item in self.egpus if item.stable_id_pattern.fullmatch(stable_id)
        )
        return matches[0] if len(matches) == 1 else None


DEFAULT_RUNTIME_PROFILE_CATALOG = RuntimeProfileCatalog(
    hosts=(HostProfileDefinition(ALLY_X_PROFILE_ID, ALLY_X_CAPABILITIES),),
    egpus=(
        EgpuProfileDefinition(
            GPD_G1_PROFILE_ID,
            STABLE_ID_PATTERN,
            GPD_G1_CAPABILITIES,
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class CapabilityDiagnostic:
    axis: CapabilityAxis
    value: str
    confidence: Confidence
    basis: CapabilityEvidenceBasis


@dataclass(frozen=True, slots=True)
class RuntimeProfileDiagnostics:
    host_status: ProfileResolutionStatus
    host_profile_id: str
    egpu_status: ProfileResolutionStatus
    egpu_profile_id: str
    capabilities: tuple[CapabilityDiagnostic, ...]

    def __post_init__(self) -> None:
        axes = tuple(item.axis for item in self.capabilities)
        if len(axes) != len(set(axes)) or set(axes) != set(CapabilityAxis):
            raise ValueError("runtime profile diagnostics must cover each capability axis once")


@dataclass(frozen=True, slots=True)
class ResolvedRuntimeProfiles:
    capabilities: EffectiveCapabilities
    exact_host: bool
    exact_egpu: bool
    host_status: ProfileResolutionStatus
    egpu_status: ProfileResolutionStatus
    egpu_stable_id: str = ""
    egpu_profile_capabilities: EgpuCapabilities = UNKNOWN_EGPU_CAPABILITIES

    def diagnostics(self) -> RuntimeProfileDiagnostics:
        host_basis = (
            CapabilityEvidenceBasis.EXACT_HOST_PROFILE
            if self.exact_host
            else CapabilityEvidenceBasis.INCOMPLETE_PROFILE_SET
        )
        egpu_basis = (
            CapabilityEvidenceBasis.EXACT_EGPU_PROFILE
            if self.exact_egpu
            else CapabilityEvidenceBasis.INCOMPLETE_PROFILE_SET
        )
        composed_basis = (
            CapabilityEvidenceBasis.COMPOSED_EXACT_PROFILES
            if self.exact_host and self.exact_egpu
            else CapabilityEvidenceBasis.INCOMPLETE_PROFILE_SET
        )
        egpu = self.egpu_profile_capabilities
        effective = self.capabilities
        return RuntimeProfileDiagnostics(
            host_status=self.host_status,
            host_profile_id=effective.host_profile_id,
            egpu_status=self.egpu_status,
            egpu_profile_id=effective.egpu_profile_id,
            capabilities=(
                _capability(
                    CapabilityAxis.EGPU_SUPPORT,
                    effective.egpu_support,
                    host_basis,
                ),
                _capability(
                    CapabilityAxis.EGPU_TRANSPORT,
                    effective.egpu_transport,
                    host_basis,
                    exact=self.exact_host,
                ),
                _capability(
                    CapabilityAxis.EXTERNAL_DISPLAY_OUTPUT,
                    egpu.display_output,
                    egpu_basis,
                ),
                _capability(
                    CapabilityAxis.DISPLAY_HANDOFF,
                    effective.display_handoff,
                    composed_basis,
                ),
                _capability(
                    CapabilityAxis.EXTERNAL_AUDIO_OUTPUT,
                    egpu.audio_output,
                    egpu_basis,
                ),
                _capability(
                    CapabilityAxis.AUDIO_HANDOFF,
                    effective.audio_handoff,
                    composed_basis,
                ),
                _capability(
                    CapabilityAxis.INTERNAL_CONTROLLER_SUPPRESSION,
                    effective.internal_controller_suppression,
                    host_basis,
                ),
                _capability(
                    CapabilityAxis.EXTERNAL_CONTROLLER_PROMOTION,
                    effective.external_controller_promotion,
                    host_basis,
                ),
                _capability(
                    CapabilityAxis.EXTERNAL_CONTROLLER_DISCONNECT,
                    effective.external_controller_disconnect,
                    host_basis,
                ),
                _capability(
                    CapabilityAxis.EXTERNAL_CONTROLLER_POWER_OFF,
                    effective.external_controller_power_off,
                    host_basis,
                ),
                _capability(
                    CapabilityAxis.POWER_BUTTON_INTERCEPTION,
                    effective.power_button_interception,
                    host_basis,
                ),
                _capability(
                    CapabilityAxis.SLEEP_BEHAVIOR,
                    effective.sleep_behavior,
                    egpu_basis,
                    exact=self.exact_egpu,
                ),
                _capability(
                    CapabilityAxis.REMOVAL_BEHAVIOR,
                    effective.removal_behavior,
                    egpu_basis,
                    exact=self.exact_egpu,
                ),
            ),
        )


def _support_confidence(value: CapabilitySupport) -> Confidence:
    if value in (CapabilitySupport.VERIFIED, CapabilitySupport.UNSUPPORTED):
        return Confidence.VERIFIED
    if value is CapabilitySupport.EXPERIMENTAL:
        return Confidence.OBSERVED
    return Confidence.UNKNOWN


def _capability(
    axis: CapabilityAxis,
    value: StrEnum,
    basis: CapabilityEvidenceBasis,
    *,
    exact: bool | None = None,
) -> CapabilityDiagnostic:
    if isinstance(value, CapabilitySupport):
        confidence = _support_confidence(value)
    else:
        confidence = (
            Confidence.VERIFIED
            if exact and value.value not in {"unknown", "untested"}
            else Confidence.UNKNOWN
        )
    return CapabilityDiagnostic(axis, value.value, confidence, basis)


def _egpu_status(snapshot: ObservedSnapshot, *, exact: bool) -> ProfileResolutionStatus:
    if exact:
        return ProfileResolutionStatus.EXACT
    if any(
        blocker.code in {"drm_inventory_unavailable", "egpu_identity_unverified"}
        for blocker in snapshot.blockers
    ):
        return ProfileResolutionStatus.UNKNOWN
    if not snapshot.gpus:
        return ProfileResolutionStatus.UNKNOWN
    if any(gpu.present and gpu.role is not GpuRole.INTERNAL for gpu in snapshot.gpus):
        return ProfileResolutionStatus.UNKNOWN
    verified_internal = tuple(
        gpu
        for gpu in snapshot.gpus
        if gpu.present
        and gpu.role is GpuRole.INTERNAL
        and gpu.confidence is Confidence.VERIFIED
    )
    return (
        ProfileResolutionStatus.ABSENT
        if len(verified_internal) == 1
        else ProfileResolutionStatus.UNKNOWN
    )


def resolve_runtime_profiles(
    snapshot: ObservedSnapshot,
    catalog: RuntimeProfileCatalog = DEFAULT_RUNTIME_PROFILE_CATALOG,
) -> ResolvedRuntimeProfiles:
    host_definition = catalog.host(snapshot.host_profile)
    exact_host = (
        host_definition is not None
        and not any(
            blocker.code == "host_profile_unknown" for blocker in snapshot.blockers
        )
    )
    host = host_definition.capabilities if exact_host else UNKNOWN_HOST_CAPABILITIES
    external = tuple(
        gpu
        for gpu in snapshot.gpus
        if gpu.role is GpuRole.EXTERNAL
        and gpu.present
        and gpu.confidence is Confidence.VERIFIED
    )
    egpu_definition = catalog.egpu(external[0].stable_id) if len(external) == 1 else None
    exact_egpu = (
        len(external) == 1
        and egpu_definition is not None
        and snapshot.support_tier is SupportTier.CERTIFIED
        and snapshot.disconnect_readiness.applicable
        and snapshot.disconnect_readiness.egpu_stable_id == external[0].stable_id
        and not any(
            blocker.code == "egpu_identity_unverified" for blocker in snapshot.blockers
        )
    )
    egpu = (
        egpu_definition.capabilities
        if exact_egpu and egpu_definition is not None
        else UNKNOWN_EGPU_CAPABILITIES
    )
    return ResolvedRuntimeProfiles(
        capabilities=compose_capabilities(host, egpu),
        exact_host=exact_host,
        exact_egpu=exact_egpu,
        host_status=(
            ProfileResolutionStatus.EXACT
            if exact_host
            else ProfileResolutionStatus.UNKNOWN
        ),
        egpu_status=_egpu_status(snapshot, exact=exact_egpu),
        egpu_stable_id=external[0].stable_id if exact_egpu else "",
        egpu_profile_capabilities=egpu,
    )


def runtime_profile_diagnostics_to_dict(
    diagnostics: RuntimeProfileDiagnostics,
) -> dict[str, object]:
    """Serialize only categorical, privacy-safe profile capability evidence."""
    return {
        "schema_version": 1,
        "host": {
            "status": diagnostics.host_status.value,
            "profile_id": diagnostics.host_profile_id,
        },
        "egpu": {
            "status": diagnostics.egpu_status.value,
            "profile_id": diagnostics.egpu_profile_id,
        },
        "capabilities": [
            {
                "axis": capability.axis.value,
                "value": capability.value,
                "confidence": capability.confidence.value,
                "basis": capability.basis.value,
            }
            for capability in diagnostics.capabilities
        ],
    }
