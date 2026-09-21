"""Fresh, read-only G1 transport and HDMI readiness evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import stat

from ...profiles.gpd_g1 import GpdG1Match, match_gpd_g1
from .drm import DrmDiscovery
from .pci import PciUsb4Discovery, Usb4DeviceRecord

USB4_ROOT = Path('/sys/bus/thunderbolt/devices')
SYSFS_DEVICES_ROOT = Path('/sys/devices')


def verified_transport_absent() -> bool:
    """Strict absence for retained-claim archival, not ordinary attach admission.

    Every external router entry blocks, even if its attributes are unreadable or
    it was deliberately deauthorized. Empty/partial host inventories never prove
    unplugging. Two complete matching readings catch observed topology changes.
    """
    def read_attribute(path):
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError('invalid host attribute')
        with path.open('r', encoding='ascii') as source:
            value = source.read(129)
        if len(value) > 128:
            raise ValueError('oversized host attribute')
        return value.strip()

    def reading():
        entries = {}
        for entry in USB4_ROOT.iterdir():
            if len(entries) >= 64:
                raise ValueError('excessive USB4 inventory')
            # Reject external/unknown entries before touching their attributes.
            if not (re.fullmatch(r'domain(?:0|[1-9][0-9]*)', entry.name)
                    or re.fullmatch(r'(?:0|[1-9][0-9]*)-0', entry.name)):
                raise ValueError('external or unknown USB4 entry')
            entries[entry.name] = entry
        domains = {name[6:] for name in entries if name.startswith('domain')}
        hosts = {name[:-2] for name in entries if name.endswith('-0')}
        if not domains or hosts != domains or len(entries) != 2 * len(domains):
            raise ValueError('incomplete USB4 host inventory')
        result = []
        for index in sorted(domains):
            domain = entries['domain' + index].resolve(strict=True)
            host = entries[index + '-0'].resolve(strict=True)
            if (SYSFS_DEVICES_ROOT not in domain.parents or host.parent != domain
                    or domain.name != 'domain' + index or host.name != index + '-0'):
                raise ValueError('USB4 host topology mismatch')
            # A bus alias can lag or disappear while the actual router kobject
            # remains. Inspect the canonical host view as well. Attributes and
            # port directories are legitimate; route-shaped children are not.
            for parent in (domain, host):
                for count, child in enumerate(parent.iterdir()):
                    if count >= 256:
                        raise ValueError('excessive USB4 host children')
                    if re.fullmatch(r'[0-9]+-[0-9a-fA-F]+', child.name):
                        if parent != domain or child.name != index + '-0' or child.resolve(strict=True) != host:
                            raise ValueError('unlisted USB4 router remains')
            identities = []
            for path in (domain, host):
                info = path.lstat()
                if not stat.S_ISDIR(info.st_mode):
                    raise ValueError('USB4 host path invalid')
                identities.append((str(path), info.st_dev, info.st_ino))
            security = read_attribute(domain / 'security')
            if security not in ('none', 'user', 'secure', 'dponly', 'usbonly', 'nopcie'):
                raise ValueError('unknown USB4 security')
            authorized = read_attribute(host / 'authorized')
            if authorized not in ('0', '1'):
                raise ValueError('unknown USB4 host authorization')
            result.append((index, tuple(identities), security, authorized))
        return tuple(result)
    try:
        return reading() == reading()
    except (OSError, ValueError, UnicodeError, RuntimeError):
        return False


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
