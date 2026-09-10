"""Read-only PCIe link observation for an already verified eGPU bridge."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from ...domain.models import Confidence, EgpuLinkObservation, EgpuLinkState
from .pci import PCI_PATTERN


WIDTH_RE = re.compile(r"^x?(?P<width>\d+)$", re.IGNORECASE)
SPEED_RE = re.compile(r"^(?P<speed>\d+(?:\.\d+)?)\s*GT/s", re.IGNORECASE)


class PcieLinkHealthDiscovery:
    """Reads only current link sysfs attributes for an exact bridge BDF."""

    def __init__(
        self,
        pci_root: Path = Path("/sys/bus/pci/devices"),
        path_resolver: Callable[[str], Path] | None = None,
    ) -> None:
        self._path = path_resolver or (lambda bdf: pci_root / bdf)

    def observe(self, bridge_bdf: str) -> EgpuLinkObservation:
        if not PCI_PATTERN.fullmatch(bridge_bdf):
            return EgpuLinkObservation(
                False, EgpuLinkState.UNKNOWN, Confidence.UNKNOWN,
                error="egpu.link_bridge_identity_invalid",
            )
        try:
            speed = (self._path(bridge_bdf) / "current_link_speed").read_text(
                encoding="utf-8", errors="replace"
            ).strip()
            width = (self._path(bridge_bdf) / "current_link_width").read_text(
                encoding="utf-8", errors="replace"
            ).strip()
        except OSError:
            return EgpuLinkObservation(
                True, EgpuLinkState.UNKNOWN, Confidence.UNKNOWN,
                error="egpu.link_metrics_unavailable",
            )
        speed_match = SPEED_RE.match(speed)
        width_match = WIDTH_RE.fullmatch(width)
        if speed_match is None or width_match is None:
            return EgpuLinkObservation(
                True, EgpuLinkState.UNKNOWN, Confidence.UNKNOWN,
                error="egpu.link_metrics_unparseable",
            )
        if float(speed_match.group("speed")) <= 0 or int(width_match.group("width")) <= 0:
            return EgpuLinkObservation(
                True, EgpuLinkState.DOWN, Confidence.OBSERVED,
                reason="egpu.link_down",
                speed_gtps=float(speed_match.group("speed")),
                width_lanes=int(width_match.group("width")),
            )
        return EgpuLinkObservation(
            True, EgpuLinkState.UP, Confidence.OBSERVED,
            reason="egpu.link_observed",
            speed_gtps=float(speed_match.group("speed")),
            width_lanes=int(width_match.group("width")),
        )
