from __future__ import annotations

import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.adapters.steamos.connection_readiness import G1ConnectionTopologyDiscovery
from hdm.adapters.steamos.drm import DrmCardRecord, DrmConnectorRecord
from hdm.adapters.steamos.pci import Usb4DeviceRecord
from tests.test_hardware_profiles import GPU_BDF, g1_records


class Drm:
    def __init__(self, cards=()):
        self.cards = cards

    def scan(self):
        return self.cards


class Pci:
    def __init__(self, *, records=(), usb4=(), complete=True):
        self.records = records
        self.usb4 = usb4
        self.complete = complete

    def scan_pci(self):
        return self.records

    def scan_usb4_checked(self):
        return self.usb4, self.complete


def tapex():
    return Usb4DeviceRecord("0-2", "Intel", "Tapex Creek", True, "a" * 64)


class ConnectionReadinessAdapterTests(unittest.TestCase):
    def test_exact_g1_hdmi_is_bound_to_g1_drm_card(self):
        card = DrmCardRecord(
            "card9", GPU_BDF, "0x1002", "0x7480", False, "amdgpu",
            (DrmConnectorRecord("card9", "HDMI-A-1", "connected", "enabled", edid_sha256="b" * 64),),
        )
        observed = G1ConnectionTopologyDiscovery(
            drm=Drm((card,)), pci_usb4=Pci(records=g1_records(), usb4=(tapex(),))
        ).observe()
        self.assertTrue(observed.pci_complete)
        self.assertTrue(observed.driver_ready)
        self.assertTrue(observed.hdmi_ready)
        self.assertEqual(observed.transport_identity, "transport:" + "a" * 16)

    def test_other_gpu_hdmi_does_not_satisfy_g1_readiness(self):
        g1 = DrmCardRecord("card9", GPU_BDF, "0x1002", "0x7480", False, "amdgpu")
        other = DrmCardRecord(
            "card4", "0000:03:00.0", "0x1234", "0x5678", False, "other",
            (DrmConnectorRecord("card4", "HDMI-A-1", "connected", "enabled", edid_sha256="b" * 64),),
        )
        observed = G1ConnectionTopologyDiscovery(
            drm=Drm((g1, other)), pci_usb4=Pci(records=g1_records(), usb4=(tapex(),))
        ).observe()
        self.assertFalse(observed.hdmi_ready)

    def test_verified_absence_requires_readable_usb4_inventory(self):
        complete = G1ConnectionTopologyDiscovery(drm=Drm(), pci_usb4=Pci()).observe()
        unavailable = G1ConnectionTopologyDiscovery(
            drm=Drm(), pci_usb4=Pci(complete=False)
        ).observe()
        self.assertTrue(complete.transport_absent_verified)
        self.assertFalse(unavailable.transport_absent_verified)


if __name__ == "__main__":
    unittest.main()
