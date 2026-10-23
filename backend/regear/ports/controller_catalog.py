"""Injected, transport-free InputPlumber read envelope. No reader is installed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..domain.controller_catalog import ControllerCatalog, EvidenceState


@dataclass(frozen=True, slots=True)
class PropertyRead:
    """One decoded property reply or a categorical read failure; no error text."""

    state: EvidenceState = EvidenceState.UNKNOWN
    value: object = None


@dataclass(frozen=True, slots=True)
class ProviderReadFrame:
    """Fixture envelope, NOT a claim that GetManagedObjects/transport exists.

    objects: {object_path: {interface_name: {property_name: PropertyRead}}}.
    interface_states: explicit {interface_name: EvidenceState}; absence is unknown.
    The future reader owns coherent enumeration and epoch invalidation.
    """

    connection_epoch: str
    objects: object
    availability: EvidenceState = EvidenceState.KNOWN
    enumeration_complete: bool = False
    interface_states: object = None


class ControllerProviderReader(Protocol):
    def read_snapshot(self) -> ProviderReadFrame:
        """Return one bounded decoded read frame; no mutation/capture methods."""


class ControllerCatalogPort(Protocol):
    def collect_catalog(self) -> ControllerCatalog:
        """Return fresh observations; never fall back to a previously read frame."""
