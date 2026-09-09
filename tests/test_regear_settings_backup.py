import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    'settings_backup', Path(__file__).resolve().parents[1] / 'scripts/regear_settings_backup.py')
backup_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup_tool)


class SettingsBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'nested').mkdir()
        (self.source / 'nested/empty').mkdir()
        (self.source / 'nested/preferences.json').write_bytes(b'{"enabled":true}\n')
        (self.source / 'empty-file').write_bytes(b'')
        self.backup = self.root / 'backup'
        self.destination = self.root / 'restored'

    def make_backup(self):
        return backup_tool.backup(self.source, self.backup)

    def rewrite_manifest(self, mutation):
        path = self.backup / 'manifest.json'
        manifest = json.loads(path.read_bytes())
        mutation(manifest)
        raw = json.dumps(manifest).encode('utf-8')
        path.write_bytes(raw)
        (self.backup / 'manifest.sha256').write_bytes(hashlib.sha256(raw).hexdigest().encode('ascii'))

    def test_roundtrip_nested_empty_and_metadata(self):
        if os.name == 'posix':
            (self.source / 'nested/preferences.json').chmod(0o640)
        manifest = self.make_backup()
        self.assertEqual(manifest, backup_tool.verify(self.backup))
        backup_tool.restore(self.backup, self.destination)
        self.assertEqual((self.destination / 'nested/preferences.json').read_bytes(), b'{"enabled":true}\n')
        self.assertTrue((self.destination / 'nested/empty').is_dir())
        self.assertEqual((self.destination / 'empty-file').read_bytes(), b'')
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(self.backup.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((self.backup / 'files/nested/preferences.json').stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((self.destination / 'nested/preferences.json').stat().st_mode), 0o640)
            self.assertEqual(self.destination.stat().st_uid, self.source.stat().st_uid)

    def test_corrupted_payload_refused_before_destination_creation(self):
        self.make_backup()
        (self.backup / 'files/nested/preferences.json').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            backup_tool.restore(self.backup, self.destination)
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.root.glob('.regear-restore-*')), [])

    def test_manifest_checksum_and_incomplete_refused(self):
        self.make_backup()
        (self.backup / 'manifest.json').write_bytes(b'{}')
        with self.assertRaises(ValueError):
            backup_tool.verify(self.backup)
        (self.backup / 'manifest.sha256').unlink()
        with self.assertRaises(ValueError):
            backup_tool.verify(self.backup)

    def test_destination_and_backup_conflicts_preserve_existing_data(self):
        self.make_backup()
        self.destination.mkdir()
        sentinel = self.destination / 'keep'
        sentinel.write_text('keep')
        with self.assertRaises(FileExistsError):
            backup_tool.restore(self.backup, self.destination)
        self.assertEqual(sentinel.read_text(), 'keep')
        with self.assertRaises(FileExistsError):
            self.make_backup()
        backup_tool.verify(self.backup)
        sentinel.unlink()
        with self.assertRaises(FileExistsError):
            backup_tool.restore(self.backup, self.destination)

    def test_unsafe_manifest_paths_even_with_valid_checksum(self):
        self.make_backup()
        for value in ['../escape', '/absolute', 'a/../escape', 'C:/escape', 'a\\escape', './x', 'a//x', 'CON', 'x.']:
            with self.subTest(value=value):
                self.rewrite_manifest(lambda m: m['entries'][0].update(path=value))
                with self.assertRaises(ValueError):
                    backup_tool.restore(self.backup, self.destination)
                self.assertFalse(self.destination.exists())

    def test_extra_entries_and_duplicates_rejected(self):
        self.make_backup()
        extra = self.backup / 'files/unlisted'
        extra.write_bytes(b'x')
        with self.assertRaises(ValueError):
            backup_tool.verify(self.backup)
        extra.unlink()
        self.rewrite_manifest(lambda m: m['entries'].append(m['entries'][0]))
        with self.assertRaises(ValueError):
            backup_tool.verify(self.backup)

    def test_symlinks_rejected_in_source_and_backup(self):
        link = self.source / 'link'
        try:
            link.symlink_to(self.source / 'empty-file')
        except OSError:
            self.skipTest('symlink creation unavailable')
        with self.assertRaises(ValueError):
            self.make_backup()
        self.assertFalse(self.backup.exists())
        link.unlink()
        self.make_backup()
        (self.backup / 'files/link').symlink_to(self.source / 'empty-file')
        with self.assertRaises(ValueError):
            backup_tool.verify(self.backup)

    def test_size_limit_refuses_incomplete_backup(self):
        original = backup_tool.MAX_FILE_BYTES
        backup_tool.MAX_FILE_BYTES = 1
        try:
            with self.assertRaises(ValueError):
                self.make_backup()
        finally:
            backup_tool.MAX_FILE_BYTES = original
        with self.assertRaises(ValueError):
            backup_tool.verify(self.backup)

    def test_backup_inside_source_rejected(self):
        with self.assertRaises(ValueError):
            backup_tool.backup(self.source, self.source / 'backup')

    @unittest.skipUnless(os.name == 'posix', 'POSIX special file')
    def test_special_file_rejected(self):
        os.mkfifo(self.source / 'fifo')
        with self.assertRaises(ValueError):
            self.make_backup()


if __name__ == '__main__':
    unittest.main()
