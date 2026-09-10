"""Public discovery regressions: missing evidence is never a quiet dock.

These use real temporary mountinfo, swaps, holders and router files. Only block
ancestry discovery is mocked: it supplies the already-known branch disk sda.
The injected PCI root maps a BDF to a real colon-free directory so Windows can
exercise observe_storage's controller-presence check without sysfs symlinks or
privileged filesystem operations. This is parser/aggregation evidence, not
coverage of real PCI ancestry, kernel sysfs, or physical disconnect safety.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.steamos.dock_branch import DockBranchDiscovery  # noqa: E402


CONTROLLER = "0000:09:00.0"


class ControllerRoot:
    """Constructor-injected path seam for Windows-incompatible PCI names."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def __truediv__(self, bdf: str) -> Path:
        if bdf != CONTROLLER:
            raise AssertionError(f"Unexpected controller lookup: {bdf}")
        return self.directory


class DiscoveryFailClosedTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.controller = root / "controller"
        self.block = root / "block"
        self.proc = root / "proc"
        self.routers = root / "thunderbolt"
        for directory in (self.controller, self.block, self.proc, self.routers):
            directory.mkdir()
        self.mountinfo = root / "mountinfo"
        self.mountinfo.write_text("", encoding="utf-8")
        self.swaps = root / "swaps"
        self.swaps.write_text(
            "Filename\tType\tSize\tUsed\tPriority\n", encoding="utf-8"
        )
        (self.block / "sda" / "holders").mkdir(parents=True)
        (self.block / "sda" / "dev").write_text("8:0\n", encoding="utf-8")
        (self.block / "sda" / "sda1" / "holders").mkdir(parents=True)
        (self.block / "sda" / "sda1" / "dev").write_text(
            "8:1\n", encoding="utf-8"
        )
        (self.block / "sda" / "sda1" / "partition").write_text(
            "1\n", encoding="utf-8"
        )
        self.discovery = DockBranchDiscovery(
            pci_root=ControllerRoot(self.controller),
            block_root=self.block,
            proc_root=self.proc,
            mountinfo=self.mountinfo,
            swaps=self.swaps,
            thunderbolt_root=self.routers,
        )

    def storage(self):
        with patch.object(
            self.discovery, "_branch_block_devices", return_value=({"sda"}, True)
        ) as ancestry:
            reading = self.discovery.observe_storage(CONTROLLER)
        ancestry.assert_called_once_with(CONTROLLER)
        return reading

    def mount(self, source: str, device_number: str, target: str = "/mnt/backup"):
        self.mountinfo.write_text(
            f"36 25 {device_number} / {target} rw,relatime - ext4 {source} rw\n",
            encoding="utf-8",
        )

    def router(self, identity: str, name: str, authorized: str = "1"):
        directory = self.routers / identity
        directory.mkdir()
        (directory / "device_name").write_text(name, encoding="utf-8")
        (directory / "authorized").write_text(authorized, encoding="utf-8")

    def test_valid_empty_storage_evidence_is_complete(self):
        reading = self.storage()
        self.assertTrue(reading.complete)
        self.assertEqual(reading.mounts, ())
        self.assertEqual(reading.other_uses, ())

    def test_valid_unrelated_mount_does_not_block_branch(self):
        self.mount("/dev/nvme0n1p3", "259:3", "/")
        reading = self.storage()
        self.assertTrue(reading.complete)
        self.assertEqual(reading.mounts, ())
        self.assertEqual(reading.other_uses, ())

    def test_valid_branch_partition_mount_is_reported(self):
        self.mount("/dev/sda1", "8:1")
        reading = self.storage()
        self.assertTrue(reading.complete)
        self.assertEqual(reading.mounts, ("/mnt/backup",))

    def test_truncated_mountinfo_is_incomplete(self):
        self.mountinfo.write_text("36 25 8:1\n", encoding="utf-8")
        self.assertFalse(self.storage().complete)

    def test_mountinfo_missing_separator_is_incomplete(self):
        self.mountinfo.write_text(
            "36 25 8:1 / /mnt/backup rw ext4 /dev/sda1 rw\n", encoding="utf-8"
        )
        self.assertFalse(self.storage().complete)

    def test_malformed_namespace_table_keeps_known_mount_but_is_incomplete(self):
        self.mount("/dev/sda1", "8:1")
        namespace = self.proc / "4242"
        namespace.mkdir()
        (namespace / "mountinfo").write_text("37 25 8:1\n", encoding="utf-8")
        reading = self.storage()
        self.assertEqual(reading.mounts, ("/mnt/backup",))
        self.assertFalse(reading.complete)

    def test_missing_swaps_is_incomplete_for_existing_disk(self):
        self.swaps.unlink()
        self.assertTrue((self.block / "sda").is_dir())
        self.assertFalse(self.storage().complete)

    def test_missing_holders_is_incomplete_for_existing_disk(self):
        (self.block / "sda" / "holders").rmdir()
        self.assertTrue((self.block / "sda").is_dir())
        self.assertFalse(self.storage().complete)

    def test_stacked_consumer_of_partition_is_reported(self):
        (self.block / "sda" / "sda1" / "holders" / "dm-0").mkdir()
        reading = self.storage()
        self.assertTrue(reading.complete)
        self.assertTrue(
            any(use.kind == "stacked" and "dm-0" in use.detail
                for use in reading.other_uses),
            "An assembled mapping on a partition still holds the branch disk",
        )

    def test_missing_partition_holders_is_incomplete(self):
        (self.block / "sda" / "sda1" / "holders").rmdir()
        self.assertFalse(self.storage().complete)

    def test_unreadable_partition_inventory_is_incomplete(self):
        original = Path.iterdir
        disk = self.block / "sda"

        def read_directory(path):
            if path == disk:
                raise PermissionError("partition inventory unavailable")
            return original(path)

        with patch.object(Path, "iterdir", read_directory):
            reading = self.storage()
        self.assertFalse(
            reading.complete,
            "Reading whole-disk holders cannot replace a failed partition scan",
        )

    def test_mount_alias_is_matched_by_partition_device_number(self):
        self.mount("/dev/disk/by-uuid/backup-volume", "8:1")
        reading = self.storage()
        self.assertEqual(reading.mounts, ("/mnt/backup",))
        self.assertTrue(reading.complete)

    def test_mount_alias_is_matched_by_whole_disk_device_number(self):
        self.mount("/dev/disk/by-label/BACKUP", "8:0")
        reading = self.storage()
        self.assertEqual(reading.mounts, ("/mnt/backup",))
        self.assertTrue(reading.complete)

    def test_partial_device_number_scan_cannot_clear_an_alias_mount(self):
        (self.block / "sda" / "sda1" / "dev").unlink()
        self.mount("/dev/disk/by-uuid/backup-volume", "8:1")
        reading = self.storage()
        self.assertFalse(
            reading.complete,
            "A known whole-disk number does not complete partition identity",
        )

    def test_duplicate_router_names_cannot_select_first_attachment(self):
        self.router("0-1", "Tapex Creek", "0")
        self.router("0-2", "TAPEX CREEK", "1")
        reading = self.discovery.observe_tunnel("Tapex Creek")
        self.assertFalse(reading.complete)
        self.assertEqual(reading.sysfs_id, "")
        self.assertIsNone(reading.authorized)
        self.assertFalse(reading.deauthorizable)

    def test_unique_router_among_unrelated_routers_is_complete(self):
        self.router("0-1", "Other Dock")
        self.router("0-2", "Tapex Creek")
        reading = self.discovery.observe_tunnel("Tapex Creek")
        self.assertTrue(reading.complete)
        self.assertEqual(reading.sysfs_id, "0-2")
        self.assertIs(reading.authorized, True)


if __name__ == "__main__":
    unittest.main()
