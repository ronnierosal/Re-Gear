"""Exact, privacy-preserving GPD G1 RX 7600M XT profile validation."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from ..adapters.steamos.drm import DrmCardRecord
from ..adapters.steamos.pci import PciDeviceRecord, Usb4DeviceRecord
from ..domain.control_plane import (
    CapabilitySupport,
    EgpuCapabilities,
    RemovalBehavior,
    SleepBehavior,
)


PROFILE_ID = "gpd-g1-rx7600mxt-titan-ridge"
STABLE_ID_PATTERN = re.compile(r"gpd-g1:[0-9a-f]{16}")
GPU_ID = ("0x1002", "0x7480")
ROOT_ID = ("0x8086", "0x15ef")
AUDIO_ID = ("0x1002", "0xab30")
XHCI_ID = ("0x8086", "0x15f0")
CAPABILITIES = EgpuCapabilities(
    profile_id=PROFILE_ID,
    display_output=CapabilitySupport.VERIFIED,
    audio_output=CapabilitySupport.VERIFIED,
    sleep_behavior=SleepBehavior.DISCONNECT_BEFORE_SLEEP_VERIFIED,
    removal_behavior=RemovalBehavior.SHUTDOWN_BEFORE_DISCONNECT,
)


@dataclass(frozen=True, slots=True)
class GpdG1Match:
    detected: bool
    verified: bool
    stable_id: str = ""
    gpu_bdf: str = ""
    root_bdf: str = ""
    audio_bdf: str = ""
    xhci_bdf: str = ""
    reason: str = ""
    pci_functions: tuple[str, ...] = field(default_factory=tuple)


def _identity(record: PciDeviceRecord) -> tuple[str, str]:
    return record.vendor, record.device


def _is_identityless_host_router(device: Usb4DeviceRecord) -> bool:
    domain, separator, route = device.sysfs_id.partition("-")
    return bool(
        separator
        and domain.isdigit()
        and route == "0"
        and not device.vendor_name
        and not device.device_name
    )


def match_gpd_g1(
    cards: tuple[DrmCardRecord, ...],
    pci_devices: tuple[PciDeviceRecord, ...],
    usb4_devices: tuple[Usb4DeviceRecord, ...],
) -> GpdG1Match:
    candidates = [card for card in cards if (card.vendor, card.device) == GPU_ID]
    if not candidates:
        pci_gpu_candidates = [
            record for record in pci_devices if _identity(record) == GPU_ID
        ]
        usb4_candidates = [
            device
            for device in usb4_devices
            if device.authorized is True
            and device.vendor_name.casefold() == "intel"
            and device.device_name.casefold() == "tapex creek"
        ]
        if pci_gpu_candidates or usb4_candidates:
            return GpdG1Match(
                True,
                False,
                reason="Candidate eGPU transport is present but DRM identity is incomplete",
            )
        return GpdG1Match(False, False, reason="Required external GPU was not detected")
    if len(candidates) != 1 or not candidates[0].pci_bdf:
        return GpdG1Match(True, False, reason="External GPU identity is ambiguous")

    card = candidates[0]
    by_bdf = {record.bdf: record for record in pci_devices}
    gpu = by_bdf.get(card.pci_bdf)
    if (
        gpu is None
        or _identity(gpu) != GPU_ID
        or not gpu.class_code.startswith("0x0300")
        or gpu.driver != "amdgpu"
        or card.driver != "amdgpu"
    ):
        return GpdG1Match(True, False, gpu_bdf=card.pci_bdf, reason="External GPU PCI record is incomplete")

    root_candidates = [
        by_bdf[bdf]
        for bdf in gpu.ancestry
        if bdf in by_bdf and _identity(by_bdf[bdf]) == ROOT_ID
    ]
    root_bdfs = {record.bdf for record in root_candidates}
    top_level_roots = [
        record
        for record in root_candidates
        if not any(
            ancestor != record.bdf and ancestor in root_bdfs
            for ancestor in record.ancestry
        )
    ]
    if (
        len(top_level_roots) != 1
        or not top_level_roots[0].removable
        or top_level_roots[0].driver != "pcieport"
    ):
        return GpdG1Match(
            True,
            False,
            gpu_bdf=card.pci_bdf,
            reason="Unique top-level removable eGPU bridge was not proven",
        )
    root = top_level_roots[0]
    subtree = tuple(
        record
        for record in pci_devices
        if record.bdf == root.bdf or root.bdf in record.ancestry
    )
    audio = [record for record in subtree if _identity(record) == AUDIO_ID]
    xhci = [record for record in subtree if _identity(record) == XHCI_ID]
    allowed = {gpu.bdf, root.bdf, *(record.bdf for record in audio + xhci)}
    unexpected = [
        record
        for record in subtree
        if record.bdf not in allowed and not record.class_code.startswith("0x0604")
    ]
    if (
        len(audio) != 1
        or len(xhci) != 1
        or audio[0].driver != "snd_hda_intel"
        or xhci[0].driver != "xhci_hcd"
        or unexpected
    ):
        return GpdG1Match(
            True,
            False,
            gpu_bdf=card.pci_bdf,
            reason="eGPU PCI subtree does not match a certified profile",
            pci_functions=tuple(sorted(record.bdf for record in subtree)),
        )

    authorized = [device for device in usb4_devices if device.authorized is True]
    external_authorized = [
        device
        for device in authorized
        if not _is_identityless_host_router(device)
    ]
    matching_usb4 = [
        device
        for device in external_authorized
        if device.vendor_name.casefold() == "intel"
        and device.device_name.casefold() == "tapex creek"
        and device.unique_id_sha256
    ]
    if len(external_authorized) != 1 or len(matching_usb4) != 1:
        return GpdG1Match(
            True,
            False,
            gpu_bdf=card.pci_bdf,
            reason="Exact authorized eGPU USB4 identity was not proven",
            pci_functions=tuple(sorted(record.bdf for record in subtree)),
        )

    stable_id = f"gpd-g1:{matching_usb4[0].unique_id_sha256[:16]}"
    return GpdG1Match(
        True,
        True,
        stable_id=stable_id,
        gpu_bdf=card.pci_bdf,
        root_bdf=root.bdf,
        audio_bdf=audio[0].bdf,
        xhci_bdf=xhci[0].bdf,
        pci_functions=tuple(sorted(record.bdf for record in subtree)),
    )
