from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from hdm.adapters.steamos.device_removal import SysfsDeviceRemoval  # noqa: E402
from hdm.ports.device_removal import (  # noqa: E402
    RemovalOutcome,
    RescanOutcome,
)

import check_architecture  # noqa: E402


GPU = "0000:08:00.0"
AUDIO = "0000:08:00.1"

#: PCI addresses contain colons, which Windows cannot use in a path name.
#: These cases exercise real filesystem semantics against a sysfs-shaped
#: tree, so there is nothing to inject around; they run on the platform the
#: adapter targets. The architecture-gate cases below are pure and always run.
COLON_PATHS = os.name != "nt"
REQUIRES_COLON_PATHS = unittest.skipUnless(
    COLON_PATHS, "PCI-shaped paths need a filesystem allowing colons"
)


@REQUIRES_COLON_PATHS
class RemovalTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.devices = self.root / "devices"
        self.rescan = self.root / "rescan"
        self.devices.mkdir()
        self.rescan.write_text("", encoding="ascii")
        for address in (GPU, AUDIO):
            device = self.devices / address
            device.mkdir()
            (device / "remove").write_text("", encoding="ascii")

    def adapter(self) -> SysfsDeviceRemoval:
        return SysfsDeviceRemoval(device_root=self.devices, rescan_path=self.rescan)

    def test_invalid_address_is_refused_before_any_write(self) -> None:
        result = self.adapter().remove("not-a-bdf")
        self.assertIs(result.outcome, RemovalOutcome.REFUSED)
        self.assertEqual(result.code, "device_removal.address_invalid")
        self.assertTrue((self.devices / GPU).is_dir())

    def test_absent_device_reports_not_present(self) -> None:
        result = self.adapter().remove("0000:99:00.0")
        self.assertIs(result.outcome, RemovalOutcome.NOT_PRESENT)

    def test_a_write_that_leaves_the_device_reports_still_present(self) -> None:
        """A caller must not infer detachment from the absence of an error."""
        result = self.adapter().remove(GPU)
        self.assertIs(result.outcome, RemovalOutcome.STILL_PRESENT)
        self.assertFalse(result.ok)

    def test_removal_is_reported_when_the_kernel_honours_the_write(self) -> None:
        """Stand in for the kernel detaching the device during the write.

        The node disappears as a side effect of writing to it, which is what
        sysfs actually does, so the adapter's post-write check must observe it.
        """
        import shutil

        device = self.devices / GPU
        original_write = Path.write_text

        def detaching(self_path, *args, **kwargs):
            result = original_write(self_path, *args, **kwargs)
            if self_path == device / "remove":
                shutil.rmtree(device)
            return result

        Path.write_text = detaching
        try:
            result = self.adapter().remove(GPU)
        finally:
            Path.write_text = original_write
        self.assertIs(result.outcome, RemovalOutcome.REMOVED)
        self.assertTrue(result.ok)
        self.assertFalse(device.exists())

    def test_write_failure_carries_the_errno(self) -> None:
        (self.devices / GPU / "remove").unlink()
        (self.devices / GPU / "remove").mkdir()
        result = self.adapter().remove(GPU)
        self.assertIs(result.outcome, RemovalOutcome.FAILED)
        self.assertTrue(result.code.startswith("device_removal.write_failed:"))


@REQUIRES_COLON_PATHS
class RescanTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.devices = self.root / "devices"
        self.rescan = self.root / "rescan"
        self.devices.mkdir()
        self.rescan.write_text("", encoding="ascii")

    def adapter(self) -> SysfsDeviceRemoval:
        return SysfsDeviceRemoval(device_root=self.devices, rescan_path=self.rescan)

    def test_restored_when_every_expected_device_returns(self) -> None:
        for address in (GPU, AUDIO):
            (self.devices / address).mkdir()
        result = self.adapter().rescan((GPU, AUDIO))
        self.assertIs(result.outcome, RescanOutcome.RESTORED)
        self.assertEqual(set(result.restored), {GPU, AUDIO})

    def test_incomplete_when_a_device_has_not_returned(self) -> None:
        (self.devices / GPU).mkdir()
        result = self.adapter().rescan((GPU, AUDIO))
        self.assertIs(result.outcome, RescanOutcome.INCOMPLETE)
        self.assertEqual(result.restored, (GPU,))
        self.assertFalse(result.ok)

    def test_invalid_expected_address_is_refused(self) -> None:
        result = self.adapter().rescan((GPU, "nope"))
        self.assertIs(result.outcome, RescanOutcome.FAILED)
        self.assertEqual(result.code, "device_removal.address_invalid")

    def test_rescan_failure_carries_the_errno(self) -> None:
        self.rescan.unlink()
        self.rescan.mkdir()
        result = self.adapter().rescan((GPU,))
        self.assertIs(result.outcome, RescanOutcome.FAILED)
        self.assertTrue(result.code.startswith("device_removal.rescan_failed:"))


class ArchitectureGateTests(unittest.TestCase):
    """The write exemption must stay narrow, so pin what it permits."""

    def test_only_one_adapter_may_write(self) -> None:
        self.assertEqual(check_architecture.DEVICE_WRITER, "device_removal.py")

    def test_only_write_text_is_permitted_there(self) -> None:
        self.assertEqual(
            check_architecture.DEVICE_WRITER_ALLOWED_CALLS, {"write_text"}
        )

    def test_other_writers_remain_forbidden_everywhere(self) -> None:
        for call in ("write_bytes", "unlink", "chmod", "mkdir", "rename"):
            self.assertIn(call, check_architecture.FORBIDDEN_WRITE_CALLS)
            self.assertNotIn(call, check_architecture.DEVICE_WRITER_ALLOWED_CALLS)

    def test_the_repository_currently_passes(self) -> None:
        self.assertEqual(check_architecture.device_writer_failures(), [])


if __name__ == "__main__":
    unittest.main()
