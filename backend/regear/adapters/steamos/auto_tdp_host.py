"""Bound Auto TDP configuration to exact host, firmware, kernel and provider.

No serial numbers, machine IDs or MAC addresses are read. The returned digest
is a local compatibility key, not hardware certification or a secret credential.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from ...ports.tdp import TdpReading
from ...profiles.ally_x import PROFILE_ID, matches_ally_x
from .host import HostRecord


@dataclass(frozen=True, slots=True)
class AutoTdpHostContext:
    code: str
    context_key: str | None = None


class AutoTdpHostDiscovery:
    def __init__(self, *, dmi_root: Path = Path("/sys/class/dmi/id"),
                 kernel_release: Path = Path("/proc/sys/kernel/osrelease")):
        self._dmi_root, self._kernel_release = dmi_root, kernel_release

    @staticmethod
    def _text(path: Path) -> str:
        with path.open("rb") as stream:
            raw = stream.read(257)
        if not raw or len(raw) > 256:
            raise ValueError("Host field missing or oversized")
        value = raw.decode("ascii").strip()
        if not value or any(ord(char) < 32 or ord(char) > 126 for char in value):
            raise ValueError("Host field malformed")
        return value

    def _identity(self) -> tuple[str, ...]:
        return tuple(self._text(self._dmi_root / name) for name in
                     ("sys_vendor", "product_name", "board_name", "bios_version", "bios_date")) + (
                         self._text(self._kernel_release),)

    def observe(self, reading: TdpReading) -> AutoTdpHostContext:
        try:
            if not isinstance(reading, TdpReading):
                return AutoTdpHostContext("auto_tdp.provider_context_unknown")
            before = self._identity()
            if not matches_ally_x(HostRecord(*before[:3])):
                return AutoTdpHostContext("auto_tdp.host_unsupported")
            if self._identity() != before:
                return AutoTdpHostContext("auto_tdp.host_context_changed")
            limits = tuple((register.minimum, register.maximum) for register in
                           (reading.sustained, reading.slow, reading.fast))
            payload = (PROFILE_ID, before, reading.binding, limits)
            digest = hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode("ascii")).hexdigest()
            return AutoTdpHostContext("auto_tdp.host_context_observed", digest)
        except Exception:
            return AutoTdpHostContext("auto_tdp.host_context_unavailable")
