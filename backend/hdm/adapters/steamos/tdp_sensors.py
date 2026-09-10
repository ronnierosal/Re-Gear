"""On-demand host sensor inventory, never a control authorization or safety gate.

Tctl is a cooling-control value, not a measured die temperature. Battery terminal
power is not APU consumption; its sign is retained without inferring direction.
Read timestamps bound a sequential scan, not the sensors' hardware sample times.
Sources: kernel hwmon/k10temp, hwmon/sysfs-interface, power/power_supply_class,
and Documentation/ABI/testing/sysfs-class-power.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from time import monotonic


@dataclass(frozen=True, slots=True)
class SensorField:
    state: str = "unknown"
    value: float | str | None = None


@dataclass(frozen=True, slots=True)
class TemperatureChannel:
    channel: int
    label: str
    meaning: str
    celsius: SensorField


@dataclass(frozen=True, slots=True)
class HwmonTemperatureSource:
    ordinal: int
    complete: bool
    channels: tuple[TemperatureChannel, ...]


@dataclass(frozen=True, slots=True)
class PowerSupplySource:
    ordinal: int
    kind: str
    complete: bool
    online: SensorField
    status: SensorField
    battery_terminal_power_watts: SensorField


@dataclass(frozen=True, slots=True)
class TdpSensorInventory:
    started_at: float | None
    finished_at: float | None
    complete: bool
    temperature_status: str
    power_status: str
    temperatures: tuple[HwmonTemperatureSource, ...]
    power_supplies: tuple[PowerSupplySource, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_USB_TYPES = frozenset(("USB", "USB_DCP", "USB_CDP", "USB_ACA", "USB_C", "USB_PD", "USB_PD_DRP"))
_BATTERY_STATUS = {
    "Charging": "charging", "Discharging": "discharging",
    "Not charging": "not_charging", "Full": "full",
}
_ONLINE = {"0": "offline", "1": "online_fixed", "2": "online_programmable"}


class TdpSensorDiscovery:
    """Discover by driver/type; ordinals are local to this scan, not device IDs."""

    MAX_HWMON_ENTRIES = 64
    MAX_CHANNEL_ENTRIES = 256
    MAX_SUPPLY_ENTRIES = 64
    MAX_VALUE_BYTES = 128

    def __init__(self, sys_root: Path = Path("/sys"), *, clock: Callable[[], float] = monotonic) -> None:
        self._root = Path(sys_root)
        self._clock = clock

    def _text(self, path: Path) -> str | None:
        try:
            with path.open("rb") as stream:
                raw = stream.read(self.MAX_VALUE_BYTES + 1)
            if len(raw) > self.MAX_VALUE_BYTES:
                return None
            return raw.decode("ascii").strip(" \t\r\n")
        except (OSError, UnicodeError):
            return None

    @staticmethod
    def _entries(root: Path, limit: int) -> tuple[list[Path], bool]:
        paths = []
        try:
            with os.scandir(root) as entries:
                for count, entry in enumerate(entries):
                    if count >= limit:
                        return sorted(paths), False
                    paths.append(root / entry.name)
        except OSError:
            return sorted(paths), False
        return sorted(paths), True

    def _number(self, path: Path, divisor: int) -> SensorField:
        text = self._text(path)
        if text is None or re.fullmatch(r"-?[0-9]{1,10}", text) is None:
            return SensorField()
        number = int(text)
        if not -(1 << 31) <= number < (1 << 31):
            return SensorField()
        return SensorField("observed", number / divisor)

    def _timestamp(self) -> float | None:
        try:
            value = self._clock()
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                return None
            return float(value)
        except Exception:
            return None

    def _temperatures(self) -> tuple[tuple[HwmonTemperatureSource, ...], bool]:
        paths, complete = self._entries(self._root / "class/hwmon", self.MAX_HWMON_ENTRIES)
        sources = []
        for path in paths:
            name = self._text(path / "name")
            if not name:
                complete = False
                continue
            if name != "k10temp":
                continue
            files, source_complete = self._entries(path, self.MAX_CHANNEL_ENTRIES)
            channels = sorted({
                int(match[1]) for file in files
                if (match := re.fullmatch(r"temp([1-9][0-9]{0,2})_(?:input|label)", file.name))
            })
            observations = []
            for channel in channels:
                label = self._text(path / f"temp{channel}_label")
                if label == "Tctl":
                    meaning = "cooling_control_value"
                elif label == "Tdie":
                    meaning = "die_temperature"
                elif label is not None and re.fullmatch(r"Tccd[1-8]", label):
                    meaning = "ccd_temperature"
                else:
                    label, meaning = "unknown", "unknown"
                    source_complete = False
                value = self._number(path / f"temp{channel}_input", 1000)
                source_complete = source_complete and value.state == "observed"
                observations.append(TemperatureChannel(channel, label, meaning, value))
            source_complete = source_complete and bool(observations)
            sources.append(HwmonTemperatureSource(len(sources), source_complete, tuple(observations)))
            complete = complete and source_complete
        return tuple(sources), complete

    def _power(self) -> tuple[tuple[PowerSupplySource, ...], bool]:
        paths, complete = self._entries(self._root / "class/power_supply", self.MAX_SUPPLY_ENTRIES)
        sources = []
        for path in paths:
            supply_type = self._text(path / "type")
            if supply_type in ("UPS", "Wireless", "BrickID"):
                continue  # Known classes outside this inventory's supported scope.
            online = status = power = SensorField("not_applicable")
            if supply_type == "Battery":
                kind = "battery"
                observed_status = _BATTERY_STATUS.get(self._text(path / "status"))
                status = SensorField("observed", observed_status) if observed_status else SensorField()
                power = self._number(path / "power_now", 1_000_000)
                source_complete = status.state == "observed" and power.state == "observed"
            elif supply_type == "Mains" or supply_type in _USB_TYPES:
                kind = "mains" if supply_type == "Mains" else "usb"
                observed_online = _ONLINE.get(self._text(path / "online"))
                online = SensorField("observed", observed_online) if observed_online else SensorField()
                source_complete = online.state == "observed"
            else:
                kind, source_complete = "unknown", False
                online = status = power = SensorField()
            sources.append(PowerSupplySource(len(sources), kind, source_complete, online, status, power))
            complete = complete and source_complete
        return tuple(sources), complete

    def scan(self) -> TdpSensorInventory:
        started = self._timestamp()
        temperatures, temperature_complete = self._temperatures()
        supplies, power_complete = self._power()
        finished = self._timestamp()
        clock_valid = started is not None and finished is not None and finished >= started
        complete = temperature_complete and power_complete and clock_valid
        # Retain partial observations, but never summarize an incomplete scan as observed.
        temperature_status = "ambiguous" if len(temperatures) > 1 else (
            "observed" if temperatures and complete else "unknown"
        )
        power_status = "observed" if supplies and complete else "unknown"
        return TdpSensorInventory(started, finished, complete, temperature_status, power_status, temperatures, supplies)
