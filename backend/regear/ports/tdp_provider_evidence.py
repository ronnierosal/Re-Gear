"""Immutable, non-authorizing evidence for future TDP provider discovery.

These records describe values supplied by a synthetic fixture.  They are not
``TdpReading`` objects and therefore cannot be passed to the power writer.
Observed ranges are provider data, not certified device limits.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TdpProviderHostIdentity:
    sys_vendor: str
    product_name: str
    board_name: str
    processor: str


@dataclass(frozen=True, slots=True)
class TdpProviderObservedRange:
    """Untrusted configured-limit values copied from one synthetic fixture."""

    current: int
    minimum: int
    maximum: int


@dataclass(frozen=True, slots=True)
class TdpProviderGpuCandidate:
    stable_id: str
    role: str


@dataclass(frozen=True, slots=True)
class TdpProviderEvidenceResult:
    """Fail-closed interpretation result; this type can never grant control."""

    code: str
    fixture_id: str
    provenance: str = "synthetic_fixture"
    can_control: bool = False
    host: TdpProviderHostIdentity | None = None
    provider_name: str | None = None
    provider_signature: str | None = None
    value_kind: str | None = None
    unit: str | None = None
    observed_range: TdpProviderObservedRange | None = None
    provider_gpu: TdpProviderGpuCandidate | None = None

    def __post_init__(self) -> None:
        if self.provenance != "synthetic_fixture":
            raise ValueError("TDP provider evidence must retain fixture provenance")
        if self.can_control is not False:
            raise ValueError("TDP provider fixture evidence cannot authorize control")
