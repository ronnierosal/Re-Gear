"""Read-only DRM inventory from sysfs."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path


CARD_PATTERN = re.compile(r"card[0-9]+")
PCI_PATTERN = re.compile(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _read_lines(path: Path) -> tuple[str, ...]:
    return tuple(line.strip() for line in _read_text(path).splitlines() if line.strip())


def _product_name(path: Path) -> str:
    """Optional driver-provided presentation only; never infer identity from it."""
    try:
        with path.open(encoding="utf-8", errors="strict") as stream:
            raw = stream.read(130)
    except (OSError, UnicodeError):
        return ""
    name = raw.strip()
    if not 1 <= len(name) <= 128 or len(raw) >= 130:
        return ""
    if any(ord(char) < 32 or ord(char) > 126 for char in name):
        return ""
    return "" if name.lower() in {"unknown", "n/a", "none"} else name


def _pci_from_device(device_path: Path) -> str:
    uevent = _read_text(device_path / "uevent")
    for line in uevent.splitlines():
        if line.startswith("PCI_SLOT_NAME="):
            candidate = line.partition("=")[2].lower()
            if PCI_PATTERN.fullmatch(candidate):
                return candidate
    try:
        matches = PCI_PATTERN.findall(str(device_path.resolve(strict=True)))
    except OSError:
        matches = []
    return matches[-1].lower() if matches else ""


@dataclass(frozen=True, slots=True)
class DrmConnectorRecord:
    card: str
    name: str
    status: str
    enabled: str
    modes: tuple[str, ...] = field(default_factory=tuple)
    edid_sha256: str = ""

    @property
    def connected(self) -> bool | None:
        if self.status == "connected":
            return True
        if self.status == "disconnected":
            return False
        return None

    @property
    def internal(self) -> bool:
        return self.name.startswith("eDP-")


@dataclass(frozen=True, slots=True)
class DrmCardRecord:
    name: str
    pci_bdf: str
    vendor: str
    device: str
    boot_vga: bool | None
    driver: str
    connectors: tuple[DrmConnectorRecord, ...] = field(default_factory=tuple)
    model_name: str = field(default="", compare=False)

    @property
    def vendor_device(self) -> str:
        return f"{self.vendor.removeprefix('0x')}:{self.device.removeprefix('0x')}".lower()


class DrmDiscovery:
    def __init__(self, drm_root: Path = Path("/sys/class/drm")) -> None:
        self._drm_root = drm_root

    def scan(self) -> tuple[DrmCardRecord, ...]:
        try:
            entries = tuple(self._drm_root.iterdir())
        except OSError:
            return ()
        cards: list[DrmCardRecord] = []
        for card_path in sorted(entries, key=lambda item: item.name):
            if not CARD_PATTERN.fullmatch(card_path.name):
                continue
            device_path = card_path / "device"
            boot_raw = _read_text(device_path / "boot_vga")
            boot_vga = True if boot_raw == "1" else False if boot_raw == "0" else None
            try:
                driver = (device_path / "driver").resolve(strict=True).name
            except OSError:
                driver = ""
            connectors: list[DrmConnectorRecord] = []
            prefix = card_path.name + "-"
            for connector_path in sorted(entries, key=lambda item: item.name):
                if not connector_path.name.startswith(prefix):
                    continue
                name = connector_path.name[len(prefix) :]
                if not name or name.startswith("Writeback"):
                    continue
                try:
                    edid = (connector_path / "edid").read_bytes()
                except OSError:
                    edid = b""
                connectors.append(
                    DrmConnectorRecord(
                        card=card_path.name,
                        name=name,
                        status=_read_text(connector_path / "status").lower(),
                        enabled=_read_text(connector_path / "enabled").lower(),
                        modes=_read_lines(connector_path / "modes"),
                        edid_sha256=hashlib.sha256(edid).hexdigest() if edid else "",
                    )
                )
            cards.append(
                DrmCardRecord(
                    name=card_path.name,
                    pci_bdf=_pci_from_device(device_path),
                    vendor=_read_text(device_path / "vendor").lower(),
                    device=_read_text(device_path / "device").lower(),
                    boot_vga=boot_vga,
                    driver=driver,
                    connectors=tuple(connectors),
                    model_name=_product_name(device_path / "product_name"),
                )
            )
        return tuple(cards)
