from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.steamos.drm import DrmCardRecord  # noqa: E402
from regear.adapters.steamos.host import HostRecord  # noqa: E402
from regear.adapters.steamos.pci import PciDeviceRecord, Usb4DeviceRecord  # noqa: E402
from regear.profiles.ally_x import match_ally_x, matches_ally_x  # noqa: E402
from regear.profiles.gpd_g1 import match_gpd_g1  # noqa: E402


GPU_BDF = "0000:08:00.0"
ROOT_BDF = "0000:04:00.0"
DOWNSTREAM_BDF = "0000:05:01.0"


def g1_records():
    ancestry = ("0000:00:03.1", ROOT_BDF)
    return (
        PciDeviceRecord(
            ROOT_BDF,
            "0x8086",
            "0x15ef",
            "0x060400",
            "pcieport",
            ("0000:00:03.1", ROOT_BDF),
            True,
        ),
        PciDeviceRecord(
            DOWNSTREAM_BDF,
            "0x8086",
            "0x15ef",
            "0x060400",
            "pcieport",
            ("0000:00:03.1", ROOT_BDF, DOWNSTREAM_BDF),
            True,
        ),
        PciDeviceRecord(
            GPU_BDF,
            "0x1002",
            "0x7480",
            "0x030000",
            "amdgpu",
            (*ancestry, DOWNSTREAM_BDF, "0000:06:00.0", "0000:07:00.0", GPU_BDF),
        ),
        PciDeviceRecord(
            "0000:08:00.1",
            "0x1002",
            "0xab30",
            "0x040300",
            "snd_hda_intel",
            (*ancestry, DOWNSTREAM_BDF, "0000:06:00.0", "0000:07:00.0", "0000:08:00.1"),
        ),
        PciDeviceRecord(
            "0000:09:00.0",
            "0x8086",
            "0x15f0",
            "0x0c0330",
            "xhci_hcd",
            (*ancestry, "0000:09:00.0"),
        ),
    )


class HardwareProfileTests(unittest.TestCase):
    def test_matches_known_ally_x_dmi_forms(self):
        host = HostRecord(
            "ASUSTeK COMPUTER INC.", "ROG Ally X RC72LA", "RC72LA"
        )
        self.assertTrue(matches_ally_x(host))
        self.assertTrue(
            matches_ally_x(
                HostRecord(
                    "  ASUSTeK   COMPUTER INC. ",
                    "ROG Ally X RC72LA",
                    "RC72LA",
                )
            )
        )
        self.assertTrue(
            matches_ally_x(
                HostRecord(
                    "ASUSTeK COMPUTER INC.",
                    "ROG Ally X RC72LA_RC72LA",
                    "RC72LA",
                )
            )
        )
        self.assertFalse(matches_ally_x(HostRecord("Valve", "Jupiter", "Steam Deck")))

    def test_rejects_similar_or_incomplete_ally_identity(self):
        similar = HostRecord("ASUS Compatible", "ROG Ally X Pro RC72LA", "RC72LA")
        incomplete = HostRecord("ASUSTeK COMPUTER INC.", "ROG Ally X RC72LA", "")
        self.assertFalse(matches_ally_x(similar))
        self.assertIn("certified profile", match_ally_x(similar).reason)
        self.assertFalse(matches_ally_x(incomplete))
        self.assertIn("incomplete", match_ally_x(incomplete).reason)

    def test_verifies_exact_g1_topology(self):
        card = DrmCardRecord("card9", GPU_BDF, "0x1002", "0x7480", False, "amdgpu")
        usb4 = (
            Usb4DeviceRecord("0-0", "", "", True, "h" * 64),
            Usb4DeviceRecord("0-2", "Intel", "Tapex Creek", True, "a" * 64),
        )

        result = match_gpd_g1((card,), g1_records(), usb4)

        self.assertTrue(result.verified)
        self.assertEqual(result.stable_id, "gpd-g1:" + "a" * 16)
        self.assertEqual(result.gpu_bdf, GPU_BDF)
        self.assertEqual(result.root_bdf, ROOT_BDF)
        self.assertEqual(result.audio_bdf, "0000:08:00.1")
        self.assertEqual(result.xhci_bdf, "0000:09:00.0")

    def test_rejects_same_gpu_id_without_complete_topology(self):
        card = DrmCardRecord("card9", GPU_BDF, "0x1002", "0x7480", False, "amdgpu")
        result = match_gpd_g1((card,), g1_records()[:-1], ())
        self.assertTrue(result.detected)
        self.assertFalse(result.verified)
        self.assertIn("subtree", result.reason)

    def test_partial_pci_or_usb4_enumeration_is_candidate_present(self):
        partial_pci = match_gpd_g1((), g1_records(), ())
        partial_usb4 = match_gpd_g1(
            (),
            (),
            (Usb4DeviceRecord("0-2", "Intel", "Tapex Creek", True, "a" * 64),),
        )

        for result in (partial_pci, partial_usb4):
            with self.subTest(result=result):
                self.assertTrue(result.detected)
                self.assertFalse(result.verified)
                self.assertIn("incomplete", result.reason)

    def test_rejects_an_extra_authorized_usb4_device(self):
        card = DrmCardRecord("card9", GPU_BDF, "0x1002", "0x7480", False, "amdgpu")
        usb4 = (
            Usb4DeviceRecord("0-1", "Intel", "Tapex Creek", True, "a" * 64),
            Usb4DeviceRecord("0-2", "Other", "Device", True, "b" * 64),
        )
        result = match_gpd_g1((card,), g1_records(), usb4)
        self.assertFalse(result.verified)
        self.assertIn("USB4", result.reason)

    def test_rejects_unbound_or_unexpected_profile_drivers(self):
        card = DrmCardRecord("card9", GPU_BDF, "0x1002", "0x7480", False, "vfio-pci")
        usb4 = (Usb4DeviceRecord("0-1", "Intel", "Tapex Creek", True, "a" * 64),)
        result = match_gpd_g1((card,), g1_records(), usb4)
        self.assertFalse(result.verified)
        self.assertIn("GPU PCI record", result.reason)

        records = tuple(
            dataclasses.replace(record, driver="")
            if (record.vendor, record.device) == ("0x1002", "0xab30")
            else record
            for record in g1_records()
        )
        result = match_gpd_g1(
            (
                DrmCardRecord(
                    "card9", GPU_BDF, "0x1002", "0x7480", False, "amdgpu"
                ),
            ),
            records,
            usb4,
        )
        self.assertFalse(result.verified)
        self.assertIn("subtree", result.reason)


if __name__ == "__main__":
    unittest.main()
