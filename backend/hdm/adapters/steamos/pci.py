"""Read-only PCI and USB4 topology inventory."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path


PCI_PATTERN = re.compile(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


@dataclass(frozen=True, slots=True)
class PciDeviceRecord:
    bdf: str
    vendor: str
    device: str
    class_code: str
    driver: str
    ancestry: tuple[str, ...] = field(default_factory=tuple)
    removable: bool = False


@dataclass(frozen=True, slots=True)
class Usb4DeviceRecord:
    sysfs_id: str
    vendor_name: str
    device_name: str
    authorized: bool | None
    unique_id_sha256: str


class PciUsb4Discovery:
    def __init__(
        self,
        pci_root: Path = Path("/sys/bus/pci/devices"),
        usb4_root: Path = Path("/sys/bus/thunderbolt/devices"),
    ) -> None:
        self._pci_root = pci_root
        self._usb4_root = usb4_root

    def scan_pci(self) -> tuple[PciDeviceRecord, ...]:
        try:
            entries = tuple(self._pci_root.iterdir())
        except OSError:
            return ()
        records: list[PciDeviceRecord] = []
        for path in sorted(entries, key=lambda item: item.name):
            if not PCI_PATTERN.fullmatch(path.name):
                continue
            try:
                resolved = str(path.resolve(strict=True))
            except OSError:
                resolved = str(path)
            ancestry = tuple(item.lower() for item in PCI_PATTERN.findall(resolved))
            if not ancestry or ancestry[-1] != path.name.lower():
                ancestry = (*ancestry, path.name.lower())
            try:
                driver = (path / "driver").resolve(strict=True).name
            except OSError:
                driver = ""
            records.append(
                PciDeviceRecord(
                    bdf=path.name.lower(),
                    vendor=_read_text(path / "vendor").lower(),
                    device=_read_text(path / "device").lower(),
                    class_code=_read_text(path / "class").lower(),
                    driver=driver,
                    ancestry=ancestry,
                    removable=(path / "remove").exists(),
                )
            )
        return tuple(records)

    def scan_usb4(self) -> tuple[Usb4DeviceRecord, ...]:
        records, _complete = self.scan_usb4_checked()
        return records

    def scan_usb4_checked(self) -> tuple[tuple[Usb4DeviceRecord, ...], bool]:
        """Return inventory plus whether the sysfs directory was readable."""
        try:
            entries = tuple(self._usb4_root.iterdir())
        except OSError:
            return (), False
        records: list[Usb4DeviceRecord] = []
        for path in sorted(entries, key=lambda item: item.name):
            authorized_raw = _read_text(path / "authorized")
            vendor = _read_text(path / "vendor_name")
            name = _read_text(path / "device_name")
            if not authorized_raw and not vendor and not name:
                continue
            unique_id = _read_text(path / "unique_id")
            authorized = (
                True if authorized_raw == "1" else False if authorized_raw == "0" else None
            )
            records.append(
                Usb4DeviceRecord(
                    sysfs_id=path.name,
                    vendor_name=vendor,
                    device_name=name,
                    authorized=authorized,
                    unique_id_sha256=(
                        hashlib.sha256(unique_id.encode("utf-8")).hexdigest()
                        if unique_id
                        else ""
                    ),
                )
            )
        return tuple(records), True
