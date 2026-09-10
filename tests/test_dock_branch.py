from __future__ import annotations

import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.steamos.dock_branch import DockBranchDiscovery  # noqa: E402
from regear.domain.dock_teardown import (  # noqa: E402
    StorageEvidenceGap,
    TunnelCapability,
    WritePermission,
)


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
        self.proc = root / "proc"
        self.swaps = root / "swaps"
        for directory in (self.pci, self.thunderbolt, self.block, self.proc):
            directory.mkdir(parents=True, exist_ok=True)
        self.mountinfo.write_text("", encoding="utf-8")
        self.swaps.write_text("Filename\t\t\t\tType\t\tSize\n", encoding="utf-8")

    def discovery(self) -> DockBranchDiscovery:
        return DockBranchDiscovery(
            pci_root=self.pci,
            thunderbolt_root=self.thunderbolt,
            block_root=self.block,
            mountinfo=self.mountinfo,
            proc_root=self.proc,
            swaps=self.swaps,
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
        # A block device the kernel knows about always has a holders
        # directory, empty when nothing stacks on it. Leaving it out describes
        # a device that is not there, which the reading now reports as
        # unexamined rather than idle.
        (target / "holders").mkdir(parents=True, exist_ok=True)
        link = self.block / name
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            raise unittest.SkipTest("symlinks are unavailable on this platform")

    def block_metadata(
        self, disk: str, *, devnum: str = "", partitions: tuple = ()
    ) -> None:
        """What the kernel publishes for a block device that exists.

        Every block device gets a `holders` directory, empty when nothing
        stacks on it, and a `dev` file naming its major:minor. A fixture that
        omits them is describing a device that is not there, which the reading
        now reports as unexamined rather than as idle.
        """
        root = self.block / disk
        (root / "holders").mkdir(parents=True, exist_ok=True)
        if devnum:
            (root / "dev").write_text(devnum, encoding="utf-8")
        for name, number in partitions:
            partition = root / name
            (partition / "holders").mkdir(parents=True, exist_ok=True)
            if number:
                (partition / "dev").write_text(number, encoding="utf-8")

    def mount(self, source: str, mount_point: str) -> None:
        existing = self.mountinfo.read_text(encoding="utf-8")
        line = f"36 25 8:1 / {mount_point} rw,relatime - ext4 {source} rw\n"
        self.mountinfo.write_text(existing + line, encoding="utf-8")

    def namespace_mount(self, pid: str, source: str, mount_point: str) -> None:
        """A mount visible only inside another process's mount namespace."""
        directory = self.proc / pid
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "mountinfo").write_text(
            f"36 25 8:1 / {mount_point} rw,relatime - ext4 {source} rw\n",
            encoding="utf-8",
        )

    def swap_on(self, source: str) -> None:
        self.swaps.write_text(
            "Filename\t\t\t\tType\t\tSize\n"
            f"{source}\t\t\t\tpartition\t8388604\n",
            encoding="utf-8",
        )

    def holder(self, device: str, holder: str) -> None:
        (self.block / device / "holders" / holder).mkdir(parents=True, exist_ok=True)

    def domain(self, index: str = "0", *, deauthorization: str | None = "1") -> Path:
        """The Thunderbolt domain, which is where support is published.

        A router id is `<domain index>-<route>`, so the router `0-1` belongs
        to `domain0`. Passing None leaves the attribute absent, which is a
        real case: not every kernel or controller publishes it.
        """
        path = self.thunderbolt / f"domain{index}"
        path.mkdir(parents=True, exist_ok=True)
        if deauthorization is not None:
            (path / "deauthorization").write_text(deauthorization, encoding="utf-8")
        return path

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
        found, gaps = self.discovery._mounts_for(set(devices))
        return found, not gaps

    def mount_gaps(self, devices, lines):
        self.fake.mountinfo.write_text("".join(lines), encoding="utf-8")
        return self.discovery._mounts_for(set(devices))[1]

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

    def test_a_truncated_line_is_read_past_but_leaves_the_scan_incomplete(self) -> None:
        """Skipping it must not also claim the table was fully read.

        The mounts that did parse are still reported: a line this parser
        cannot read is no reason to discard the ones it could. But a truncated
        table is a table with an unread mount in it, and calling that a
        finished scan is how a branch in use reads as idle.
        """
        found, complete = self.mounts(
            {"sda"},
            [
                "36 25 8:1\n",
                "37 25 8:1 / /run/media/deck/A rw - ext4 /dev/sda1 rw\n",
            ],
        )

        self.assertEqual(found, ("/run/media/deck/A",))
        self.assertFalse(complete)

    def test_a_line_with_no_separator_is_skipped(self) -> None:
        found, _ = self.mounts(
            {"sda"},
            ["36 25 8:1 / /run/media/deck/A rw,relatime ext4 /dev/sda1 rw\n"],
        )

        self.assertEqual(found, ())

    def test_an_unreadable_mountinfo_is_incomplete_not_empty(self) -> None:
        self.fake.mountinfo.unlink()

        found, _gaps = self.discovery._mounts_for({"sda"})
        complete = not _gaps

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


class OtherStorageUseTests(Harness):
    """Unmounted is not unused, and treating the two as the same loses files.

    A drive can be written to with no mount in this namespace at all: swap on
    it, a device-mapper or md layer stacked over it, or a filesystem mounted
    inside a container that has its own mount namespace.
    """

    def uses(self, devices):
        """`(uses, complete)`, so cases about completeness stay readable.

        The reading now carries WHICH evidence was missing; `gaps` below
        exposes that for the cases that care.
        """
        found, gaps = self.discovery._other_uses(set(devices))
        return found, not gaps

    def gaps(self, devices):
        return self.discovery._other_uses(set(devices))[1]

    def test_a_quiet_system_reports_no_other_use(self) -> None:
        self.fake.block_metadata("sda")

        found, complete = self.uses({"sda"})

        self.assertEqual(found, ())
        self.assertTrue(complete)

    def test_no_devices_needs_no_checks(self) -> None:
        found, complete = self.uses(())

        self.assertEqual(found, ())
        self.assertTrue(complete)

    def test_swap_on_a_branch_partition_is_a_use(self) -> None:
        self.fake.block_metadata("sda", partitions=(("sda2", ""),))
        self.fake.swap_on("/dev/sda2")

        found, complete = self.uses({"sda"})

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].kind, "swap")
        self.assertEqual(found[0].device, "sda2")
        self.assertTrue(complete)

    def test_swap_elsewhere_is_not_this_branch(self) -> None:
        self.fake.swap_on("/dev/nvme0n1p2")

        found, _ = self.uses({"sda"})

        self.assertEqual(found, ())

    def test_a_missing_swaps_file_is_not_a_system_without_swap(self) -> None:
        """`/proc/swaps` exists whether or not any swap is configured.

        A system with none has a header row and nothing under it. An absent
        file therefore means the table was not read at all, which says nothing
        about what is swapping to the branch.
        """
        self.fake.swaps.unlink()

        found, complete = self.uses({"sda"})

        self.assertEqual(found, ())
        self.assertFalse(complete)

    def test_a_stacked_device_holds_its_member(self) -> None:
        # A member of an assembled array is thoroughly in use while being
        # mounted nowhere.
        (self.fake.block / "sda").mkdir(parents=True, exist_ok=True)
        self.fake.holder("sda", "dm-0")

        found, complete = self.uses({"sda"})

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].kind, "stacked")
        self.assertIn("dm-0", found[0].detail)
        self.assertTrue(complete)

    def test_several_holders_are_all_reported(self) -> None:
        (self.fake.block / "sda").mkdir(parents=True, exist_ok=True)
        self.fake.holder("sda", "dm-0")
        self.fake.holder("sda", "md0")

        found, _ = self.uses({"sda"})

        self.assertEqual({use.detail for use in found}, {"in use by dm-0", "in use by md0"})

    def test_a_mapping_assembled_on_a_partition_is_a_use(self) -> None:
        """Only the disk's own holders were ever read.

        A dm or md device assembled on a partition holds the branch just as
        firmly as one assembled on the whole disk, and reported nothing at
        all -- an idle branch, over a live mapping.
        """
        self.fake.block_metadata("sda", partitions=(("sda1", ""),))
        (self.fake.block / "sda" / "sda1" / "holders" / "dm-0").mkdir(parents=True)

        found, complete = self.uses({"sda"})

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].kind, "stacked")
        self.assertEqual(found[0].detail, "in use by dm-0")
        self.assertTrue(complete)

    def test_a_partition_use_names_the_partition_not_the_disk(self) -> None:
        """What a player has to act on is the thing that is held."""
        self.fake.block_metadata("sda", partitions=(("sda1", ""),))
        (self.fake.block / "sda" / "sda1" / "holders" / "dm-0").mkdir(parents=True)

        found, _ = self.uses({"sda"})

        self.assertEqual(found[0].device, "sda1")

    def test_an_unreadable_partition_inventory_is_incomplete(self) -> None:
        """Listing the disk alone is not the same as there being no partitions.

        The disk's own holders read fine here. What failed is the walk that
        would have found its partitions, so any mapping assembled on one is
        unseen -- and reporting that as a finished scan is the whole bug.
        """
        self.fake.block_metadata("sda")
        disk = self.fake.block / "sda"
        real = Path.iterdir

        def refuse(self):
            if self == disk:
                raise PermissionError(disk)
            return real(self)

        with unittest.mock.patch.object(Path, "iterdir", refuse):
            found, complete = self.uses({"sda"})

        self.assertEqual(found, ())
        self.assertFalse(complete)

    def test_no_holders_directory_is_not_no_holders(self) -> None:
        """The kernel gives every block device one, empty when unused.

        Absent means this is not the device we think it is, or it went away
        mid-walk. Either way it was never examined, and an unexamined device
        is not an unused one.
        """
        (self.fake.block / "sda").mkdir(parents=True, exist_ok=True)

        found, complete = self.uses({"sda"})

        self.assertEqual(found, ())
        self.assertFalse(complete)


class StorageGapTests(Harness):
    """Which evidence was missing, not merely that some was.

    Every one of these used to arrive as one code. An unreadable mount
    namespace, an absent `/proc/swaps` and a partition list that could not be
    taken have different remedies, and one of them is transient.
    """

    def storage(self, devices):
        return self.discovery._other_uses(set(devices))[1]

    def test_the_same_kind_of_failure_twice_is_reported_once(self):
        """A reading says which evidence is missing, not how often."""
        self.fake.block_metadata("sda")
        self.fake.block_metadata("sdb")
        for device in ("sda", "sdb"):
            (self.fake.block / device / "holders").rmdir()

        gaps = self.storage({"sda", "sdb"})

        self.assertEqual(gaps, (StorageEvidenceGap.HOLDERS_UNREADABLE,))

    def test_simultaneous_failures_all_survive(self):
        """An implementation that returns on the first gap passes without this."""
        self.fake.block_metadata("sda")
        (self.fake.block / "sda" / "holders").rmdir()
        self.fake.swaps.unlink()

        gaps = self.storage({"sda"})

        self.assertIn(StorageEvidenceGap.SWAPS_UNREADABLE, gaps)
        self.assertIn(StorageEvidenceGap.HOLDERS_UNREADABLE, gaps)

    def test_gaps_are_reported_in_declaration_order_not_discovery_order(self):
        """The later-declared cause is made to happen FIRST, on purpose.

        Most failure combinations happen to be discovered in declaration
        order anyway, so a fixture built from them proves nothing: appending
        as the walk goes passes it. This one inverts them. The mount table is
        read top to bottom, so an alias line placed above a truncated line
        makes MOUNT_SOURCE_UNATTRIBUTABLE (declared fifth) happen before
        MOUNT_LINE_UNPARSABLE (declared fourth).
        """
        self.fake.block_metadata("sda")

        _, gaps = self.discovery._mounts_for({"sda"})
        self.assertEqual(gaps, ())  # the fixture itself is clean

        self.fake.mountinfo.write_text(
            "36 25 8:1 / /mnt/a rw - ext4 /dev/disk/by-uuid/1234-ABCD rw\n"
            "37 25 8:2\n",
            encoding="utf-8",
        )

        _, gaps = self.discovery._mounts_for({"sda"})

        self.assertEqual(
            gaps,
            (
                StorageEvidenceGap.MOUNT_LINE_UNPARSABLE,
                StorageEvidenceGap.MOUNT_SOURCE_UNATTRIBUTABLE,
                StorageEvidenceGap.DEVICE_NUMBERS_INCOMPLETE,
            ),
        )

    def test_no_gap_can_carry_a_path_or_a_device_name(self):
        """Structural, so a later detail field cannot quietly leak one.

        This reading crosses other processes. It must not become a way to
        enumerate them, and the type having nowhere to put a path beats
        remembering to redact one.
        """
        for gap in StorageEvidenceGap:
            with self.subTest(gap=gap):
                self.assertNotIn("/", gap.value)
                self.assertEqual(gap.value, gap.value.lower())
                self.assertTrue(gap.value.replace("_", "").isalpha())

    def test_a_finished_reading_has_no_gaps_and_says_it_is_complete(self):
        self.fake.block_metadata("sda")

        found, gaps = self.discovery._other_uses({"sda"})

        self.assertEqual(found, ())
        self.assertEqual(gaps, ())


class AliasMountTests(Harness):
    """A drive mounted through an alias is mounted.

    Nothing requires a mount to name the kernel device. `/dev/disk/by-uuid/`,
    `/dev/disk/by-label/` and `/dev/mapper/` are ordinary, and their basenames
    are a UUID, a label or a mapping name that match no sysfs device. Matching
    on the basename alone therefore reads a mounted branch as an idle one,
    which is the reading that lets a teardown proceed over a live filesystem.
    """

    def mounts(self, devices, lines):
        self.fake.mountinfo.write_text("".join(lines), encoding="utf-8")
        found, gaps = self.discovery._mounts_for(set(devices))
        return found, not gaps

    def mount_gaps(self, devices, lines):
        self.fake.mountinfo.write_text("".join(lines), encoding="utf-8")
        return self.discovery._mounts_for(set(devices))[1]

    ALIAS = (
        "36 25 8:1 / /run/media/deck/BACKUP rw,relatime "
        "- ext4 /dev/disk/by-uuid/1234-ABCD rw\n"
    )

    def publish_device_numbers(self) -> None:
        disk = self.fake.block / "sda"
        disk.mkdir(parents=True, exist_ok=True)
        (disk / "dev").write_text("8:0\n", encoding="utf-8")
        partition = disk / "sda1"
        partition.mkdir(parents=True, exist_ok=True)
        (partition / "dev").write_text("8:1\n", encoding="utf-8")

    def test_an_alias_mount_is_matched_by_device_number(self) -> None:
        self.publish_device_numbers()

        found, complete = self.mounts({"sda"}, [self.ALIAS])

        self.assertEqual(found, ("/run/media/deck/BACKUP",))
        self.assertTrue(complete)

    def test_an_alias_mount_with_no_device_numbers_is_not_an_idle_branch(self) -> None:
        """Unattributable is not absent."""
        found, complete = self.mounts({"sda"}, [self.ALIAS])

        self.assertEqual(found, ())
        self.assertFalse(complete)

    def test_a_device_number_elsewhere_is_still_not_this_branch(self) -> None:
        """Reading numbers must not turn every alias into a match."""
        self.publish_device_numbers()

        found, complete = self.mounts(
            {"sda"},
            [
                "36 25 259:3 / / rw,relatime "
                "- ext4 /dev/disk/by-uuid/OTHER-DISK rw\n"
            ],
        )

        self.assertEqual(found, ())
        self.assertTrue(complete)

    def test_a_partial_device_number_scan_cannot_clear_an_alias(self) -> None:
        """Knowing some numbers is not knowing the answer.

        The disk publishes 8:0 and its partition publishes nothing. An alias
        mounting 8:1 then matches no number held, which is not the same as
        belonging to someone else. Treating a merely non-empty map as
        sufficient is what makes that mount disappear.
        """
        disk = self.fake.block / "sda"
        disk.mkdir(parents=True, exist_ok=True)
        (disk / "dev").write_text("8:0\n", encoding="utf-8")
        (disk / "sda1").mkdir(parents=True, exist_ok=True)

        found, complete = self.mounts({"sda"}, [self.ALIAS])

        self.assertEqual(found, ())
        self.assertFalse(complete)

    def test_a_malformed_device_number_cannot_clear_an_alias(self) -> None:
        """Unreadable evidence in the shape of an answer is still unreadable.

        A truncated or garbled `dev` file is not a device number. Counting it
        as one makes the map look exhaustive while holding nothing that can
        match, so the alias mount silently disappears.
        """
        disk = self.fake.block / "sda"
        disk.mkdir(parents=True, exist_ok=True)
        (disk / "dev").write_text("8:0\n", encoding="utf-8")
        partition = disk / "sda1"
        partition.mkdir(parents=True, exist_ok=True)
        (partition / "dev").write_text("not-a-device-number\n", encoding="utf-8")

        found, complete = self.mounts({"sda"}, [self.ALIAS])

        self.assertEqual(found, ())
        self.assertFalse(complete)

    def test_a_plain_device_source_still_needs_no_numbers(self) -> None:
        """The existing name comparison is kept, not replaced."""
        found, complete = self.mounts(
            {"sda"},
            ["36 25 8:1 / /mnt/stick rw - ext4 /dev/sda1 rw\n"],
        )

        self.assertEqual(found, ("/mnt/stick",))
        self.assertTrue(complete)


class MountNamespaceTests(Harness):
    """A drive mounted inside a container is mounted.

    /proc/self/mountinfo shows this process's namespace. Flatpak apps, Steam's
    own containers and any unit with PrivateMounts have their own, and a mount
    in one of those is invisible here while being very much a mount.
    """

    def test_a_mount_in_another_namespace_is_found(self) -> None:
        self.fake.namespace_mount("4242", "/dev/sda1", "/run/host/media/BACKUP")

        found, _gaps = self.discovery._mounts_for({"sda"})
        complete = not _gaps

        self.assertEqual(found, ("/run/host/media/BACKUP",))
        self.assertTrue(complete)

    def test_this_namespace_is_still_read(self) -> None:
        self.fake.mount("/dev/sda1", "/run/media/deck/BACKUP")

        found, _ = self.discovery._mounts_for({"sda"})

        self.assertEqual(found, ("/run/media/deck/BACKUP",))

    def test_the_same_mount_seen_from_two_processes_is_reported_once(self) -> None:
        self.fake.mount("/dev/sda1", "/run/media/deck/BACKUP")
        self.fake.namespace_mount("4242", "/dev/sda1", "/run/media/deck/BACKUP")

        found, _ = self.discovery._mounts_for({"sda"})

        self.assertEqual(found, ("/run/media/deck/BACKUP",))

    def test_non_numeric_proc_entries_are_skipped(self) -> None:
        (self.fake.proc / "self").mkdir(parents=True, exist_ok=True)
        (self.fake.proc / "self" / "mountinfo").write_text(
            "36 25 8:1 / /ignored rw - ext4 /dev/sda1 rw\n", encoding="utf-8"
        )

        found, _ = self.discovery._mounts_for({"sda"})

        self.assertEqual(found, ())

    def test_a_process_that_exited_mid_walk_holds_nothing(self) -> None:
        (self.fake.proc / "4242").mkdir(parents=True, exist_ok=True)

        found, _gaps = self.discovery._mounts_for({"sda"})
        complete = not _gaps

        self.assertEqual(found, ())
        self.assertTrue(complete)

    def test_an_unwalkable_proc_leaves_this_namespace_readable(self) -> None:
        # Degraded to incomplete rather than to nothing: the namespace this
        # process is in was still read, and the decision refuses on incomplete
        # anyway.
        self.fake.mount("/dev/sda1", "/run/media/deck/BACKUP")
        for child in list(self.fake.proc.iterdir()):
            child.rmdir()
        self.fake.proc.rmdir()

        found, _gaps = self.discovery._mounts_for({"sda"})
        complete = not _gaps

        self.assertEqual(found, ("/run/media/deck/BACKUP",))
        self.assertFalse(complete)


class TunnelTests(Harness):
    def test_an_authorized_router_is_found_by_the_name_it_publishes(self) -> None:
        self.fake.tunnel("Tapex Creek")

        reading = self.discovery.observe_tunnel("Tapex Creek")

        self.assertEqual(reading.sysfs_id, "0-1")
        self.assertIs(reading.authorized, True)
        self.assertTrue(reading.complete)

    def test_support_is_read_from_the_domain_not_guessed_from_the_router(self) -> None:
        """The kernel publishes this per domain, and it is a separate fact.

        The router file existing says only that there is a file. Whether the
        domain supports de-authorization at all is answered one level up, and
        it is the answer that decides whether this dock can ever do it.
        """
        self.fake.tunnel("Tapex Creek")
        self.fake.domain("0", deauthorization="1")

        reading = self.discovery.observe_tunnel("Tapex Creek")

        self.assertIs(reading.capability, TunnelCapability.SUPPORTED)

    def test_a_domain_that_says_no_is_unsupported_not_unknown(self) -> None:
        self.fake.tunnel("Tapex Creek")
        self.fake.domain("0", deauthorization="0")

        reading = self.discovery.observe_tunnel("Tapex Creek")

        self.assertIs(reading.capability, TunnelCapability.NOT_SUPPORTED)
        self.assertFalse(reading.deauthorizable)

    def test_an_absent_domain_attribute_is_unknown_not_unsupported(self) -> None:
        """Not every kernel publishes it, and silence is not a refusal.

        Reading absence as NOT_SUPPORTED would tell a player their dock
        cannot do this, permanently, on the strength of a file nobody wrote.
        """
        self.fake.tunnel("Tapex Creek")
        self.fake.domain("0", deauthorization=None)

        reading = self.discovery.observe_tunnel("Tapex Creek")

        self.assertIs(reading.capability, TunnelCapability.UNKNOWN)

    def test_a_nonsense_domain_attribute_is_unknown(self) -> None:
        self.fake.tunnel("Tapex Creek")
        self.fake.domain("0", deauthorization="maybe")

        reading = self.discovery.observe_tunnel("Tapex Creek")

        self.assertIs(reading.capability, TunnelCapability.UNKNOWN)

    def test_the_router_of_another_domain_is_not_consulted(self) -> None:
        """`0-1` belongs to domain0, and domain1 answers for something else."""
        self.fake.tunnel("Tapex Creek")
        self.fake.domain("1", deauthorization="1")

        reading = self.discovery.observe_tunnel("Tapex Creek")

        self.assertIs(reading.capability, TunnelCapability.UNKNOWN)

    def test_write_permission_is_its_own_axis(self) -> None:
        """Supported and writable are two answers, and both are required."""
        self.fake.tunnel("Tapex Creek")
        self.fake.domain("0", deauthorization="1")

        reading = self.discovery.observe_tunnel("Tapex Creek")

        self.assertIs(reading.write_permission, WritePermission.WRITABLE)
        self.assertTrue(reading.deauthorizable)

    def test_an_absent_authorized_file_leaves_permission_unknown(self) -> None:
        """Absent is unknown here, and support is still the domain's answer."""
        self.fake.tunnel("Tapex Creek", authorized=None)
        self.fake.domain("0", deauthorization="1")

        reading = self.discovery.observe_tunnel("Tapex Creek")

        self.assertIs(reading.write_permission, WritePermission.UNKNOWN)
        self.assertIs(reading.capability, TunnelCapability.SUPPORTED)
        self.assertFalse(reading.deauthorizable)

    def test_two_routers_publishing_one_name_refuse_to_resolve(self) -> None:
        """A device_name is a product string, not an identity.

        Two identical docks publish the same one. Returning whichever sorted
        first would name a router the caller did not mean, and the only thing
        downstream does with a router is deauthorize it.
        """
        self.fake.tunnel("Tapex Creek")
        second = self.fake.thunderbolt / "0-3"
        second.mkdir(parents=True, exist_ok=True)
        (second / "device_name").write_text("Tapex Creek", encoding="utf-8")
        (second / "authorized").write_text("1", encoding="utf-8")

        reading = self.discovery.observe_tunnel("Tapex Creek")

        self.assertTrue(reading.ambiguous)
        self.assertFalse(reading.complete)
        self.assertEqual(reading.sysfs_id, "")
        self.assertIsNone(reading.authorized)

    def test_one_router_among_others_still_resolves(self) -> None:
        """Ambiguity is two matches, not two routers."""
        self.fake.tunnel("Tapex Creek")
        other = self.fake.thunderbolt / "0-3"
        other.mkdir(parents=True, exist_ok=True)
        (other / "device_name").write_text("Some Other Dock", encoding="utf-8")

        reading = self.discovery.observe_tunnel("Tapex Creek")

        self.assertEqual(reading.sysfs_id, "0-1")
        self.assertFalse(reading.ambiguous)
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
