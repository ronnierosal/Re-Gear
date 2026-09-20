"""Bounded read-only cooling evidence for one exact PCI eGPU.

This adapter never writes PWM, fan, power, driver or transport state.  It only
reports controls that the loaded GPU driver already exposes through hwmon.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Callable
from pathlib import Path
from time import monotonic

from ...domain.prepared_egpu_disconnect import EgpuCoolingEvidence


class EgpuCoolingDiscovery:
    MAX_HWMON_ENTRIES = 8
    MAX_HWMON_FILES = 128
    MAX_VALUE_BYTES = 128

    def __init__(
        self,
        pci_root: Path = Path("/sys/bus/pci/devices"),
        *,
        clock: Callable[[], float] = monotonic,
        device_path: Callable[[str], Path] | None = None,
        driver_name: Callable[[Path], str] | None = None,
    ) -> None:
        self._pci_root = Path(pci_root)
        self._clock = clock
        self._device_path = device_path or (lambda bdf: self._pci_root / bdf)
        self._driver_name_reader = driver_name or self._driver_name

    def _text(self, path: Path) -> str | None:
        try:
            with path.open("rb") as source:
                value = source.read(self.MAX_VALUE_BYTES + 1)
            if len(value) > self.MAX_VALUE_BYTES:
                return None
            return value.decode("ascii").strip(" \t\r\n")
        except (OSError, UnicodeError):
            return None

    @staticmethod
    def _entries(path: Path, limit: int) -> tuple[tuple[Path, ...], bool]:
        found: list[Path] = []
        try:
            with os.scandir(path) as entries:
                for index, entry in enumerate(entries):
                    if index >= limit:
                        return tuple(sorted(found)), False
                    found.append(path / entry.name)
        except OSError:
            return tuple(sorted(found)), False
        return tuple(sorted(found)), True

    def _timestamp(self) -> float | None:
        try:
            value = self._clock()
        except Exception:
            return None
        if (
            type(value) not in (int, float)
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < 0
        ):
            return None
        return float(value)

    def _integer(self, path: Path, *, maximum: int) -> int | None:
        value = self._text(path)
        if value is None or re.fullmatch(r"[0-9]{1,10}", value) is None:
            return None
        parsed = int(value)
        return parsed if 0 <= parsed <= maximum else None

    @staticmethod
    def _driver_name(device: Path) -> str:
        try:
            driver = (device / "driver").resolve(strict=True)
            return driver.name if driver.is_dir() else ""
        except (OSError, RuntimeError):
            return ""

    def scan(
        self,
        *,
        gpu_bdf: str,
        attachment_binding: str,
        generation: str,
    ) -> EgpuCoolingEvidence:
        if (
            type(gpu_bdf) is not str
            or re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]", gpu_bdf)
            is None
            or type(attachment_binding) is not str
            or not attachment_binding
            or type(generation) is not str
            or not generation
        ):
            return EgpuCoolingEvidence("", "", "", False, "", False)

        started = self._timestamp()
        try:
            device = Path(self._device_path(gpu_bdf))
        except Exception:
            device = self._pci_root / "invalid"
        present = device.is_dir()
        try:
            driver = self._driver_name_reader(device) if present else ""
        except Exception:
            driver = ""
        if type(driver) is not str:
            driver = ""
        roots, roots_complete = self._entries(device / "hwmon", self.MAX_HWMON_ENTRIES)
        matches = tuple(root for root in roots if self._text(root / "name") == "amdgpu")

        temperatures: list[float] = []
        fan_rpm = None
        automatic = None
        source_complete = roots_complete and len(matches) == 1
        if len(matches) == 1:
            source = matches[0]
            files, files_complete = self._entries(source, self.MAX_HWMON_FILES)
            source_complete = source_complete and files_complete
            channels = sorted(
                {
                    int(match.group(1))
                    for file in files
                    if (match := re.fullmatch(r"temp([1-9][0-9]{0,2})_input", file.name))
                }
            )
            for channel in channels:
                millidegrees = self._integer(
                    source / f"temp{channel}_input", maximum=200_000
                )
                if millidegrees is None:
                    source_complete = False
                else:
                    temperatures.append(millidegrees / 1000)
            fan_rpm = self._integer(source / "fan1_input", maximum=1_000_000)
            pwm_mode = self._integer(source / "pwm1_enable", maximum=255)
            automatic = pwm_mode == 2 if pwm_mode is not None else None
            source_complete = (
                source_complete
                and bool(temperatures)
                and fan_rpm is not None
                and automatic is not None
            )

        finished = self._timestamp()
        clock_valid = (
            started is not None and finished is not None and finished >= started
        )
        complete = (
            present
            and driver == "amdgpu"
            and source_complete
            and clock_valid
        )
        return EgpuCoolingEvidence(
            attachment_binding,
            generation,
            gpu_bdf,
            present,
            driver,
            complete,
            tuple(temperatures),
            fan_rpm,
            automatic,
        )
