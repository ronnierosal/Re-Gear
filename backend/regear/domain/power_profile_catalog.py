"""Strict, non-authorizing handheld APU power-profile catalog contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .control_plane import PlacementState
from .power_modes import PowerMode


STABLE_PLACEMENTS = frozenset(
    {
        PlacementState.PORTABLE,
        PlacementState.BOOSTED_HANDHELD,
        PlacementState.DOCKED_IGPU,
        PlacementState.DOCKED_EGPU,
    }
)


class PowerSource(StrEnum):
    BATTERY = "battery"
    AC = "ac"


class PowerRangeKind(StrEnum):
    PUBLISHED_APU_TDP = "published_apu_tdp"
    OEM_CUSTOM_MODE = "oem_custom_mode"


def _text(value: object, label: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} is required")


def _watts(value: object, label: str) -> None:
    if type(value) is not int or not 0 < value <= 0xFFFFFFFF:
        raise ValueError(f"{label} must be positive integer watts")


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    manufacturer: str
    model: str
    variant: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.manufacturer, "manufacturer"),
            (self.model, "model"),
            (self.variant, "variant"),
        ):
            _text(value, label)


@dataclass(frozen=True, slots=True)
class ProviderBinding:
    provider_id: str
    binding_id: str

    def __post_init__(self) -> None:
        _text(self.provider_id, "provider ID")
        _text(self.binding_id, "provider binding ID")


@dataclass(frozen=True, slots=True)
class SourceReference:
    source_id: str
    url: str
    context: str

    def __post_init__(self) -> None:
        _text(self.source_id, "source ID")
        if type(self.url) is not str or not self.url.startswith("https://"):
            raise ValueError("source URL must be HTTPS")
        _text(self.context, "source context")


@dataclass(frozen=True, slots=True)
class EvidenceDimensions:
    researched: bool = False
    source_conflicted: bool = False
    backend_discovered: bool = False
    fixture_tested: bool = False
    write_tested: bool = False
    restore_tested: bool = False
    hardware_validated: bool = False

    def __post_init__(self) -> None:
        if any(type(value) is not bool for value in (
            self.researched,
            self.source_conflicted,
            self.backend_discovered,
            self.fixture_tested,
            self.write_tested,
            self.restore_tested,
            self.hardware_validated,
        )):
            raise ValueError("evidence dimensions must be explicit booleans")


@dataclass(frozen=True, slots=True)
class DocumentedPowerRange:
    minimum_watts: int
    maximum_watts: int
    kind: PowerRangeKind
    source: SourceReference

    def __post_init__(self) -> None:
        _watts(self.minimum_watts, "documented minimum")
        _watts(self.maximum_watts, "documented maximum")
        if self.minimum_watts > self.maximum_watts:
            raise ValueError("documented power range is reversed")
        if type(self.kind) is not PowerRangeKind:
            raise ValueError("documented power range kind is invalid")
        if type(self.source) is not SourceReference:
            raise ValueError("documented range requires source provenance")


@dataclass(frozen=True, slots=True)
class OemModeClaim:
    name: str
    watts: int
    power_source: PowerSource | None
    source: SourceReference

    def __post_init__(self) -> None:
        _text(self.name, "OEM mode name")
        _watts(self.watts, "OEM claimed power")
        if self.power_source is not None and type(self.power_source) is not PowerSource:
            raise ValueError("OEM power source is invalid")
        if type(self.source) is not SourceReference:
            raise ValueError("OEM mode claim requires source provenance")


@dataclass(frozen=True, slots=True)
class NativePowerProfile:
    """An exact named backend target; never a derived point in a watt range."""

    mode: PowerMode
    native_profile_id: str
    target_watts: int
    provider: ProviderBinding
    power_source: PowerSource
    placement: PlacementState
    evidence: EvidenceDimensions
    sources: tuple[SourceReference, ...]

    def __post_init__(self) -> None:
        if self.mode not in {
            PowerMode.BATTERY_SAVER,
            PowerMode.BALANCED,
            PowerMode.PERFORMANCE,
        }:
            raise ValueError("native profiles support only exact named manual modes")
        _text(self.native_profile_id, "native profile ID")
        _watts(self.target_watts, "native profile target")
        if type(self.provider) is not ProviderBinding:
            raise ValueError("native profile provider binding is invalid")
        if type(self.power_source) is not PowerSource:
            raise ValueError("native profile power source is invalid")
        if type(self.placement) is not PlacementState or self.placement not in STABLE_PLACEMENTS:
            raise ValueError("native profile requires an exact stable placement")
        if type(self.evidence) is not EvidenceDimensions:
            raise ValueError("native profile evidence is invalid")
        if type(self.sources) is not tuple or not self.sources or any(
            type(source) is not SourceReference for source in self.sources
        ):
            raise ValueError("native profile requires immutable source provenance")


@dataclass(frozen=True, slots=True)
class DevicePowerProfile:
    identity: DeviceIdentity
    evidence: EvidenceDimensions
    sources: tuple[SourceReference, ...]
    documented_range: DocumentedPowerRange | None = None
    oem_claims: tuple[OemModeClaim, ...] = ()
    native_profiles: tuple[NativePowerProfile, ...] = ()

    def __post_init__(self) -> None:
        if type(self.identity) is not DeviceIdentity or type(self.evidence) is not EvidenceDimensions:
            raise ValueError("device power profile identity or evidence is invalid")
        if type(self.sources) is not tuple or not self.sources or any(
            type(source) is not SourceReference for source in self.sources
        ):
            raise ValueError("device power profile needs immutable sources")
        if self.documented_range is not None and type(self.documented_range) is not DocumentedPowerRange:
            raise ValueError("documented range is invalid")
        if type(self.oem_claims) is not tuple or any(type(item) is not OemModeClaim for item in self.oem_claims):
            raise ValueError("OEM claims must be immutable validated claims")
        if type(self.native_profiles) is not tuple or any(
            type(item) is not NativePowerProfile for item in self.native_profiles
        ):
            raise ValueError("native profiles must be immutable validated profiles")
        keys = tuple(
            (item.mode, item.provider, item.power_source, item.placement)
            for item in self.native_profiles
        )
        if len(keys) != len(set(keys)):
            raise ValueError("native profile binding is ambiguous")


@dataclass(frozen=True, slots=True)
class PowerProfileCatalog:
    version: int
    profiles: tuple[DevicePowerProfile, ...]

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version <= 0:
            raise ValueError("catalog version must be a positive integer")
        if type(self.profiles) is not tuple or not self.profiles or any(
            type(profile) is not DevicePowerProfile for profile in self.profiles
        ):
            raise ValueError("catalog requires immutable device profiles")
        identities = tuple(profile.identity for profile in self.profiles)
        if len(identities) != len(set(identities)):
            raise ValueError("catalog device identities must be unique")


@dataclass(frozen=True, slots=True)
class CurrentPowerEvidence:
    identity: DeviceIdentity
    provider: ProviderBinding
    power_source: PowerSource
    placement: PlacementState
    generation: int
    observed_generation: int
    minimum_watts: int | None
    maximum_watts: int | None
    identity_verified: bool
    binding_verified: bool
    range_verified: bool
    restoration_verified: bool
    ownership_verified: bool
    context_verified: bool
    evidence_id: str

    def __post_init__(self) -> None:
        if type(self.identity) is not DeviceIdentity or type(self.provider) is not ProviderBinding:
            raise ValueError("current power identity or provider is invalid")
        if type(self.power_source) is not PowerSource:
            raise ValueError("current power source is invalid")
        if type(self.placement) is not PlacementState:
            raise ValueError("current placement is invalid")
        for value, label in ((self.generation, "generation"), (self.observed_generation, "observed generation")):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{label} must be a positive integer")
        if (self.minimum_watts is None) != (self.maximum_watts is None):
            raise ValueError("provider bounds must be supplied together")
        if self.minimum_watts is not None:
            _watts(self.minimum_watts, "provider minimum")
            _watts(self.maximum_watts, "provider maximum")
            if self.minimum_watts > self.maximum_watts:
                raise ValueError("provider bounds are reversed")
        flags = (
            self.identity_verified,
            self.binding_verified,
            self.range_verified,
            self.restoration_verified,
            self.ownership_verified,
            self.context_verified,
        )
        if any(type(flag) is not bool for flag in flags):
            raise ValueError("current power evidence flags must be booleans")
        _text(self.evidence_id, "current evidence ID")


@dataclass(frozen=True, slots=True)
class CatalogEvaluationProvenance:
    catalog_version: int | None = None
    evidence_id: str = ""
    current_generation: int | None = None
    observed_generation: int | None = None

    def __post_init__(self) -> None:
        if self.catalog_version is not None and (
            type(self.catalog_version) is not int or self.catalog_version <= 0
        ):
            raise ValueError("evaluation catalog version is invalid")
        generations = (self.current_generation, self.observed_generation)
        if any(value is not None for value in generations):
            if any(type(value) is not int or value <= 0 for value in generations):
                raise ValueError("evaluation generations must be supplied together")
            _text(self.evidence_id, "evaluation evidence ID")
        elif self.evidence_id:
            raise ValueError("evaluation evidence ID requires generations")


@dataclass(frozen=True, slots=True)
class PowerProfileResolution:
    requested_mode: PowerMode | None
    profile: NativePowerProfile | None
    follow_system: bool
    code: str
    provenance: CatalogEvaluationProvenance

    def __post_init__(self) -> None:
        if self.requested_mode is not None and type(self.requested_mode) is not PowerMode:
            raise ValueError("resolution requested mode is invalid")
        if self.profile is not None and type(self.profile) is not NativePowerProfile:
            raise ValueError("resolution native profile is invalid")
        if type(self.follow_system) is not bool:
            raise ValueError("resolution system fallback flag is invalid")
        _text(self.code, "resolution code")
        if type(self.provenance) is not CatalogEvaluationProvenance:
            raise ValueError("resolution provenance is invalid")

    @property
    def available(self) -> bool:
        return self.profile is not None

    @property
    def authorizes_activation(self) -> bool:
        return False


def resolve_power_profile(
    catalog: PowerProfileCatalog,
    requested_mode: PowerMode,
    current: CurrentPowerEvidence,
) -> PowerProfileResolution:
    """Resolve one exact validated named target without deriving or clamping."""
    valid_catalog = type(catalog) is PowerProfileCatalog
    valid_current = type(current) is CurrentPowerEvidence
    provenance = CatalogEvaluationProvenance(
        catalog_version=catalog.version if valid_catalog else None,
        evidence_id=current.evidence_id if valid_current else "",
        current_generation=current.generation if valid_current else None,
        observed_generation=current.observed_generation if valid_current else None,
    )
    valid_mode = type(requested_mode) is PowerMode
    declined = lambda code: PowerProfileResolution(
        requested_mode if valid_mode else None,
        None,
        True,
        code,
        provenance,
    )
    if not valid_catalog or not valid_current:
        return declined("power_profile.input_invalid")
    if not valid_mode:
        return declined("power_profile.mode_invalid")
    if requested_mode is PowerMode.SYSTEM_CONTROL:
        return declined("power_profile.follow_system")
    if requested_mode is PowerMode.AUTO:
        return declined("power_profile.auto_requires_runtime_admission")
    if current.placement not in STABLE_PLACEMENTS:
        return declined("power_profile.placement_unresolved")
    if current.generation != current.observed_generation:
        return declined("power_profile.generation_stale")
    checks = (
        (current.identity_verified, "identity_unverified"),
        (current.binding_verified, "binding_unverified"),
        (current.range_verified, "range_unverified"),
        (current.restoration_verified, "restoration_unverified"),
        (current.ownership_verified, "ownership_unverified"),
        (current.context_verified, "context_unverified"),
    )
    for passed, suffix in checks:
        if passed is not True:
            return declined(f"power_profile.{suffix}")
    if current.minimum_watts is None or current.maximum_watts is None:
        return declined("power_profile.range_missing")
    devices = tuple(profile for profile in catalog.profiles if profile.identity == current.identity)
    if len(devices) != 1:
        return declined("power_profile.device_missing_or_ambiguous")
    device = devices[0]
    matches = tuple(
        profile
        for profile in device.native_profiles
        if profile.mode is requested_mode
        and profile.provider == current.provider
        and profile.power_source is current.power_source
        and profile.placement is current.placement
    )
    if len(matches) != 1:
        return declined("power_profile.named_profile_missing_or_ambiguous")
    profile = matches[0]
    evidence = profile.evidence
    if evidence.source_conflicted or not (
        evidence.backend_discovered
        and evidence.write_tested
        and evidence.restore_tested
        and evidence.hardware_validated
    ):
        return declined("power_profile.native_validation_incomplete")
    if not current.minimum_watts <= profile.target_watts <= current.maximum_watts:
        return declined("power_profile.target_outside_verified_range")
    return PowerProfileResolution(
        requested_mode,
        profile,
        False,
        "power_profile.exact_non_authorizing_match",
        provenance,
    )
