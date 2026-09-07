import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, Mock

from backend.hdm.delivery.device_filter_listener import FilterListener


class ListenerValidationTests(unittest.TestCase):
    def test_startup_wait_is_separate_from_short_accept(self):
        listener = object.__new__(FilterListener)
        listener._owned_socket = Mock()
        listener.connection = Mock()
        accepted = Mock()
        listener.connection.accept.return_value = (accepted, None)
        self.assertIs(listener.accept_waiting(deadline=80, clock=lambda:10),accepted)
        listener.connection.settimeout.assert_called_once_with(70)
        with self.assertRaises(TimeoutError): listener.accept(deadline=80, clock=lambda:10)
        with self.assertRaises(TimeoutError): listener.accept_waiting(deadline=101, clock=lambda:10)

    def test_non_linux_rejected(self):
        with patch("backend.hdm.delivery.device_filter_listener.sys.platform", "win32"):
            with self.assertRaises(ValueError):
                FilterListener(1000)

    def test_unpaired_fixture_and_invalid_group_rejected(self):
        with patch("backend.hdm.delivery.device_filter_listener.sys.platform", "linux"):
            for kwargs in ({"owner_uid": 1000}, {"trusted_directory_fd": 9}):
                with self.assertRaises(ValueError):
                    FilterListener(1000, **kwargs)
            for group in (True, -1, "1000"):
                with self.assertRaises(ValueError):
                    FilterListener(group)


@unittest.skipUnless(sys.platform == "linux", "Linux Unix listener fixture")
class ListenerLinuxTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name)
        self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)

    def listener(self):
        return FilterListener(os.getgid(), owner_uid=os.getuid(), trusted_directory_fd=self.fd)

    def test_bind_connect_permissions_and_exact_cleanup(self):
        with self.listener() as listener:
            info = os.lstat(self.path / "launch.sock")
            self.assertTrue(stat.S_ISSOCK(info.st_mode))
            self.assertEqual(stat.S_IMODE(info.st_mode), 0o660)
            self.assertEqual((info.st_uid, info.st_gid), (os.getuid(), os.getgid()))
            with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as client:
                client.connect(str(self.path / "launch.sock"))
                with listener.accept(deadline=time.monotonic() + 1) as accepted:
                    client.send(b"fixture")
                    self.assertEqual(accepted.recv(10), b"fixture")
        self.assertFalse((self.path / "launch.sock").exists())
        self.assertTrue(self.path.is_dir())

    def test_existing_file_symlink_and_socket_never_removed(self):
        entry = self.path / "launch.sock"
        entry.write_bytes(b"preserve")
        with self.assertRaises(OSError):
            self.listener()
        self.assertEqual(entry.read_bytes(), b"preserve")
        entry.unlink()
        entry.symlink_to(self.path / "missing")
        with self.assertRaises(OSError):
            self.listener()
        self.assertTrue(entry.is_symlink())
        entry.unlink()
        with self.listener():
            original = entry.stat().st_ino
            with self.assertRaises(OSError):
                self.listener()
            self.assertEqual(entry.stat().st_ino, original)

    def test_replaced_socket_is_not_unlinked(self):
        listener = self.listener()
        entry = self.path / "launch.sock"
        entry.unlink()
        entry.write_text("replacement")
        with self.assertRaises(ValueError):
            listener.close()
        self.assertEqual(entry.read_text(), "replacement")
        self.assertIsNone(listener.directory)

    def test_missing_socket_reports_cleanup_failure(self):
        listener = self.listener()
        (self.path / "launch.sock").unlink()
        with self.assertRaises(FileNotFoundError):
            listener.close()
        self.assertIsNone(listener.directory)

    def test_deadline_bounds_and_timeout(self):
        with self.listener() as listener:
            for deadline in (True, 0, time.monotonic() + 6, float("nan")):
                with self.assertRaises(TimeoutError):
                    listener.accept(deadline=deadline)
            with self.assertRaises(TimeoutError):
                listener.accept(deadline=time.monotonic() + 0.01)

    def test_writable_fixture_parent_rejected(self):
        os.chmod(self.path, 0o777)
        try:
            with self.assertRaises(ValueError):
                self.listener()
        finally:
            os.chmod(self.path, 0o700)


if __name__ == "__main__":
    unittest.main()
