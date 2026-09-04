"""Fresh, read-only G1 transport and HDMI readiness evidence."""

from __future__ import annotations

from dataclasses import dataclass

from ...profiles.gpd_g1 import GpdG1Match, match_gpd_g1
from .drm import DrmDiscovery
from .pci import PciUsb4Discovery, Usb4DeviceRecord


@dataclass(frozen=True, slots=True)
class G1ConnectionTopologyObservation:
    transport_identity: str = ""
    transport_present: bool = False
    transport_absent_verified: bool = False
    g1_identity: str = ""
    pci_complete: bool = False
    driver_ready: bool = False
    link_applicable: bool = False
    root_bdf: str = ""
    hdmi_ready: bool = False


class G1ConnectionTopologyDiscovery:
    """Observe the exact transport, PCI subtree, driver, and G1 HDMI path."""

    def __init__(
        self,
        *,
        drm: DrmDiscovery | None = None,
        pci_usb4: PciUsb4Discovery | None = None,
    ) -> None:
        self._drm = drm or DrmDiscovery()
        self._pci_usb4 = pci_usb4 or PciUsb4Discovery()

    def observe(self) -> G1ConnectionTopologyObservation:
        cards = self._drm.scan()
        pci = self._pci_usb4.scan_pci()
        usb4, usb4_complete = self._pci_usb4.scan_usb4_checked()
        external = tuple(item for item in usb4 if not _identityless_host_router(item))
        candidates = tuple(
            item
            for item in external
            if item.authorized is True
            and item.vendor_name.casefold() == "intel"
            and item.device_name.casefold() == "tapex creek"
            and item.unique_id_sha256
        )
        transport_identity = (
            f"transport:{candidates[0].unique_id_sha256[:16]}"
            if len(external) == 1 and len(candidates) == 1
            else "transport:unresolved" if external else ""
        )
        g1 = match_gpd_g1(cards, pci, usb4)
        return G1ConnectionTopologyObservation(
            transport_identity=transport_identity,
            transport_present=bool(external),
            transport_absent_verified=usb4_complete and not external,
            g1_identity=g1.stable_id if g1.verified else "",
            pci_complete=g1.verified,
            driver_ready=g1.verified,
            link_applicable=g1.verified,
            root_bdf=g1.root_bdf if g1.verified else "",
            hdmi_ready=_g1_hdmi_ready(cards, g1),
        )


def _identityless_host_router(device: Usb4DeviceRecord) -> bool:
    domain, separator, route = device.sysfs_id.partition("-")
    return bool(
        separator
        and domain.isdigit()
        and route == "0"
        and not device.vendor_name
        and not device.device_name
    )


def _g1_hdmi_ready(cards, g1: GpdG1Match) -> bool:
    if not g1.verified:
        return False
    matches = tuple(
        connector
        for card in cards
        if card.pci_bdf == g1.gpu_bdf
        for connector in card.connectors
        if not connector.internal
        and connector.connected is True
        and bool(connector.edid_sha256)
    )
    return len(matches) == 1
