"""Independent bounded parser for injected InputPlumber public property reads.

No D-Bus library, command runner, filesystem reader or production consumer.
Protocol evidence is pinned in docs/CONTROLLER_PROVIDER_CATALOG.md.
"""

from __future__ import annotations

import re
import math
from dataclasses import dataclass

from ...domain.controller_catalog import (
    CatalogCode, ControllerCatalog, DeviceKind, DeviceObservation, EvidenceState,
    Observation, ProviderInterface,
)
from ...ports.controller_catalog import ControllerProviderReader, PropertyRead, ProviderReadFrame


MANAGER = "org.shadowblip.InputManager"
COMPOSITE = "org.shadowblip.Input.CompositeDevice"
EVENT = "org.shadowblip.Input.Source.EventDevice"
UDEV = "org.shadowblip.Input.Source.UdevDevice"
SOURCES = frozenset({EVENT, UDEV, "org.shadowblip.Input.Source.HIDRawDevice",
                     "org.shadowblip.Input.Source.IIOIMUDevice"})
TARGETS = frozenset({"org.shadowblip.Input.Gamepad", "org.shadowblip.Input.Keyboard",
                     "org.shadowblip.Input.Mouse"})
DBUS = "org.shadowblip.Input.DBusDevice"
RECOGNIZED = SOURCES | TARGETS | {MANAGER, COMPOSITE, DBUS}
PATH = re.compile(r"/(?:[A-Za-z0-9_]+(?:/[A-Za-z0-9_]+)*)?\Z")
INTERFACE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\Z")
EPOCH = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


@dataclass(frozen=True, slots=True)
class CatalogLimits:
    max_objects: int = 128
    max_interfaces: int = 16
    max_properties: int = 64
    max_items: int = 256
    max_string: int = 1024
    max_nodes: int = 32768
    max_depth: int = 8
    max_text_bytes: int = 1048576

    def __post_init__(self) -> None:
        values = (self.max_objects, self.max_interfaces, self.max_properties, self.max_items,
                  self.max_string, self.max_nodes, self.max_depth, self.max_text_bytes)
        ceilings = (128, 16, 64, 256, 1024, 32768, 8, 1048576)
        if any(type(v) is not int or not 0 < v <= ceiling for v, ceiling in zip(values, ceilings)):
            raise ValueError("catalog limits require bounded positive integers")


class _InvalidInput(Exception):
    def __init__(self, code: CatalogCode):
        self.code = code


def _bounded(value: object, limits: CatalogLimits) -> None:
    remaining = limits.max_nodes
    text_remaining = limits.max_text_bytes
    active: set[int] = set()

    def visit(item: object, depth: int) -> None:
        nonlocal remaining, text_remaining
        remaining -= 1
        if remaining < 0 or depth > limits.max_depth:
            raise _InvalidInput(CatalogCode.BOUNDS)
        if type(item) is str:
            if len(item) > limits.max_string:
                raise _InvalidInput(CatalogCode.BOUNDS)
            try:
                text_remaining -= len(item.encode("utf-8"))
            except UnicodeError:
                raise _InvalidInput(CatalogCode.MALFORMED) from None
            if text_remaining < 0:
                raise _InvalidInput(CatalogCode.BOUNDS)
        elif type(item) is float:
            if not math.isfinite(item):
                raise _InvalidInput(CatalogCode.MALFORMED)
        elif type(item) is int:
            if not -(2**63) <= item < 2**64:
                raise _InvalidInput(CatalogCode.BOUNDS)
        elif item is None or type(item) in (bool, EvidenceState):
            return
        elif type(item) is PropertyRead:
            visit(item.state, depth + 1)
            visit(item.value, depth + 1)
        elif type(item) in (dict, tuple, list):
            if len(item) > limits.max_items or id(item) in active:
                raise _InvalidInput(CatalogCode.BOUNDS)
            active.add(id(item))
            if type(item) is dict:
                for k, v in item.items():
                    visit(k, depth + 1)
                    visit(v, depth + 1)
            else:
                for v in item:
                    visit(v, depth + 1)
            active.remove(id(item))
        else:
            raise _InvalidInput(CatalogCode.MALFORMED)
    visit(value, 0)


def _error(code: CatalogCode) -> Observation:
    return Observation(EvidenceState.ERROR, code=code)


def _string(value: object) -> bool:
    return type(value) is str


def _strings(value: object) -> bool:
    return type(value) in (tuple, list) and all(type(v) is str for v in value)


def _paths(value: object) -> bool:
    return _strings(value) and all(PATH.fullmatch(v) for v in value) and len(set(value)) == len(value)


def _keys(value: object) -> bool:
    return type(value) in (tuple, list) and all(type(v) is int and 0 <= v <= 65535 for v in value)


def _read(interfaces: dict, names: frozenset | set, prop: str, valid) -> Observation:
    observations = []
    for name in sorted(names & interfaces.keys()):
        properties = interfaces[name]
        if prop not in properties:
            continue
        raw = properties[prop]
        if type(raw) is not PropertyRead or type(raw.state) is not EvidenceState:
            observations.append(_error(CatalogCode.MALFORMED))
        elif raw.state is not EvidenceState.KNOWN:
            observations.append(Observation(raw.state, code=CatalogCode.READ_UNAVAILABLE)
                                if raw.value is None else _error(CatalogCode.MALFORMED))
        elif valid(raw.value):
            value = tuple(raw.value) if type(raw.value) in (list, tuple) else raw.value
            observations.append(Observation(EvidenceState.KNOWN, value, CatalogCode.OBSERVED))
        else:
            observations.append(_error(CatalogCode.MALFORMED))
    if not observations:
        return Observation()
    if any(v != observations[0] for v in observations[1:]):
        return _error(CatalogCode.CONFLICT)
    return observations[0]


def parse_provider_frame(frame: ProviderReadFrame, *, limits: CatalogLimits = CatalogLimits()) -> ControllerCatalog:
    """Normalize one injected frame, retaining no mutable input or previous state."""
    def failed(code: CatalogCode) -> ControllerCatalog:
        return ControllerCatalog(EvidenceState.ERROR, issues=(code,))

    if type(frame) is not ProviderReadFrame or type(frame.availability) is not EvidenceState:
        return failed(CatalogCode.MALFORMED)
    if frame.availability is not EvidenceState.KNOWN:
        return ControllerCatalog(frame.availability, issues=(CatalogCode.READ_UNAVAILABLE,))
    if (type(frame.connection_epoch) is not str or not EPOCH.fullmatch(frame.connection_epoch)
            or type(frame.enumeration_complete) is not bool or type(frame.objects) is not dict):
        return failed(CatalogCode.MALFORMED)
    try:
        _bounded(frame.objects, limits)
        _bounded(frame.interface_states, limits)
        if len(frame.objects) > limits.max_objects:
            raise _InvalidInput(CatalogCode.BOUNDS)
        for interfaces in frame.objects.values():
            if type(interfaces) is not dict:
                continue
            if len(interfaces) > limits.max_interfaces:
                raise _InvalidInput(CatalogCode.BOUNDS)
            if any(type(props) is dict and len(props) > limits.max_properties
                   for props in interfaces.values()):
                raise _InvalidInput(CatalogCode.BOUNDS)
    except _InvalidInput as error:
        return failed(error.code)
    issues = [] if frame.enumeration_complete else [CatalogCode.PARTIAL]
    devices = []
    managers = []
    present = set()
    if any(type(path) is not str for path in frame.objects):
        issues.append(CatalogCode.MALFORMED)
    for path in sorted(path for path in frame.objects if type(path) is str):
        interfaces = frame.objects[path]
        if (type(path) is not str or not PATH.fullmatch(path) or type(interfaces) is not dict):
            issues.append(CatalogCode.MALFORMED)
            continue
        if any(type(name) is not str or not INTERFACE.fullmatch(name) or type(props) is not dict
               or any(type(p) is not str for p in props)
               for name, props in interfaces.items()):
            issues.append(CatalogCode.MALFORMED)
            continue
        present.update(interfaces)
        if MANAGER in interfaces:
            managers.append({MANAGER: interfaces[MANAGER]})
        kinds = []
        if SOURCES & interfaces.keys():
            kinds.append(DeviceKind.SOURCE)
        if COMPOSITE in interfaces:
            kinds.append(DeviceKind.COMPOSITE)
        if TARGETS & interfaces.keys():
            kinds.append(DeviceKind.TARGET)
        if DBUS in interfaces:
            kinds.append(DeviceKind.DBUS)
        if not kinds and set(interfaces) <= {MANAGER, "org.freedesktop.DBus.Properties", "org.freedesktop.DBus.Introspectable"}:
            continue
        kind = kinds[0] if len(kinds) == 1 else DeviceKind.UNMANAGED
        if len(kinds) > 1:
            issues.append(CatalogCode.CONFLICT)
        composite = {COMPOSITE}
        transport = Observation()
        # Raw dictionaries never enter the pure immutable Observation contract.
        # Only explicitly reported ID_BUS is transport evidence, not IdBustype,
        # the device name, source order, or the presence of an external target.
        udev_properties = interfaces.get(UDEV, {})
        if "Properties" in udev_properties:
            raw_udev = udev_properties["Properties"]
            if type(raw_udev) is not PropertyRead or type(raw_udev.state) is not EvidenceState:
                transport = _error(CatalogCode.MALFORMED)
            elif raw_udev.state is not EvidenceState.KNOWN:
                transport = Observation(raw_udev.state, code=CatalogCode.READ_UNAVAILABLE) if raw_udev.value is None else _error(CatalogCode.MALFORMED)
            elif type(raw_udev.value) is not dict or any(type(k) is not str or type(v) is not str for k, v in raw_udev.value.items()):
                transport = _error(CatalogCode.MALFORMED)
            elif raw_udev.value.get("ID_BUS") in ("usb", "bluetooth"):
                transport = Observation(EvidenceState.KNOWN, raw_udev.value["ID_BUS"], CatalogCode.OBSERVED)
        device = DeviceObservation(
            path, kind, tuple(sorted(interfaces)),
            name=_read(interfaces, RECOGNIZED, "Name", _string),
            persistent_id=_read(interfaces, composite, "PersistentId", _string),
            profile_name=_read(interfaces, composite, "ProfileName", _string),
            profile_path=_read(interfaces, composite, "ProfilePath", _string),
            source_paths=_read(interfaces, composite, "SourceDevicePaths", _paths),
            target_paths=_read(interfaces, composite, "TargetDevices", _paths),
            dbus_paths=_read(interfaces, composite, "DbusDevices", _paths),
            input_capabilities=_read(interfaces, composite, "Capabilities", _strings),
            target_capabilities=_read(interfaces, composite, "TargetCapabilities", _strings),
            output_capabilities=_read(interfaces, composite, "OutputCapabilities", _strings),
            supported_keys=_read(interfaces, {EVENT}, "SupportedKeys", _keys),
            bus_type=_read(interfaces, SOURCES, "IdBustype", _string), transport=transport,
        )
        for value in (device.name, device.persistent_id, device.profile_name, device.profile_path,
                      device.source_paths, device.target_paths, device.dbus_paths,
                      device.input_capabilities, device.target_capabilities, device.output_capabilities,
                      device.supported_keys, device.bus_type, device.transport):
            if value.state is EvidenceState.ERROR:
                issues.append(value.code)
        devices.append(device)
    manager = managers[0] if len(managers) == 1 else {}
    version = _read(manager, {MANAGER}, "Version", _string)
    order = _read(manager, {MANAGER}, "GamepadOrder", _paths)
    if len(managers) > 1:
        version = order = _error(CatalogCode.CONFLICT)
        issues.append(CatalogCode.CONFLICT)
    states = frame.interface_states
    if states is not None and (type(states) is not dict or any(
            type(k) is not str or not INTERFACE.fullmatch(k) or type(v) is not EvidenceState
            for k, v in states.items())):
        issues.append(CatalogCode.MALFORMED)
        states = {}
    states = states or {}
    interface_evidence = []
    for name in sorted(RECOGNIZED | present | states.keys()):
        state = states.get(name, EvidenceState.KNOWN if name in present else EvidenceState.UNKNOWN)
        if name in present and state not in (EvidenceState.KNOWN, EvidenceState.ERROR):
            state = EvidenceState.ERROR
            issues.append(CatalogCode.CONFLICT)
        interface_evidence.append(ProviderInterface(name, state))
    for value in (version, order):
        if value.state is EvidenceState.ERROR:
            issues.append(value.code)
    return ControllerCatalog(EvidenceState.KNOWN, frame.connection_epoch,
                             frame.enumeration_complete and not issues, version,
                             tuple(interface_evidence), tuple(devices), order, tuple(issues))


class InputPlumberCatalogAdapter:
    def __init__(self, reader: ControllerProviderReader, *, limits: CatalogLimits = CatalogLimits()) -> None:
        self._reader = reader
        self._limits = limits

    def collect_catalog(self) -> ControllerCatalog:
        try:
            frame = self._reader.read_snapshot()
        except Exception:
            return ControllerCatalog(EvidenceState.ERROR, issues=(CatalogCode.READER_FAILED,))
        return parse_provider_frame(frame, limits=self._limits)
