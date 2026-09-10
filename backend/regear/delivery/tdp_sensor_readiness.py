"""Assess explicit temperature/power evidence without hardware authorization.

The ceiling is caller-supplied policy evidence, never a discovered safe limit.
In current k10temp source temp1_max is a legacy value hidden on Zen; temp1_crit
depends on available/enabled HTC registers. Neither supplies a universal APU
ceiling. A future profile must bind a documented operating ceiling and sensor
meaning to the exact hardware/firmware and validate it before live control.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass

from ..adapters.steamos.tdp_sensors import TdpSensorInventory


def _finite(value: object) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True, slots=True)
class TdpSensorReadinessConfig:
    temperature_label: str
    temperature_meaning: str
    ceiling_celsius: float
    maximum_age_seconds: float

    def __post_init__(self) -> None:
        meaning = {
            "Tctl": "cooling_control_value",
            "Tdie": "die_temperature",
        }.get(self.temperature_label) if type(self.temperature_label) is str else None
        if type(self.temperature_label) is str and re.fullmatch(r"Tccd(?:[1-9]|1[0-6])", self.temperature_label):
            meaning = "ccd_temperature"
        if meaning is None or self.temperature_meaning != meaning:
            raise ValueError("Temperature label and meaning must agree")
        if not _finite(self.ceiling_celsius) or self.ceiling_celsius <= 0:
            raise ValueError("An explicit finite positive operating ceiling is required")
        if not _finite(self.maximum_age_seconds) or self.maximum_age_seconds <= 0:
            raise ValueError("An explicit finite positive evidence age is required")


@dataclass(frozen=True, slots=True)
class TdpSensorReadiness:
    code: str
    thermal_state: str = "unknown"
    power_source: str = "unknown"
    temperature_celsius: float | None = None
    configured_ceiling_celsius: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _power_source(inventory: TdpSensorInventory) -> str:
    supplies = inventory.power_supplies
    if not supplies or any(source.complete is not True or source.kind not in ("battery", "mains", "usb") for source in supplies):
        return "unknown"
    batteries = [source for source in supplies if source.kind == "battery"]
    external = [source for source in supplies if source.kind in ("mains", "usb")]
    # The inventory cannot identify a host battery among several peripherals.
    if len(batteries) != 1 or not external:
        return "unknown"
    battery = batteries[0]
    if battery.status.state != "observed" or battery.status.value not in ("charging", "discharging", "not_charging", "full"):
        return "unknown"
    power = battery.battery_terminal_power_watts
    if power.state != "observed" or not _finite(power.value):
        return "unknown"
    if any(source.online.state != "observed" or source.online.value not in ("offline", "online_fixed", "online_programmable") for source in external):
        return "unknown"
    online = {source.online.value != "offline" for source in external}
    # Different ports can legitimately be offline and online simultaneously.
    # Any observed external source is sufficient here, not a power-budget claim.
    if True in online:
        return "external" if battery.status.value != "discharging" else "unknown"
    if battery.status.value == "discharging" and abs(power.value) > 0:
        return "battery_discharge"
    return "unknown"


def assess_tdp_sensor_readiness(
    inventory: TdpSensorInventory,
    config: TdpSensorReadinessConfig,
    *,
    now: float,
) -> TdpSensorReadiness:
    """Compare fresh explicit evidence; this result grants no write capability."""
    if not isinstance(config, TdpSensorReadinessConfig):
        return TdpSensorReadiness("tdp.sensor_configuration_unknown")
    if not isinstance(inventory, TdpSensorInventory) or inventory.complete is not True:
        return TdpSensorReadiness("tdp.sensors_incomplete")
    started, finished = inventory.started_at, inventory.finished_at
    if (
        not all(_finite(value) for value in (now, started, finished))
        or not 0 <= started <= finished <= now
        or now - started > config.maximum_age_seconds
    ):
        return TdpSensorReadiness("tdp.sensors_stale")
    if inventory.temperature_status != "observed" or inventory.power_status != "observed" or len(inventory.temperatures) != 1:
        return TdpSensorReadiness("tdp.sensor_sources_unknown")
    source = inventory.temperatures[0]
    if source.complete is not True:
        return TdpSensorReadiness("tdp.temperature_unknown")
    matches = [channel for channel in source.channels if channel.label == config.temperature_label]
    if len(matches) != 1 or matches[0].meaning != config.temperature_meaning:
        return TdpSensorReadiness("tdp.temperature_unknown")
    reading = matches[0].celsius
    if reading.state != "observed" or not _finite(reading.value) or reading.value < 0:
        return TdpSensorReadiness("tdp.temperature_unknown")
    thermal = "below_ceiling" if reading.value < config.ceiling_celsius else "at_or_above_ceiling"
    power = _power_source(inventory)
    code = (
        "tdp.thermal_ceiling_reached" if thermal == "at_or_above_ceiling" else
        "tdp.power_source_unknown" if power == "unknown" else
        "tdp.sensor_evidence_observed"
    )
    return TdpSensorReadiness(code, thermal, power, reading.value, config.ceiling_celsius)
