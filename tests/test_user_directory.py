"""Real Linux descriptor/race regressions; Windows runs store compatibility tests."""
import os
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from hdm.delivery.user_directory import UserDirectory
from hdm.delivery.support_export import SupportBundleFileWriter


@unittest.skipUnless(sys.platform == "linux", "requires real Linux directory descriptors")
class UserDirectoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.outside = self.root / "outside"
        self.outside.mkdir()
        self.uid, self.gid = os.getuid(), os.getgid()

    def directory(self, path):
        return UserDirectory(path, self.uid, self.gid, create_from=self.home, create=True)

    def test_preserves_existing_parent_modes_and_owns_new_directories(self):
        self.home.chmod(0o755)
        with self.directory(self.home / "config" / "service") as directory:
            directory.publish("managed", b"reviewed", 0o644)
        self.assertEqual(self.home.stat().st_mode & 0o777, 0o755)
        target = self.home / "config/service/managed"
        self.assertEqual(target.read_bytes(), b"reviewed")
        self.assertEqual(target.stat().st_uid, self.uid)
        self.assertEqual(target.stat().st_mode & 0o777, 0o644)

    def test_requested_final_mode_preserves_private_intermediate_and_existing_modes(self):
        target = self.home / 'config' / 'service'
        with UserDirectory(target, self.uid, self.gid, create_from=self.home,
                           create=True, final_mode=0o755):
            pass
        self.assertEqual(target.stat().st_mode & 0o777, 0o755)
        self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)
        with self.directory(target):
            pass
        self.assertEqual(target.stat().st_mode & 0o777, 0o755)
        with self.assertRaises(ValueError):
            UserDirectory(target, final_mode=0o777)

    @unittest.skipUnless(getattr(os, 'geteuid', lambda: -1)() == 0,
                         'requires root to exercise distinct destination credentials')
    def test_root_delivers_to_distinct_user_with_correct_ownership(self):
        uid = gid = 65534
        self.root.chmod(0o755)
        os.chown(self.home, uid, gid)
        target = self.home / 'config' / 'service'
        with UserDirectory(target, uid, gid, create_from=self.home, create=True) as directory:
            directory.publish('managed', b'reviewed', 0o644)
        for entry in (target.parent, target, target / 'managed'):
            self.assertEqual((entry.stat().st_uid, entry.stat().st_gid), (uid, gid))
        self.assertEqual((target / 'managed').read_bytes(), b'reviewed')
        bundle = SimpleNamespace(json_text='{"reviewed":true}', size_bytes=17)
        writer = SupportBundleFileWriter(allowed_home_parent=self.root)
        result = writer.save(self.home, bundle)
        exported = self.home / result.relative_path
        self.assertEqual(exported.read_text(), bundle.json_text)
        for entry in (exported.parent, exported):
            self.assertEqual((entry.stat().st_uid, entry.stat().st_gid), (uid, gid))
        self.assertEqual(exported.stat().st_mode & 0o777, 0o600)

    def test_rejects_symlink_in_any_parent_component(self):
        (self.home / "config").symlink_to(self.outside, target_is_directory=True)
        with self.assertRaises((OSError, ValueError)):
            self.directory(self.home / "config" / "service")
        self.assertEqual(list(self.outside.iterdir()), [])

    def test_directory_replaced_after_mkdir_is_not_chowned(self):
        original = subprocess.run
        def race(*args, **kwargs):
            result = original(*args, **kwargs)
            (self.home / 'config').rename(self.home / 'moved')
            (self.home / 'config').symlink_to(self.outside, target_is_directory=True)
            return result
        before = self.outside.stat()
        with patch('subprocess.run', side_effect=race), patch('os.fchown') as chown:
            with self.assertRaises((OSError, ValueError)):
                self.directory(self.home / 'config')
            chown.assert_not_called()
        self.assertEqual(self.outside.stat().st_uid, before.st_uid)
        self.assertEqual(self.outside.stat().st_mode, before.st_mode)

    def test_pinned_parent_swap_cannot_redirect_publication_or_removal(self):
        path = self.home / "config"
        path.mkdir()
        with self.directory(path) as directory:
            path.rename(self.home / "moved")
            path.symlink_to(self.outside, target_is_directory=True)
            directory.publish("managed", b"reviewed", 0o644)
            self.assertEqual(list(self.outside.iterdir()), [])
            directory.remove_matching("managed", b"reviewed", 100)
        self.assertEqual(list((self.home / "moved").iterdir()), [])

    def test_destination_created_at_publication_is_never_overwritten(self):
        original = os.link
        def race(source, destination, **kwargs):
            (self.home / destination).write_bytes(b"user content")
            return original(source, destination, **kwargs)
        with self.directory(self.home) as directory, patch("os.link", side_effect=race):
            with self.assertRaises(FileExistsError):
                directory.publish("managed", b"reviewed", 0o644)
        self.assertEqual((self.home / "managed").read_bytes(), b"user content")
        self.assertEqual([p.name for p in self.home.iterdir()], ["managed"])

    def test_temporary_replacement_does_not_redirect_metadata_or_publication(self):
        original = os.fchmod
        victim = self.outside / "victim"
        victim.write_bytes(b"private")
        victim.chmod(0o600)
        def race(fd, mode):
            temporary = next(self.home.glob(".re-gear-*.tmp"))
            temporary.rename(self.home / "original")
            temporary.symlink_to(victim)
            return original(fd, mode)
        with self.directory(self.home) as directory, patch("os.fchmod", side_effect=race):
            directory.publish("managed", b"reviewed", 0o644)
        self.assertEqual((self.home / "managed").read_bytes(), b"reviewed")
        self.assertEqual(victim.read_bytes(), b"private")
        self.assertEqual(victim.stat().st_mode & 0o777, 0o600)
        self.assertFalse(list(self.home.glob(".re-gear-*.tmp")))

    def test_write_failure_removes_temporary_without_publishing(self):
        with self.directory(self.home) as directory, patch("os.write", side_effect=OSError("failed")):
            with self.assertRaises(OSError):
                directory.publish("managed", b"reviewed", 0o644)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_modified_or_symlinked_managed_file_is_preserved(self):
        victim = self.outside / "victim"
        victim.write_bytes(b"reviewed")
        target = self.home / "managed"
        target.symlink_to(victim)
        with self.directory(self.home) as directory:
            with self.assertRaises((OSError, ValueError)):
                directory.remove_matching("managed", b"reviewed", 100)
        self.assertEqual(victim.read_bytes(), b"reviewed")
        self.assertTrue(target.is_symlink())
