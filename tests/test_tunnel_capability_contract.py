"""Independent capability/permission evidence; temporary files, not hardware proof."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from regear.adapters.steamos.dock_branch import DockBranchDiscovery
from regear.domain.dock_teardown import (
    DockTeardownState, TeardownApproval, TunnelCapability, TunnelEvidence,
    UsbBranchEvidence, WritePermission, decide_dock_teardown,
)


class CapabilityObservationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.router = self.root / "1-2"
        self.router.mkdir()
        (self.router / "device_name").write_text("Contract dock", encoding="utf-8")
        (self.router / "authorized").write_text("1", encoding="utf-8")
        for domain in ("domain0", "domain1"):
            (self.root / domain).mkdir()
        (self.root / "domain0" / "deauthorization").write_text("1", encoding="utf-8")
        self.support = self.root / "domain1" / "deauthorization"
        self.discovery = DockBranchDiscovery(thunderbolt_root=self.root)

    def reading(self, writable=True):
        # Permissions are deliberately injected; Windows access is not Linux sysfs.
        with patch("regear.adapters.steamos.dock_branch.os.access", return_value=writable):
            return self.discovery.observe_tunnel("Contract dock")

    def test_only_the_matching_domain_establishes_support(self):
        for value, expected in (("1\n", TunnelCapability.SUPPORTED),
                                ("0\n", TunnelCapability.NOT_SUPPORTED),
                                ("", TunnelCapability.UNKNOWN),
                                ("2", TunnelCapability.UNKNOWN),
                                ("yes", TunnelCapability.UNKNOWN)):
            with self.subTest(value=value):
                self.support.write_text(value, encoding="utf-8")
                reading = self.reading()
                self.assertEqual(reading.sysfs_id, "1-2")
                self.assertEqual(reading.capability, expected)
                self.assertEqual(reading.write_permission, WritePermission.WRITABLE)
                self.assertEqual(reading.deauthorizable, expected is TunnelCapability.SUPPORTED)

    def test_missing_domain_attribute_is_not_supported_by_writability(self):
        reading = self.reading()
        self.assertEqual(reading.capability, TunnelCapability.UNKNOWN)
        self.assertFalse(reading.deauthorizable)

    def test_support_does_not_override_denied_permission(self):
        self.support.write_text("1", encoding="utf-8")
        reading = self.reading(writable=False)
        self.assertEqual(reading.capability, TunnelCapability.SUPPORTED)
        self.assertEqual(reading.write_permission, WritePermission.DENIED)
        self.assertFalse(reading.deauthorizable)

    def test_missing_authorized_file_preserves_unknown_state(self):
        self.support.write_text("1", encoding="utf-8")
        (self.router / "authorized").unlink()
        reading = self.reading()
        self.assertIsNone(reading.authorized)
        self.assertEqual(reading.write_permission, WritePermission.UNKNOWN)
        self.assertFalse(reading.deauthorizable)

    def test_unreadable_support_cannot_borrow_another_domains_answer(self):
        self.support.write_text("1", encoding="utf-8")
        original = Path.read_text

        def read(path, *args, **kwargs):
            if path == self.support:
                raise PermissionError("fixture: support unreadable")
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", read):
            reading = self.reading()
        self.assertEqual(reading.capability, TunnelCapability.UNKNOWN)
        self.assertEqual(reading.write_permission, WritePermission.WRITABLE)
        self.assertFalse(reading.deauthorizable)

    def test_failed_permission_stat_is_unknown_even_when_access_allows(self):
        self.support.write_text("1", encoding="utf-8")
        original = Path.stat

        def stat(path, *args, **kwargs):
            if path == self.router / "authorized":
                raise PermissionError("fixture: authorization stat unreadable")
            return original(path, *args, **kwargs)

        with patch.object(Path, "stat", stat):
            reading = self.reading()
        self.assertEqual(reading.capability, TunnelCapability.SUPPORTED)
        self.assertEqual(reading.write_permission, WritePermission.UNKNOWN)
        self.assertFalse(reading.deauthorizable)


class CapabilityDecisionTests(unittest.TestCase):
    def decide(self, capability, permission, already_down=False):
        usb = UsbBranchEvidence(controller_bdf="0000:09:00.0", present=not already_down,
                                scan_complete=True, mounted_storage=(), storage_scan_complete=True)
        tunnel = TunnelEvidence(sysfs_id="1-2", authorized=not already_down,
                                capability=capability, write_permission=permission, scan_complete=True)
        return decide_dock_teardown(
            usb=usb, tunnel=tunnel, gpu_functions_present=(), gpu_scan_complete=True,
            approval=TeardownApproval(controller_bdf=usb.controller_bdf,
                                      tunnel_sysfs_id=tunnel.sysfs_id, disconnecting=()),
        )

    def test_all_capability_permission_combinations(self):
        for capability in TunnelCapability:
            for permission in WritePermission:
                with self.subTest(capability=capability, permission=permission):
                    decision = self.decide(capability, permission)
                    if capability is TunnelCapability.UNKNOWN:
                        suffix = "tunnel_capability_unknown"
                    elif capability is TunnelCapability.NOT_SUPPORTED:
                        suffix = "tunnel_capability_unsupported"
                    elif permission is WritePermission.UNKNOWN:
                        suffix = "tunnel_write_permission_unknown"
                    elif permission is WritePermission.DENIED:
                        suffix = "tunnel_write_permission_denied"
                    else:
                        self.assertTrue(decision.permitted)
                        continue
                    self.assertFalse(decision.permitted)
                    self.assertEqual(decision.code, "dock_teardown." + suffix)

    def test_already_down_needs_neither_capability_nor_permission(self):
        decision = self.decide(TunnelCapability.UNKNOWN, WritePermission.UNKNOWN, already_down=True)
        self.assertEqual(decision.state, DockTeardownState.ALREADY_DOWN)
        self.assertFalse(decision.permitted)

    def test_partial_or_unrecognized_evidence_never_permits(self):
        for capability, permission in (
            (None, WritePermission.WRITABLE),
            ("future_capability", WritePermission.WRITABLE),
            (TunnelCapability.SUPPORTED, None),
            (TunnelCapability.SUPPORTED, "future_permission"),
        ):
            with self.subTest(capability=capability, permission=permission):
                self.assertFalse(self.decide(capability, permission).permitted)
