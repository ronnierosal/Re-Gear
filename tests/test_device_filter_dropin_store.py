import os
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from backend.hdm.delivery.device_filter_dropin_store import DropinStore, NAME, BACKUP


class ValidationTests(unittest.TestCase):
    def test_fixture_authority_paired(self):
        with self.assertRaises(ValueError):
            DropinStore(owner_uid=0)


@unittest.skipUnless(sys.platform == 'linux', 'Linux durable drop-in fixture')
class DropinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.unit = 'gamescope-session.service'
        self.directory = self.root / (self.unit + '.d')
        self.directory.mkdir()
        self.path = self.directory / NAME
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)
        self.store = DropinStore(owner_uid=os.getuid(), trusted_directory_fd=self.fd)

    def test_absence_restored_and_no_replay(self):
        self.store.apply(self.unit, b'candidate')
        self.store.apply(self.unit, b'candidate')
        self.store.restore(self.unit)
        self.store.restore(self.unit)
        self.assertFalse(self.path.exists())
        with self.assertRaises(ValueError):
            self.store.apply(self.unit, b'candidate')

    def test_exact_bytes_mode_and_owner_restored(self):
        self.path.write_bytes(b'old\x00\xff')
        self.path.chmod(0o640)
        original = self.path.stat()
        self.store.apply(self.unit, b'candidate')
        self.store.restore(self.unit)
        restored = self.path.stat()
        self.assertEqual(self.path.read_bytes(), b'old\x00\xff')
        self.assertEqual((restored.st_uid, restored.st_gid, restored.st_mode),
                         (original.st_uid, original.st_gid, original.st_mode))

    def test_foreign_replacement_not_overwritten(self):
        self.store.apply(self.unit, b'candidate')
        self.path.write_bytes(b'foreign')
        for action in (lambda: self.store.apply(self.unit, b'candidate'), lambda: self.store.restore(self.unit)):
            with self.assertRaises(ValueError):
                action()
        self.assertEqual(self.path.read_bytes(), b'foreign')

    def test_backup_failure_prevents_mutation_and_retry(self):
        original = self.store._write
        def fail_candidate(directory, name, snapshot, **kwargs):
            if name == NAME:
                raise OSError('injected before candidate')
            return original(directory, name, snapshot, **kwargs)
        with patch.object(self.store, '_write', side_effect=fail_candidate):
            with self.assertRaises(OSError):
                self.store.apply(self.unit, b'candidate')
        self.assertTrue((self.directory / BACKUP).exists())
        self.assertFalse(self.path.exists())
        self.store.apply(self.unit, b'candidate')
        self.store.restore(self.unit)

    def test_interrupted_restore_after_mutation_retry(self):
        self.store.apply(self.unit, b'candidate')
        original = self.store._record
        def fail_complete(directory, record, **kwargs):
            if record['phase'] == 'restored':
                raise OSError('injected completion failure')
            return original(directory, record, **kwargs)
        with patch.object(self.store, '_record', side_effect=fail_complete):
            with self.assertRaises(OSError):
                self.store.restore(self.unit)
        self.assertFalse(self.path.exists())
        self.store.restore(self.unit)

    def test_symlink_target_rejected(self):
        outside = self.root / 'outside'
        outside.write_bytes(b'outside')
        self.path.symlink_to(outside)
        with self.assertRaises(OSError):
            self.store.apply(self.unit, b'candidate')
        self.assertEqual(outside.read_bytes(), b'outside')

    def test_copied_other_unit_backup_rejected(self):
        self.store.apply(self.unit, b'candidate')
        other = self.root / 'steam-launcher.service.d'
        other.mkdir()
        backup = other / BACKUP
        backup.write_bytes((self.directory / BACKUP).read_bytes())
        backup.chmod(0o600)
        with self.assertRaises(ValueError):
            self.store.apply('steam-launcher.service', b'candidate')
        self.assertFalse((other / NAME).exists())

    def test_invalid_candidate_and_boolean_version_rejected(self):
        self.store.apply(self.unit, b'candidate')
        backup = self.directory / BACKUP
        original = json.loads(backup.read_bytes())
        for update in ({'candidate': None}, {'version': True}):
            backup.write_text(json.dumps(dict(original, **update)))
            with self.assertRaises(ValueError):
                self.store.restore(self.unit)
        self.assertEqual(self.path.read_bytes(), b'candidate')

    def test_fixed_unit_only(self):
        with self.assertRaises(ValueError):
            self.store.apply('../other', b'candidate')

    def test_wrong_trial_candidate_blocks_restore(self):
        self.store.apply(self.unit,b'candidate')
        with self.assertRaises(ValueError):
            self.store.restore(self.unit,expected_candidate=b'other-trial')
        self.assertEqual(self.path.read_bytes(),b'candidate')
        self.store.restore(self.unit,expected_candidate=b'candidate')
        self.assertFalse(self.path.exists())


if __name__ == '__main__':
    unittest.main()
