"""Pure provider observations; never controller ownership or mutation authority."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from typing import Generic, TypeVar


class EvidenceState(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


class CatalogCode(StrEnum):
    OBSERVED = "observed"
    MISSING = "missing"
    READ_UNAVAILABLE = "read_unavailable"
    MALFORMED = "malformed"
    BOUNDS = "bounds_exceeded"
    CONFLICT = "conflicting_observations"
    READER_FAILED = "reader_failed"
    PARTIAL = "partial_enumeration"


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Observation(Generic[T]):
    state: EvidenceState = EvidenceState.UNKNOWN
    value: T | None = None
    code: CatalogCode = CatalogCode.MISSING

    def __post_init__(self) -> None:
        if type(self.state) is not EvidenceState or type(self.code) is not CatalogCode:
            raise ValueError("observation requires categorical state and code")
        if self.state is EvidenceState.KNOWN:
            if self.value is None or self.code is not CatalogCode.OBSERVED:
                raise ValueError("known observation requires an observed value")
            values = self.value if type(self.value) is tuple else (self.value,)
            if any(type(v) not in (str, int, bool) for v in values):
                raise ValueError("observation values must be immutable scalars")
        elif self.value is not None or self.code is CatalogCode.OBSERVED:
            raise ValueError("unavailable observation must not retain a value")


class DeviceKind(StrEnum):
    SOURCE = "provider_source"
    COMPOSITE = "composite"
    TARGET = "virtual_target"
    DBUS = "virtual_dbus"
    UNMANAGED = "unclassified"


class RelationKind(StrEnum):
    SOURCE = "source"
    TARGET = "target"
    DBUS = "dbus"


class RelationState(StrEnum):
    RESOLVED = "resolved"
    MISSING = "missing_object"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class DeviceObservation:
    path: str  # Private, provider-scoped reference; not a stable hardware ID.
    kind: DeviceKind
    interfaces: tuple[str, ...]
    name: Observation[str] = field(default_factory=Observation)
    persistent_id: Observation[str] = field(default_factory=Observation)
    profile_name: Observation[str] = field(default_factory=Observation)
    profile_path: Observation[str] = field(default_factory=Observation)
    source_paths: Observation[tuple[str, ...]] = field(default_factory=Observation)
    target_paths: Observation[tuple[str, ...]] = field(default_factory=Observation)
    dbus_paths: Observation[tuple[str, ...]] = field(default_factory=Observation)
    input_capabilities: Observation[tuple[str, ...]] = field(default_factory=Observation)
    target_capabilities: Observation[tuple[str, ...]] = field(default_factory=Observation)
    output_capabilities: Observation[tuple[str, ...]] = field(default_factory=Observation)
    supported_keys: Observation[tuple[int, ...]] = field(default_factory=Observation)
    bus_type: Observation[str] = field(default_factory=Observation)
    transport: Observation[str] = field(default_factory=Observation)


@dataclass(frozen=True, slots=True)
class ProviderInterface:
    name: str
    state: EvidenceState


@dataclass(frozen=True, slots=True)
class CatalogRelationship:
    composite_path: str
    device_path: str
    kind: RelationKind
    state: RelationState


@dataclass(frozen=True, slots=True)
class ControllerCatalog:
    availability: EvidenceState
    connection_epoch: str = ""  # Supplied by reader; never inferred from paths.
    enumeration_complete: bool = False
    version: Observation[str] = field(default_factory=Observation)
    interfaces: tuple[ProviderInterface, ...] = ()
    devices: tuple[DeviceObservation, ...] = ()
    provider_order: Observation[tuple[str, ...]] = field(default_factory=Observation)
    issues: tuple[CatalogCode, ...] = ()

    def relationships(self) -> tuple[CatalogRelationship, ...]:
        by_path = {d.path: d for d in self.devices}
        edges = []
        for device in self.devices:
            if device.kind is not DeviceKind.COMPOSITE:
                continue
            for kind, observation in ((RelationKind.SOURCE, device.source_paths),
                                      (RelationKind.TARGET, device.target_paths),
                                      (RelationKind.DBUS, device.dbus_paths)):
                for path in observation.value or ():
                    edges.append((device.path, path, kind))
        owners: dict[str, set[str]] = {}
        for composite, path, _kind in edges:
            owners.setdefault(path, set()).add(composite)
        result = []
        for composite, path, kind in edges:
            target = by_path.get(path)
            expected = {RelationKind.SOURCE: {DeviceKind.SOURCE},
                        RelationKind.TARGET: {DeviceKind.TARGET, DeviceKind.DBUS},
                        RelationKind.DBUS: {DeviceKind.DBUS}}[kind]
            state = RelationState.RESOLVED
            if target is None:
                state = RelationState.MISSING
            elif target.kind not in expected or len(owners[path]) != 1:
                state = RelationState.AMBIGUOUS
            result.append(CatalogRelationship(composite, path, kind, state))
        return tuple(result)

    def public_projection(self) -> dict:
        """A safe summary: raw names, IDs, paths, versions/capability text stay private.

        Keys expire with the supplied epoch and are not input/mutation bindings.
        Counts describe observations, not functional or hardware support.
        """
        def key(path: str) -> str:
            return sha256((self.connection_epoch + "\0" + path).encode()).hexdigest()[:24]

        def summary(observation: Observation) -> dict:
            value = observation.value
            return {"state": observation.state.value, "code": observation.code.value,
                    "count": len(value) if type(value) is tuple else None}

        edges = self.relationships()
        devices = []
        for d in self.devices:
            devices.append({"key": key(d.path), "kind": d.kind.value,
                            "name": summary(d.name), "profile": summary(d.profile_name),
                            "input_capabilities": summary(d.input_capabilities),
                            "target_capabilities": summary(d.target_capabilities),
                            "output_capabilities": summary(d.output_capabilities),
                            "supported_keys": summary(d.supported_keys),
                            "transport": summary(d.transport),
                            "source_paths": summary(d.source_paths),
                            "target_paths": summary(d.target_paths),
                            "dbus_paths": summary(d.dbus_paths),
                            "referenced_in_snapshot": any(e.device_path == d.path for e in edges),
                            "physical_origin": None, "builtin": None, "external": None})
        by_path = {d.path: d for d in self.devices}
        return {"provider": "InputPlumber", "availability": self.availability.value,
                "connection_epoch": key("") if self.connection_epoch else None,
                "enumeration_complete": self.enumeration_complete,
                "version": summary(self.version),
                "interfaces": [{"state": i.state.value} for i in self.interfaces],
                "devices": devices,
                "relationships": [{"composite": key(e.composite_path), "device": key(e.device_path),
                                    "kind": e.kind.value, "state": e.state.value} for e in edges],
                "provider_order": {**summary(self.provider_order), "entries": [
                    {"key": key(path), "composite_present": path in by_path and
                     by_path[path].kind is DeviceKind.COMPOSITE}
                    for path in self.provider_order.value or ()]},
                "steam_player_order": None, "effective_targets_verified": False,
                "issues": sorted({i.value for i in self.issues})}
