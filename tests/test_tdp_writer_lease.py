import builtins
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
from hdm.delivery.tdp_writer_lease import FileTdpWriterLease


class TdpWriterLeasePortableTests(unittest.TestCase):
    def test_relative_state_root_is_rejected(self):
        with self.assertRaises(ValueError):
            FileTdpWriterLease(Path("relative-state"))

    def test_missing_fcntl_fails_without_creating_lock_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lease = FileTdpWriterLease(root)
            original_import = builtins.__import__
            def unavailable(name, *args, **kwargs):
                if name == "fcntl":
                    raise ImportError("fcntl unavailable")
                return original_import(name, *args, **kwargs)
            with patch("builtins.__import__", side_effect=unavailable):
                self.assertFalse(lease.acquire())
            self.assertFalse(lease.held)
            self.assertEqual(list(root.iterdir()), [])
            lease.close()
            lease.close()

    @unittest.skipIf(os.name == "posix", "Real non-POSIX behavior only")
    def test_real_non_posix_failure_is_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lease = FileTdpWriterLease(root)
            self.assertFalse(lease.acquire())
            self.assertFalse(lease.held)
            self.assertEqual(list(root.iterdir()), [])


@unittest.skipUnless(sys.platform.startswith("linux"), "Real Linux flock and permission behavior required")
class TdpWriterLeaseLinuxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.first = FileTdpWriterLease(self.root)
        self.second = FileTdpWriterLease(self.root)
        self.addCleanup(self.first.close)
        self.addCleanup(self.second.close)

    def test_private_root_acquires_private_regular_lock_and_close_releases(self):
        self.assertTrue(self.first.acquire())
        self.assertTrue(self.first.held)
        self.assertTrue(self.first.acquire())
        metadata = (self.root / "tdp-writer.lock").stat()
        self.assertTrue(stat.S_ISREG(metadata.st_mode))
        self.assertEqual(stat.S_IMODE(metadata.st_mode), 0o600)
        self.assertEqual(metadata.st_uid, os.geteuid())
        self.assertFalse(self.second.acquire())
        self.assertFalse(self.second.held)
        self.first.close()
        self.first.close()
        self.assertFalse(self.first.held)
        self.assertTrue(self.second.acquire())

    def test_separate_process_cannot_take_held_lock_but_can_after_release(self):
        program = (
            "import sys; from pathlib import Path; "
            "sys.path.insert(0, sys.argv[1]); "
            "from hdm.delivery.tdp_writer_lease import FileTdpWriterLease; "
            "lease = FileTdpWriterLease(Path(sys.argv[2])); "
            "acquired = lease.acquire(); lease.close(); "
            "sys.exit(0 if acquired else 23)"
        )
        self.assertTrue(self.first.acquire())
        def child():
            return subprocess.run(
                (sys.executable, "-c", program, str(BACKEND), str(self.root)),
                shell=False, capture_output=True, timeout=5, check=False,
            )
        blocked = child()
        self.assertEqual(blocked.returncode, 23, blocked.stderr)
        self.first.close()
        released = child()
        self.assertEqual(released.returncode, 0, released.stderr)

    def test_group_or_other_writable_root_is_rejected_without_lock_file(self):
        for mode in (0o770, 0o702, 0o777):
            with self.subTest(mode=oct(mode)):
                self.root.chmod(mode)
                self.assertFalse(self.first.acquire())
                self.assertFalse(self.first.held)
                self.assertFalse((self.root / "tdp-writer.lock").exists())
        self.root.chmod(0o700)

    def test_missing_root_is_not_created(self):
        lease = FileTdpWriterLease(self.root / "missing")
        self.assertFalse(lease.acquire())
        self.assertFalse((self.root / "missing").exists())

    def test_root_symlink_is_rejected(self):
        target = self.root / "actual"
        target.mkdir(mode=0o700)
        link = self.root / "linked"
        link.symlink_to(target, target_is_directory=True)
        lease = FileTdpWriterLease(link)
        self.assertFalse(lease.acquire())
        self.assertFalse((target / "tdp-writer.lock").exists())

    def test_lock_symlink_is_rejected_without_changing_target(self):
        target = self.root / "unrelated"
        target.write_bytes(b"preserve this")
        target.chmod(0o600)
        (self.root / "tdp-writer.lock").symlink_to(target)
        self.assertFalse(self.first.acquire())
        self.assertFalse(self.first.held)
        self.assertEqual(target.read_bytes(), b"preserve this")

    def test_group_or_other_writable_lock_is_rejected(self):
        lock = self.root / "tdp-writer.lock"
        lock.touch(mode=0o600)
        for mode in (0o620, 0o602, 0o666):
            with self.subTest(mode=oct(mode)):
                lock.chmod(mode)
                self.assertFalse(self.first.acquire())
                self.assertFalse(self.first.held)
        lock.chmod(0o600)
        self.assertTrue(self.first.acquire())

    def test_directory_lock_target_is_rejected(self):
        (self.root / "tdp-writer.lock").mkdir(mode=0o700)
        self.assertFalse(self.first.acquire())
        self.assertFalse(self.first.held)


if __name__ == "__main__":
    unittest.main()
