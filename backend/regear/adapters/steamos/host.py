"""Read-only host identity from DMI sysfs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


@dataclass(frozen=True, slots=True)
class HostRecord:
    sys_vendor: str
    product_name: str
    board_name: str


class HostDiscovery:
    def __init__(self, dmi_root: Path = Path("/sys/class/dmi/id")) -> None:
        self._dmi_root = dmi_root

    def scan(self) -> HostRecord:
        return HostRecord(
            sys_vendor=_read_text(self._dmi_root / "sys_vendor"),
            product_name=_read_text(self._dmi_root / "product_name"),
            board_name=_read_text(self._dmi_root / "board_name"),
        )
