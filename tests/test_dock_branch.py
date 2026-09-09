from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.adapters.steamos.dock_branch import DockBranchDiscovery  # noqa: E402


CONTROLLER = "0000:09:00.0"

#: PCI addresses contain colons, which Windows cannot use in a path name. These
#: cases exercise real filesystem semantics against a sysfs-shaped tree, so
#: there is nothing to inject around; they run on the platform the adapter
#: targets. The tunnel cases below use thunderbolt ids and always run.
REQUIRES_COLON_PATHS = unittest.skipUnless(
    os.name != "nt", "PCI-shaped paths need a filesystem allowing colons"
)


class Fake:
    """A sysfs tree shaped like the one the tested Ally X reports."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.pci = root / "pci"
        self.thunderbolt = root / "thunderbolt"
        self.block = root / "block"
        self.mountinfo = root / "mountinfo"
        for directory in (self.pci, self.thunderbolt, self.block):
            directory.mkdir(parents=True, exist_ok=True)
        self.mountinfo.write_text("", encoding="utf-8")

    def discovery(self) -> DockBranchDiscovery:
        return DockBranchDiscovery(
            pci_root=self.pci,
            thunderbolt_root=self.thunderbolt,
            block_root=self.block,
            mountinfo=self.mountinfo,
        )

    def controller(self, bdf: str = CONTROLLER) -> Path:
        path = self.pci / bdf
        path.mkdir(parents=True, exist_ok=True)
        return path

    def usb_device(
        self, bus: str, device_id: str, *, product="", manufacturer="", classes=()
    ) -> Path:
        path = self.controller() / bus / device_id
        path.mkdir(parents=True, exist_ok=True)
        if product:
            (path / "product").write_text(product, encoding="utf-8")
        if manufacturer:
            (path / "manufacturer").write_text(manufacturer, encoding="utf-8")
        for index, code in enumerate(classes):
            interface = path / f"{device_id}:1.{index}"
            interface.mkdir(parents=True, exist_ok=True)
            (interface / "bInterfaceClass").write_text(code, encoding="utf-8")
        return path

    def block_device(self, name: str, *, behind: str | None = CONTROLLER) -> None:
        target = self.root / "devices"
        if behind is not None:
            target = target / behind / "usb" / name
        else:
            target = target / "internal" / name
        target.mkdir(parents=True, exist_ok=True)
        link = self.block / name
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            raise unittest.SkipTest("symlinks are unavailable on this platform")

    def mount(self, source: str, mount_point: str) -> None:
        existing = self.mountinfo.read_text(encoding="utf-8")
        line = f"36 25 8:1 / {mount_point} rw,relatime - ext4 {source} rw\n"
        self.mountinfo.write_text(existing + line, encoding="utf-8")

    def tunnel(self, name: str, *, authorized: str | None = "1") -> Path:
        path = self.thunderbolt / "0-1"
        path.mkdir(parents=True, exist_ok=True)
        (path / "device_name").write_text(name, encoding="utf-8")
        if authorized is not None:
            (path / "authorized").write_text(authorized, encoding="utf-8")
        return path


class Harness(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.fake = Fake(Path(self._temporary.name).resolve())
        self.discovery = self.fake.discovery()


@REQUIRES_COLON_PATHS
class UsbBranchTests(Harness):
    def test_an_empty_dock_reads_as_present_with_nothing_attached(self) -> None:
        self.fake.controller()

        reading = self.discovery.observe_usb(CONTROLLER)

        self.assertTrue(reading.present)
        self.assertTrue(reading.complete)
        self.assertEqual(reading.devices, ())

    def test_a_controller_already_removed_is_a_finished_reading(self) -> None:
        # Not a failed look: this half of the teardown is simply already done.
        reading = self.discovery.observe_usb(CONTROLLER)

        self.assertFalse(reading.present)
        self.assertTrue(reading.complete)

    def test_attached_devices_are_named_the_way_a_player_would_know_them(self) -> None:
        self.fake.usb_device(
            "usb1",
            "1-1",
            product="Wireless Controller",
            manufacturer="Microsoft",
            classes=("03",),
        )

        reading = self.discovery.observe_usb(CONTROLLER)

        self.assertEqual(len(reading.devices), 1)
        self.assertEqual(reading.devices[0].label, "Microsoft Wireless Controller")
        self.assertEqual(reading.devices[0].kinds, ("input",))

    def test_a_device_publishing_no_name_still_gets_a_label(self) -> None:
        # An unnamed device is still something that will disconnect, and a
        # player cannot act on a blank line.
        self.fake.usb_device("usb1", "1-2")

        reading = self.discovery.observe_usb(CONTROLLER)

        self.assertEqual(reading.devices[0].label, "USB device 1-2")

    def test_devices_behind_a_hub_are_found_too(self) -> None:
        self.fake.usb_device("usb1", "1-1", product="Hub")
        self.fake.usb_device("usb1/1-1", "1-1.2", product="Flash Drive", classes=("08",))

        reading = self.discovery.observe_usb(CONTROLLER)

        labels = {device.label for device in reading.devices}
        self.assertIn("Flash Drive", labels)
        self.assertTrue(reading.complete)

    def test_a_malformed_controller_address_never_walks_anything(self) -> None:
        reading = self.discovery.observe_usb("../../etc")

        self.assertFalse(reading.present)
        self.assertFalse(reading.complete)

    def test_several_interface_classes_are_all_reported(self) -> None:
        self.fake.usb_device("usb1", "1-3", product="Dock Audio", classes=("01", "03"))

        reading = self.discovery.observe_usb(CONTROLLER)

        self.assertEqual(set(reading.devices[0].kinds), {"audio", "input"})


@REQUIRES_COLON_PATHS
class StorageTests(Harness):
    """The reading that decides whether somebody loses their files."""

    def test_no_block_devices_on_the_branch_is_a_complete_empty_answer(self) -> None:
        self.fake.controller()

        reading = self.discovery.observe_storage(CONTROLLER)

        self.assertEqual(reading.mounts, ())
        self.assertTrue(reading.complete)

    def test_a_mounted_drive_on_the_branch_is_found(self) -> None:
        self.fake.controller()
        self.fake.block_device("sda")
        self.fake.mount("/dev/sda1", "/run/media/deck/BACKUP")

        reading = self.discovery.observe_storage(CONTROLLER)

        self.assertEqual(reading.mounts, ("/run/media/deck/BACKUP",))
        self.assertTrue(reading.complete)

    def test_a_partition_is_matched_to_the_disk_the_branch_walk_found(self) -> None:
        # sysfs names the disk; mountinfo names the partition.
        self.fake.controller()
        self.fake.block_device("sdb")
        self.fake.mount("/dev/sdb2", "/run/media/deck/GAMES")

        self.assertEqual(
            self.discovery.observe_storage(CONTROLLER).mounts,
            ("/run/media/deck/GAMES",),
        )

    def test_internal_storage_is_never_attributed_to_the_dock(self) -> None:
        # The handheld's own drive is mounted at all times. Reading it as a
        # dock mount would refuse every teardown forever.
        self.fake.controller()
        self.fake.block_device("nvme0n1", behind=None)
        self.fake.mount("/dev/nvme0n1p3", "/")

        self.assertEqual(self.discovery.observe_storage(CONTROLLER).mounts, ())

    def test_an_unmounted_drive_on_the_branch_does_not_block(self) -> None:
        self.fake.controller()
        self.fake.block_device("sda")

        reading = self.discovery.observe_storage(CONTROLLER)

        self.assertEqual(reading.mounts, ())
        self.assertTrue(reading.complete)

    def test_an_unreadable_mountinfo_reports_incomplete_not_empty(self) -> None:
        # An empty mount list from a read that failed is not evidence that
        # nothing is mounted, and here that difference is somebody's files.
        self.fake.controller()
        self.fake.block_device("sda")
        self.fake.mountinfo.unlink()

        reading = self.discovery.observe_storage(CONTROLLER)

        self.assertEqual(reading.mounts, ())
        self.assertFalse(reading.complete)

    def test_a_missing_block_root_reports_incomplete(self) -> None:
        self.fake.controller()
        for child in self.fake.block.iterdir():
            child.unlink()
        self.fake.block.rmdir()

        self.assertFalse(self.discovery.observe_storage(CONTROLLER).complete)

    def test_a_controller_already_gone_has_nothing_mounted_on_it(self) -> None:
        reading = self.discovery.observe_storage(CONTROLLER)

        self.assertEqual(reading.mounts, ())
        self.assertTrue(reading.complete)

    def test_a_malformed_controller_address_reports_incomplete(self) -> None:
        self.assertFalse(self.discovery.observe_storage("nonsense").complete)


class MountinfoParsingTests(Harness):
    """The mount mapping on its own, without a sysfs tree.

    This is the subtlest part of the reading and the one with the worst
    failure: a mount missed here is a filesystem torn out from under someone.
    It needs no PCI paths and no symlinks, so unlike the walk above it runs
    everywhere, including on the machine this was written on -- which is the
    point, because the walk's own cases only run in CI.
    """

    def mounts(self, devices, lines):
        self.fake.mountinfo.write_text("".join(lines), encoding="utf-8")
        return self.discovery._mounts_for(set(devices))

    def test_no_devices_needs_no_read_at_all(self) -> None:
        found, complete = self.mounts((), [])

        self.assertEqual(found, ())
        self.assertTrue(complete)

    def test_a_partition_of_a_branch_disk_is_matched(self) -> None:
        found, complete = self.mounts(
            {"sda"},
            ["36 25 8:1 / /run/media/deck/BACKUP rw,relatime - ext4 /dev/sda1 rw\n"],
        )

        self.assertEqual(found, ("/run/media/deck/BACKUP",))
        self.assertTrue(complete)

    def test_the_whole_disk_mounted_directly_is_matched(self) -> None:
        found, _ = self.mounts(
            {"sdc"}, ["36 25 8:1 / /mnt/stick rw - vfat /dev/sdc rw\n"]
        )

        self.assertEqual(found, ("/mnt/stick",))

    def test_a_similarly_named_device_is_not_the_same_device(self) -> None:
        # "sdb" is not a partition of "sda". Matching it would refuse a
        # teardown over a drive that is not on the dock at all.
        found, _ = self.mounts(
            {"sda"}, ["36 25 8:1 / /mnt/other rw - ext4 /dev/sdb1 rw\n"]
        )

        self.assertEqual(found, ())

    def test_a_device_that_is_not_on_the_branch_is_ignored(self) -> None:
        found, _ = self.mounts(
            {"sda"}, ["36 25 259:3 / / rw - ext4 /dev/nvme0n1p3 rw\n"]
        )

        self.assertEqual(found, ())

    def test_optional_fields_before_the_separator_do_not_shift_the_source(self) -> None:
        # mountinfo carries a variable number of optional fields before "-".
        # Reading the source at a fixed index would find the wrong column.
        found, _ = self.mounts(
            {"sda"},
            [
                "36 25 8:1 / /run/media/deck/BACKUP rw,relatime shared:1 master:2 "
                "- ext4 /dev/sda1 rw\n"
            ],
        )

        self.assertEqual(found, ("/run/media/deck/BACKUP",))

    def test_several_mounts_of_one_branch_are_all_reported(self) -> None:
        # A player told about one of three would unmount it and try again.
        found, _ = self.mounts(
            {"sda", "sdb"},
            [
                "36 25 8:1 / /run/media/deck/A rw - ext4 /dev/sda1 rw\n",
                "37 25 8:2 / /run/media/deck/B rw - ext4 /dev/sda2 rw\n",
                "38 25 8:3 / /run/media/deck/C rw - ext4 /dev/sdb1 rw\n",
            ],
        )

        self.assertEqual(
            found, ("/run/media/deck/A", "/run/media/deck/B", "/run/media/deck/C")
        )

    def test_the_same_mount_point_twice_is_reported_once(self) -> None:
        found, _ = self.mounts(
            {"sda"},
            [
                "36 25 8:1 / /run/media/deck/A rw - ext4 /dev/sda1 rw\n",
                "37 25 8:1 / /run/media/deck/A rw - ext4 /dev/sda1 rw\n",
            ],
        )

        self.assertEqual(found, ("/run/media/deck/A",))

    def test_a_truncated_line_is_skipped_rather_than_crashing(self) -> None:
        found, complete = self.mounts(
            {"sda"},
            [
                "36 25 8:1\n",
                "37 25 8:1 / /run/media/deck/A rw - ext4 /dev/sda1 rw\n",
            ],
        )

        self.assertEqual(found, ("/run/media/deck/A",))
        self.assertTrue(complete)

    def test_a_line_with_no_separator_is_skipped(self) -> None:
        found, _ = self.mounts(
            {"sda"},
            ["36 25 8:1 / /run/media/deck/A rw,relatime ext4 /dev/sda1 rw\n"],
        )

        self.assertEqual(found, ())

    def test_an_unreadable_mountinfo_is_incomplete_not_empty(self) -> None:
        self.fake.mountinfo.unlink()

        found, complete = self.discovery._mounts_for({"sda"})

        self.assertEqual(found, ())
        self.assertFalse(complete)

    def test_the_twenty_seventh_disk_is_not_a_partition_of_the_first(self) -> None:
        # "sdaa1" starts with "sda". A bare prefix test would refuse a teardown
        # over a drive that is not on the dock at all -- safe, but for a reason
        # a player cannot act on.
        found, _ = self.mounts(
            {"sda"}, ["36 25 8:1 / /mnt/other rw - ext4 /dev/sdaa1 rw\n"]
        )

        self.assertEqual(found, ())

    def test_an_nvme_partition_is_matched_through_its_p(self) -> None:
        # These names already end in a digit, so the partition suffix is "p3"
        # rather than "3".
        found, _ = self.mounts(
            {"nvme0n1"}, ["36 25 259:3 / /mnt/fast rw - ext4 /dev/nvme0n1p3 rw\n"]
        )

        self.assertEqual(found, ("/mnt/fast",))

    def test_an_mmcblk_partition_is_matched_the_same_way(self) -> None:
        found, _ = self.mounts(
            {"mmcblk0"}, ["36 25 179:1 / /run/media/deck/SD rw - vfat /dev/mmcblk0p1 rw\n"]
        )

        self.assertEqual(found, ("/run/media/deck/SD",))

    def test_a_different_nvme_namespace_is_not_a_partition(self) -> None:
        found, _ = self.mounts(
            {"nvme0n1"}, ["36 25 259:3 / /mnt/other rw - ext4 /dev/nvme0n12 rw\n"]
        )

        self.assertEqual(found, ())


class TunnelTests(Harness):
    def test_an_authorized_router_is_found_by_the_name_it_publishes(self) -> None:
        self.fake.tunnel("Tapex Creek")

        reading = self.discovery.observe_tunnel("Tapex Creek")

        self.assertEqual(reading.sysfs_id, "0-1")
        self.assertIs(reading.authorized, True)
        self.assertTrue(reading.complete)

    def test_a_deauthorized_router_reads_as_down(self) -> None:
        self.fake.tunnel("Tapex Creek", authorized="0")

        self.assertIs(self.discovery.observe_tunnel("Tapex Creek").authorized, False)

    def test_an_unreadable_authorized_file_is_unknown_not_down(self) -> None:
        # One says the tunnel is down; the other says nothing at all. Reporting
        # a dock as detached on the strength of an unreadable file is the
        # failure this whole feature exists to avoid.
        self.fake.tunnel("Tapex Creek", authorized=None)

        self.assertIsNone(self.discovery.observe_tunnel("Tapex Creek").authorized)

    def test_a_nonsense_authorized_value_is_unknown_rather_than_truthy(self) -> None:
        self.fake.tunnel("Tapex Creek", authorized="maybe")

        self.assertIsNone(self.discovery.observe_tunnel("Tapex Creek").authorized)

    def test_no_such_router_is_a_finished_answer(self) -> None:
        # The dock is not attached by that name. That is a real reading, not a
        # failure to look.
        self.fake.tunnel("Some Other Dock")

        reading = self.discovery.observe_tunnel("Tapex Creek")

        self.assertEqual(reading.sysfs_id, "")
        self.assertTrue(reading.complete)

    def test_a_missing_thunderbolt_root_reports_incomplete(self) -> None:
        self.fake.thunderbolt.rmdir()

        self.assertFalse(self.discovery.observe_tunnel("Tapex Creek").complete)

    def test_the_name_match_ignores_case(self) -> None:
        self.fake.tunnel("TAPEX CREEK")

        self.assertEqual(
            self.discovery.observe_tunnel("Tapex Creek").sysfs_id, "0-1"
        )


@REQUIRES_COLON_PATHS
class ReadOnlyTests(Harness):
    def test_observing_changes_nothing_on_disk(self) -> None:
        # The act lives behind its own boundary: reading the state of a
        # player's dock must never be the thing that changes it.
        self.fake.controller()
        self.fake.usb_device("usb1", "1-1", product="Flash Drive", classes=("08",))
        self.fake.block_device("sda")
        self.fake.mount("/dev/sda1", "/run/media/deck/BACKUP")
        self.fake.tunnel("Tapex Creek")

        before = sorted(
            (str(path.relative_to(self.fake.root)), path.is_file())
            for path in self.fake.root.rglob("*")
        )
        self.discovery.observe_usb(CONTROLLER)
        self.discovery.observe_storage(CONTROLLER)
        self.discovery.observe_tunnel("Tapex Creek")
        after = sorted(
            (str(path.relative_to(self.fake.root)), path.is_file())
            for path in self.fake.root.rglob("*")
        )

        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
