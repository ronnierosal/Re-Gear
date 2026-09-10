"""Read-only categorical PCI wake-capability observation for exact eGPU topology."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


PCI_BDF_RE = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]$")


class WakeCapabilityState(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    UNKNOWN = "unknown"


class RuntimePowerState(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class WakeDiagnosticsObservation:
    """Aggregate only; PCI identities remain private to the caller."""

    applicable: bool
    bridge_wakeup: WakeCapabilityState = WakeCapabilityState.UNKNOWN
    function_wakeup_enabled: int = 0
    function_wakeup_disabled: int = 0
    function_wakeup_unknown: int = 0
    function_runtime_active: int = 0
    function_runtime_suspended: int = 0
    function_runtime_unknown: int = 0
    reason: str = ""

    def __post_init__(self) -> None:
        counts = (
            self.function_wakeup_enabled,
            self.function_wakeup_disabled,
            self.function_wakeup_unknown,
            self.function_runtime_active,
            self.function_runtime_suspended,
            self.function_runtime_unknown,
        )
        if any(value < 0 or value > 64 for value in counts):
            raise ValueError("wake diagnostic count is invalid")
        if not self.applicable and any(counts):
            raise ValueError("inapplicable wake diagnostics cannot carry counts")

    def to_public_dict(self) -> dict[str, object]:
        """Return only categorical aggregate evidence for remote support capture."""
        return {
            "applicable": self.applicable,
            "bridge_wakeup": self.bridge_wakeup.value,
            "function_wakeup": {
                "enabled": self.function_wakeup_enabled,
                "disabled": self.function_wakeup_disabled,
                "unknown": self.function_wakeup_unknown,
            },
            "function_runtime": {
                "active": self.function_runtime_active,
                "suspended": self.function_runtime_suspended,
                "unknown": self.function_runtime_unknown,
            },
            "reason": self.reason,
        }


class WakeDiagnosticsDiscovery:
    """Reads existing sysfs attributes and never changes wake or power state."""

    def __init__(
        self,
        sysfs_root: Path = Path("/sys/bus/pci/devices"),
        device_path: Callable[[str], Path] | None = None,
    ) -> None:
        self._sysfs_root = sysfs_root
        self._device_path = device_path or (lambda bdf: self._sysfs_root / bdf)

    def observe(
        self, root_bdf: str, function_bdfs: tuple[str, ...]
    ) -> WakeDiagnosticsObservation:
        if not PCI_BDF_RE.fullmatch(root_bdf) or not function_bdfs:
            return WakeDiagnosticsObservation(False, reason="wake.identity_unverified")
        if (
            len(function_bdfs) > 64
            or len(function_bdfs) != len(set(function_bdfs))
            or any(not PCI_BDF_RE.fullmatch(bdf) for bdf in function_bdfs)
        ):
            return WakeDiagnosticsObservation(False, reason="wake.topology_unverified")
        bridge = self._read_wakeup(root_bdf)
        wake_counts = {state: 0 for state in WakeCapabilityState}
        runtime_counts = {state: 0 for state in RuntimePowerState}
        for bdf in function_bdfs:
            wake_counts[self._read_wakeup(bdf)] += 1
            runtime_counts[self._read_runtime_state(bdf)] += 1
        return WakeDiagnosticsObservation(
            True,
            bridge_wakeup=bridge,
            function_wakeup_enabled=wake_counts[WakeCapabilityState.ENABLED],
            function_wakeup_disabled=wake_counts[WakeCapabilityState.DISABLED],
            function_wakeup_unknown=wake_counts[WakeCapabilityState.UNKNOWN],
            function_runtime_active=runtime_counts[RuntimePowerState.ACTIVE],
            function_runtime_suspended=runtime_counts[RuntimePowerState.SUSPENDED],
            function_runtime_unknown=runtime_counts[RuntimePowerState.UNKNOWN],
            reason="wake.read_only_capability_observed",
        )

    def _read_wakeup(self, bdf: str) -> WakeCapabilityState:
        value = self._read(self._device_path(bdf) / "power" / "wakeup")
        return {
            "enabled": WakeCapabilityState.ENABLED,
            "disabled": WakeCapabilityState.DISABLED,
        }.get(value, WakeCapabilityState.UNKNOWN)

    def _read_runtime_state(self, bdf: str) -> RuntimePowerState:
        value = self._read(self._device_path(bdf) / "power" / "runtime_status")
        return {
            "active": RuntimePowerState.ACTIVE,
            "suspended": RuntimePowerState.SUSPENDED,
        }.get(value, RuntimePowerState.UNKNOWN)

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace").strip().casefold()
        except OSError:
            return ""
