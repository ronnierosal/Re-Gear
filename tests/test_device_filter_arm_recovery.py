from contextlib import contextmanager
from dataclasses import replace
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.hdm.delivery.device_filter_arm import FilterArmStore
from backend.hdm.delivery.device_filter_arm_recovery import clear_recovered_arm
from backend.hdm.delivery.device_filter_journal import JournalRecord
from backend.hdm.delivery.device_filter_lifecycle import (
    LaunchBinding, FilterLifecycle, Phase, OwnedFilter, DirectCleanupStage)
from tests.test_device_filter_arm import arm


@unittest.skipUnless(sys.platform == 'linux', 'Linux serialized arm recovery')
class ArmRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, fd)
        self.store = FilterArmStore(owner_uid=os.geteuid(), trusted_directory_fd=fd)
        self.arm = arm()
        self.store.arm(self.arm)
        binding = LaunchBinding('a'*64, 'op', self.arm.unit, 'e'*32, 1000,
                                50, 60, 70, 80, 'b'*64, 99)
        self.record = JournalRecord(1, FilterLifecycle(binding, Phase.CANCELLED))
        @contextmanager
        def transaction():
            yield SimpleNamespace(read=lambda *args: self.record)
        self.journal = SimpleNamespace(transaction=transaction)

    def clear(self, **kwargs):
        return clear_recovered_arm(self.journal, self.store, self.arm,
                                   current_boot_hash='a'*64, publisher_quiesced=True, **kwargs)

    def test_complete_recovery_removes_only_exact_arm_and_retries(self):
        result = self.clear()
        self.assertEqual(result.outcome, 'arm_removed')
        self.assertFalse(result.launch_authorized)
        self.assertFalse(result.disconnect_clearance)
        self.assertIsNone(self.store.read(self.arm.unit))
        self.assertEqual(self.clear().outcome, 'arm_already_absent')

    def test_direct_detach_proof_alone_is_not_complete(self):
        state = replace(self.record.lifecycle, owned=OwnedFilter(7, '4'*64, True, True, 8, 80))
        self.record = replace(self.record, lifecycle=state,
                              direct_cleanup=DirectCleanupStage.DETACHED_VERIFIED)
        with self.assertRaises(ValueError): self.clear()
        self.assertEqual(self.store.read(self.arm.unit), self.arm)
        self.record = replace(self.record, direct_cleanup=DirectCleanupStage.COMPLETE)
        self.assertEqual(self.clear().outcome, 'arm_removed')

    def test_no_quiescence_or_wrong_boot_leaves_arm(self):
        for options in (dict(current_boot_hash='a'*64),
                        dict(current_boot_hash='f'*64, publisher_quiesced=True)):
            with self.assertRaises(ValueError):
                clear_recovered_arm(self.journal, self.store, self.arm, **options)
        self.assertEqual(self.store.read(self.arm.unit), self.arm)

    def test_replacement_arm_is_not_removed(self):
        self.clear()
        replacement = replace(self.arm, operation='replacement')
        self.store.arm(replacement)
        with self.assertRaises(ValueError): self.clear()
        self.assertEqual(self.store.read(self.arm.unit), replacement)

    def test_unlink_then_fsync_failure_can_retry(self):
        with patch('backend.hdm.delivery.device_filter_arm_recovery.os.fsync', side_effect=OSError('fsync')):
            with self.assertRaises(OSError): self.clear()
        self.assertIsNone(self.store.read(self.arm.unit))
        self.assertEqual(self.clear().outcome, 'arm_already_absent')

    def test_writer_lock_serializes_clear_and_publication(self):
        with self.store._writer_directory():
            with self.assertRaises(BlockingIOError): self.clear()
            with self.assertRaises(BlockingIOError): self.store.arm(self.arm)
        self.assertEqual(self.store.read(self.arm.unit), self.arm)

    def test_unlink_failure_retains_arm(self):
        with patch('backend.hdm.delivery.device_filter_arm_recovery.os.unlink', side_effect=OSError('unlink')):
            with self.assertRaises(OSError): self.clear()
        self.assertEqual(self.store.read(self.arm.unit), self.arm)


if __name__ == '__main__': unittest.main()
