"""The only adapter permitted to write to a device node, and only these two.

`scripts/check_architecture.py` forbids adapter filesystem writes everywhere
else and constrains this module further: it may call `write_text` and nothing
else, may reference only the two approved sysfs path constants, and may not
spawn processes. That mirrors how `subprocess` is confined to `commands.py` —
the capability is concentrated in one reviewed place rather than relaxed
globally.

Two writes exist here. `<device>/remove` detaches an exact PCI function.
`/sys/bus/pci/rescan` asks the bus to re-enumerate, which is the recovery path
for a removal that should be undone. Both were exercised on an Ally X with a
GPD G1: each function detached in about two seconds and a rescan restored both
in about three, with their drivers rebound.

Removal is verified, never assumed. A write that returns without error but
leaves the device present is reported as `still_present`, because a caller
about to tell a player the device is detached must not be told so by a write
that silently did nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

from ...ports.device_removal import (
    RemovalOutcome,
    RemovalResult,
    RescanOutcome,
    RescanResult,
)


PCI_ADDRESS = re.compile(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]")

#: The two approved write targets. The architecture check pins these literals.
PCI_DEVICE_ROOT = "/sys/bus/pci/devices"
PCI_RESCAN = "/sys/bus/pci/rescan"

#: sysfs treats any nonzero value as the trigger; "1" is the conventional one.
TRIGGER = "1"


class SysfsDeviceRemoval:
    """Detach exact PCI functions and restore them by bus rescan."""

    def __init__(
        self,
        device_root: Path = Path(PCI_DEVICE_ROOT),
        rescan_path: Path = Path(PCI_RESCAN),
    ) -> None:
        self._device_root = device_root
        self._rescan_path = rescan_path

    def _device(self, address: str) -> Path:
        return self._device_root / address

    def remove(self, address: str) -> RemovalResult:
        if not PCI_ADDRESS.fullmatch(address):
            # Never build a write path from an unvalidated caller string.
            return RemovalResult(
                address, RemovalOutcome.REFUSED, "device_removal.address_invalid"
            )
        device = self._device(address)
        if not device.is_dir():
            return RemovalResult(
                address, RemovalOutcome.NOT_PRESENT, "device_removal.not_present"
            )
        try:
            (device / "remove").write_text(TRIGGER, encoding="ascii")
        except OSError as error:
            return RemovalResult(
                address,
                RemovalOutcome.FAILED,
                f"device_removal.write_failed:{error.errno}",
            )
        if device.is_dir():
            # The write succeeded and the device stayed. Report it rather than
            # letting a caller infer detachment from the absence of an error.
            return RemovalResult(
                address, RemovalOutcome.STILL_PRESENT, "device_removal.still_present"
            )
        return RemovalResult(address, RemovalOutcome.REMOVED)

    def rescan(self, expected: tuple[str, ...]) -> RescanResult:
        if any(not PCI_ADDRESS.fullmatch(address) for address in expected):
            return RescanResult(
                RescanOutcome.FAILED, code="device_removal.address_invalid"
            )
        try:
            self._rescan_path.write_text(TRIGGER, encoding="ascii")
        except OSError as error:
            return RescanResult(
                RescanOutcome.FAILED, code=f"device_removal.rescan_failed:{error.errno}"
            )
        restored = tuple(
            address for address in expected if self._device(address).is_dir()
        )
        if len(restored) != len(expected):
            # Enumeration can lag the write, so an incomplete result is a
            # report rather than a verdict; the caller decides whether to wait.
            return RescanResult(
                RescanOutcome.INCOMPLETE, restored, "device_removal.rescan_incomplete"
            )
        return RescanResult(RescanOutcome.RESTORED, restored)
