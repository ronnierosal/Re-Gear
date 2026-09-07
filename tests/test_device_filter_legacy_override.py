import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from backend.hdm.delivery.device_filter_legacy_override import LegacyOverrideStore, NAMES
from backend.hdm.ports.presentation_activation import GamescopeUserContext


class BindingTests(unittest.TestCase):
    def test_fixture_authority_is_paired(self):
        with self.assertRaises(ValueError):
            LegacyOverrideStore(owner_uid=0)


@unittest.skipUnless(sys.platform == 'linux', 'Linux legacy override fixture')
class LegacyOverrideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / 'home'
        self.home.mkdir()
        self.backups = self.base / 'backups'
        self.backups.mkdir(mode=0o700)
        self.root_fd = os.open(self.backups, os.O_RDONLY | os.O_DIRECTORY)
        self.home_fd = os.open(self.home, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.root_fd)
        self.addCleanup(os.close, self.home_fd)
        self.uid = os.getuid()
        self.user = GamescopeUserContext('fixture', self.uid, os.getgid(), self.home,
            Path('/run/user') / str(self.uid), Path('/run/user') / str(self.uid) / 'bus')
        self.unit = 'gamescope-session.service'
        self.target = self.home / '.config/systemd/user' / (self.unit + '.d') / NAMES[self.unit]
        self.target.parent.mkdir(parents=True)
        self.store = LegacyOverrideStore(owner_uid=self.uid, trusted_root_fd=self.root_fd,
                                          trusted_home_fd=self.home_fd)

    def suspend(self, expected=b'managed'):
        return self.store.suspend(self.user, self.unit, 'trial-1', expected_original=expected)

    def restore(self, expected=b'managed'):
        return self.store.restore(self.user, self.unit, 'trial-1', expected_original=expected)

    def test_exact_restore_and_no_replay(self):
        self.target.write_bytes(b'managed')
        self.target.chmod(0o640)
        before = self.target.stat()
        self.suspend()
        self.suspend()
        self.assertFalse(self.target.exists())
        self.restore()
        self.restore()
        after = self.target.stat()
        self.assertEqual(self.target.read_bytes(), b'managed')
        self.assertEqual((after.st_mode, after.st_uid, after.st_gid),
                         (before.st_mode, before.st_uid, before.st_gid))
        with self.assertRaises(ValueError):
            self.suspend()

    def test_original_absence(self):
        self.suspend(None)
        self.restore(None)
        self.assertFalse(self.target.exists())

    def test_foreign_original_or_replacement_never_overwritten(self):
        self.target.write_bytes(b'foreign')
        with self.assertRaises(ValueError):
            self.suspend()
        self.target.write_bytes(b'managed')
        self.suspend()
        self.target.write_bytes(b'foreign')
        with self.assertRaises(ValueError):
            self.restore()
        self.assertEqual(self.target.read_bytes(), b'foreign')

    def test_interruption_after_move_can_restore(self):
        self.target.write_bytes(b'managed')
        original = self.store._save
        def fail_complete(root, name, record, **kwargs):
            if record['phase'] == 'suspended':
                raise OSError('injected suspension completion')
            return original(root, name, record, **kwargs)
        with patch.object(self.store, '_save', side_effect=fail_complete):
            with self.assertRaises(OSError):
                self.suspend()
        self.assertFalse(self.target.exists())
        self.restore()
        self.assertEqual(self.target.read_bytes(), b'managed')

    def test_interruption_after_restore_retries(self):
        self.target.write_bytes(b'managed')
        self.suspend()
        original = self.store._save
        def fail_complete(root, name, record, **kwargs):
            if record['phase'] == 'restored':
                raise OSError('injected restore completion')
            return original(root, name, record, **kwargs)
        with patch.object(self.store, '_save', side_effect=fail_complete):
            with self.assertRaises(OSError):
                self.restore()
        self.assertEqual(self.target.read_bytes(), b'managed')
        self.restore()

    def test_backup_failure_prevents_move(self):
        self.target.write_bytes(b'managed')
        with patch.object(self.store, '_save', side_effect=OSError('backup failed')):
            with self.assertRaises(OSError):
                self.suspend()
        self.assertEqual(self.target.read_bytes(), b'managed')

    def test_symlink_target_rejected(self):
        outside = self.base / 'outside'
        outside.write_bytes(b'managed')
        self.target.symlink_to(outside)
        with self.assertRaises(OSError):
            self.suspend()
        self.assertEqual(outside.read_bytes(), b'managed')

    def test_mismatched_operation_cannot_restore(self):
        self.target.write_bytes(b'managed')
        self.suspend()
        with self.assertRaises(ValueError):
            self.store.restore(self.user, self.unit, 'other', expected_original=b'managed')
        self.assertFalse(self.target.exists())

    def test_raced_replacement_is_retained(self):
        self.target.write_bytes(b'managed')
        rename = os.rename
        def race(*args, **kwargs):
            self.target.write_bytes(b'foreign-race')
            return rename(*args, **kwargs)
        with patch('backend.hdm.delivery.device_filter_legacy_override.os.rename', side_effect=race):
            with self.assertRaises(ValueError):
                self.suspend()
        held = list(self.backups.glob('*.held'))
        self.assertEqual(len(held), 1)
        self.assertEqual(held[0].read_bytes(), b'foreign-race')
        with self.assertRaises(ValueError):
            self.restore()
        self.assertEqual(self.target.read_bytes(), b'foreign-race')
