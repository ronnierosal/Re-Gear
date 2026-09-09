"""Read explicit maintainer configuration from the private HDM state directory.

This file records evidence declarations; parsing never certifies a thermal policy
or measures overhead. Missing configuration has no defaults and starts no work.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from ..domain.telemetry import TelemetryCollectionContract, TelemetryConsumer, TelemetryMetric
from ..domain.frame_time_window import FrameWindowPolicy
from .tdp_sensor_readiness import TdpSensorReadinessConfig


FILENAME = "auto-tdp.json"
MAX_BYTES = 8192


@dataclass(frozen=True, slots=True)
class AutoTdpConfiguration:
    host_context_key: str
    sensor_config: TdpSensorReadinessConfig
    thermal_evidence_reference: str
    collection_contract: TelemetryCollectionContract
    benchmark_evidence_reference: str | None


@dataclass(frozen=True, slots=True)
class AutoTdpConfigurationResult:
    code: str
    configuration: AutoTdpConfiguration | None = None


def _shape(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError("Configuration shape is invalid")
    return value


def _reference(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 256
            or not value.strip() or any(ord(char) < 32 for char in value)):
        raise ValueError("Configuration evidence reference is invalid")
    return value


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate configuration key")
        value[key] = item
    return value


def decode_auto_tdp_configuration(raw: bytes) -> AutoTdpConfiguration:
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("Configuration exceeds byte bound")
    value = _shape(json.loads(raw, object_pairs_hook=_unique),
                   ("schema_version", "host_context_key", "thermal", "collection"))
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("Configuration schema is invalid")
    key = value["host_context_key"]
    if not isinstance(key, str) or re.fullmatch(r"[0-9a-f]{64}", key) is None:
        raise ValueError("Configuration host context is invalid")
    thermal = _shape(value["thermal"], ("temperature_label", "temperature_meaning",
        "ceiling_celsius", "maximum_age_seconds", "evidence_reference"))
    sensor = TdpSensorReadinessConfig(**{name: thermal[name] for name in
        ("temperature_label", "temperature_meaning", "ceiling_celsius", "maximum_age_seconds")})
    thermal_reference = _reference(thermal["evidence_reference"])
    collection = _shape(value["collection"], ("interval_ms", "measured_collection_cost_ms",
        "benchmarked", "evidence_reference"))
    contract = TelemetryCollectionContract(TelemetryConsumer.AUTO_TDP,
        (TelemetryMetric.FPS, TelemetryMetric.TEMPERATURE_C, TelemetryMetric.POWER_WATTS),
        collection["interval_ms"], collection["measured_collection_cost_ms"], collection["benchmarked"])
    # The current factory uses the default two-second frame gap. Larger cadence
    # must not appear configured when no frame window can mature at that cadence.
    if contract.interval_ms + contract.measured_collection_cost_ms > FrameWindowPolicy().maximum_gap_ms:
        raise ValueError("Configuration cadence cannot sustain the frame window")
    benchmark_reference = collection["evidence_reference"]
    if contract.benchmarked:
        benchmark_reference = _reference(benchmark_reference)
    elif benchmark_reference is not None:
        raise ValueError("An unbenchmarked configuration cannot claim evidence")
    return AutoTdpConfiguration(key, sensor, thermal_reference, contract, benchmark_reference)


class FileAutoTdpConfiguration:
    def __init__(self, state_root: Path):
        if not state_root.is_absolute() or state_root == Path(state_root.anchor):
            raise ValueError("Configuration state root must be a narrow absolute path")
        self._root = state_root

    @staticmethod
    def _owner(metadata):
        if os.name != "nt" and (metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022):
            raise ValueError("Configuration must not be writable by another owner")

    def load(self) -> AutoTdpConfigurationResult:
        try:
            root = self._root.lstat()
            if not stat.S_ISDIR(root.st_mode) or self._root.is_symlink():
                raise ValueError("Configuration root must be a real directory")
            self._owner(root)
            target = self._root / FILENAME
            try:
                metadata = target.lstat()
            except FileNotFoundError:
                return AutoTdpConfigurationResult("auto_tdp.configuration_missing")
            if not stat.S_ISREG(metadata.st_mode) or target.is_symlink():
                raise ValueError("Configuration must be a regular file")
            self._owner(metadata)
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            descriptor = os.open(target, flags)
            with os.fdopen(descriptor, "rb") as source:
                actual = os.fstat(source.fileno())
                if not stat.S_ISREG(actual.st_mode):
                    raise ValueError("Configuration descriptor is not a regular file")
                self._owner(actual)
                raw = source.read(MAX_BYTES + 1)
            return AutoTdpConfigurationResult("auto_tdp.configuration_loaded", decode_auto_tdp_configuration(raw))
        except Exception:
            return AutoTdpConfigurationResult("auto_tdp.configuration_invalid")
