"""Public observation checks using the existing independent temporary-file harness."""
import unittest
from unittest.mock import patch
from pathlib import Path

import test_dock_branch_fail_closed as fixtures
from regear.domain.dock_teardown import StorageEvidenceGap as Gap


class StorageGapContractTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DiscoveryFailClosedTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_multiple_gaps_preserve_mounts_and_declaration_order(self):
        f = self.fixture
        (f.block / "sda" / "sda1" / "dev").unlink()
        f.mountinfo.write_text(
            "36 25 99:0 / /alias rw - ext4 /dev/disk/by-uuid/missing rw\n"
            "truncated\n"
            "37 25 8:0 / /known rw - ext4 /dev/sda rw\n",
            encoding="utf-8",
        )
        f.swaps.unlink()
        reading = f.storage()
        self.assertEqual(reading.mounts, ("/known",))
        self.assertFalse(reading.complete)
        self.assertEqual(reading.gaps, (
            Gap.MOUNT_LINE_UNPARSABLE, Gap.MOUNT_SOURCE_UNATTRIBUTABLE,
            Gap.DEVICE_NUMBERS_INCOMPLETE, Gap.SWAPS_UNREADABLE,
        ))

    def test_two_unreadable_namespaces_report_one_gap(self):
        f = self.fixture
        denied = set()
        for pid in ("12", "34"):
            directory = f.proc / pid
            directory.mkdir()
            denied.add(directory / "mountinfo")
        original = Path.read_text

        def read(path, *args, **kwargs):
            if path in denied:
                raise PermissionError("fixture namespace")
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", read):
            reading = f.storage()
        self.assertEqual(reading.gaps, (Gap.MOUNT_NAMESPACE_UNREADABLE,))
        self.assertFalse(reading.complete)

    def test_invalid_controller_is_incomplete_without_platform_specific_path(self):
        reading = self.fixture.discovery.observe_storage("not-a-bdf")
        self.assertEqual(reading.gaps, (Gap.BLOCK_DEVICE_WALK_INCOMPLETE,))
        self.assertFalse(reading.complete)

    def test_absent_controller_is_complete_without_platform_specific_path(self):
        self.fixture.controller.rmdir()
        reading = self.fixture.discovery.observe_storage(fixtures.CONTROLLER)
        self.assertEqual(reading.gaps, ())
        self.assertTrue(reading.complete)
