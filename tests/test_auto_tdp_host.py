import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import test_tdp_control as control_fixtures
from hdm.adapters.steamos.auto_tdp_host import AutoTdpHostDiscovery


class AutoHostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.values = dict(sys_vendor="ASUSTeK COMPUTER INC.", product_name="ROG Ally X RC72LA",
                           board_name="RC72LA", bios_version="fixture-bios", bios_date="fixture-date",
                           kernel="fixture-kernel")
        for name, value in self.values.items():
            (self.root / name).write_text(value, encoding="ascii")
        self.discovery = AutoTdpHostDiscovery(dmi_root=self.root, kernel_release=self.root / "kernel")
        self.reading = control_fixtures.reading()

    def test_exact_host_produces_opaque_compatibility_key(self):
        result = self.discovery.observe(self.reading)
        self.assertEqual(result.code, "auto_tdp.host_context_observed")
        self.assertEqual(len(result.context_key), 64)
        self.assertNotIn("fixture", str(result))

    def test_power_adjustment_does_not_change_compatibility_key(self):
        before = self.discovery.observe(self.reading)
        self.assertEqual(before, self.discovery.observe(control_fixtures.reading(16, 16, 16)))

    def test_provider_restart_or_range_change_invalidates_key(self):
        before = self.discovery.observe(self.reading)
        for reading in (replace(self.reading, binding="new-owner-or-boot"),
                        replace(self.reading, sustained=replace(self.reading.sustained, maximum=29))):
            self.assertNotEqual(before.context_key, self.discovery.observe(reading).context_key)

    def test_firmware_or_kernel_change_invalidates_key(self):
        before = self.discovery.observe(self.reading)
        for name in ("bios_version", "bios_date", "kernel"):
            path = self.root / name
            path.write_text("changed", encoding="ascii")
            self.assertNotEqual(before.context_key, self.discovery.observe(self.reading).context_key)
            path.write_text(self.values[name], encoding="ascii")

    def test_missing_oversized_or_malformed_fields_never_produce_key(self):
        path = self.root / "bios_version"
        for raw in (b"", b"x" * 257, b"invalid\x00field", b"\xff"):
            path.write_bytes(raw)
            self.assertIsNone(self.discovery.observe(self.reading).context_key)
        path.unlink()
        self.assertIsNone(self.discovery.observe(self.reading).context_key)

    def test_unknown_host_and_changed_scan_fail_closed(self):
        (self.root / "product_name").write_text("another handheld", encoding="ascii")
        self.assertEqual(self.discovery.observe(self.reading).code, "auto_tdp.host_unsupported")
        original = tuple(self.values[name] for name in self.values)
        values = iter((original, original[:-1] + ("new-kernel",)))
        self.discovery._identity = lambda: next(values)
        self.assertEqual(self.discovery.observe(self.reading).code, "auto_tdp.host_context_changed")
