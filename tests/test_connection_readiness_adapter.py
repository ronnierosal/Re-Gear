from __future__ import annotations

import unittest
import sys
import tempfile
from unittest.mock import Mock, patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.steamos.connection_readiness import G1ConnectionTopologyDiscovery
from regear.adapters.steamos import connection_readiness as adapter
from regear.adapters.steamos.drm import DrmCardRecord, DrmConnectorRecord
from regear.adapters.steamos.pci import Usb4DeviceRecord
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


class StrictTransportAbsenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.domain = self.root / 'nhi' / 'domain0'
        self.host = self.domain / '0-0'
        self.host.mkdir(parents=True)
        (self.domain / 'security').write_text('user')
        (self.host / 'authorized').write_text('1')
        self.inventory = Mock()
        self.inventory.iterdir.side_effect = lambda: iter((self.domain, self.host))
        for name, value in (('USB4_ROOT', self.inventory), ('SYSFS_DEVICES_ROOT', self.root)):
            patcher = patch.object(adapter, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_stable_positive_host_only_inventory(self):
        self.assertTrue(adapter.verified_transport_absent())
        self.assertEqual(self.inventory.iterdir.call_count, 2)

    def test_external_entry_blocks_without_reading_attributes(self):
        for authorized in ('0', '1', None):
            external = self.host / '0-1'
            external.mkdir(exist_ok=True)
            attribute = external / 'authorized'
            if authorized is not None:
                attribute.write_text(authorized)
            elif attribute.exists():
                attribute.unlink()
            self.inventory.iterdir.side_effect = lambda: iter((self.domain, self.host, external))
            self.assertFalse(adapter.verified_transport_absent())

    def test_router_without_bus_alias_still_blocks_absence(self):
        (self.host / '0-1').mkdir()
        self.assertFalse(adapter.verified_transport_absent())

    def test_legitimate_host_port_and_attributes_are_allowed(self):
        (self.host / 'usb4_port1').mkdir()
        (self.host / 'device_name').write_text('host')
        self.assertTrue(adapter.verified_transport_absent())

    def test_unknown_malformed_empty_and_incomplete_inventory(self):
        for entries in ((), (self.domain,), (self.host,),
                        (self.domain, self.host, self.root / 'unknown'),
                        (self.domain, self.host, self.root / '00-0')):
            self.inventory.iterdir.side_effect = lambda entries=entries: iter(entries)
            self.assertFalse(adapter.verified_transport_absent())

    def test_missing_or_malformed_host_attribute_refuses(self):
        (self.host / 'authorized').write_text('unreadable')
        self.assertFalse(adapter.verified_transport_absent())
        (self.host / 'authorized').unlink()
        self.assertFalse(adapter.verified_transport_absent())

    def test_unreadable_inventory_refuses(self):
        self.inventory.iterdir.side_effect = PermissionError('denied')
        self.assertFalse(adapter.verified_transport_absent())

    def test_host_disappears_between_readings(self):
        self.inventory.iterdir.side_effect = [iter((self.domain, self.host)), iter((self.domain,))]
        self.assertFalse(adapter.verified_transport_absent())

    def test_host_attribute_changes_between_readings(self):
        count = 0
        def entries():
            nonlocal count
            count += 1
            if count == 2:
                (self.host / 'authorized').write_text('0')
            return iter((self.domain, self.host))
        self.inventory.iterdir.side_effect = entries
        self.assertFalse(adapter.verified_transport_absent())

    def test_attribute_permission_failure_refuses(self):
        with patch.object(Path, 'open', side_effect=PermissionError('denied')):
            self.assertFalse(adapter.verified_transport_absent())


if __name__ == "__main__":
    unittest.main()
