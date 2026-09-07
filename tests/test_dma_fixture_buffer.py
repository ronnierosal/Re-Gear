import ctypes
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from backend.hdm.delivery import dma_fixture_buffer as buffer


class DmaFixtureBufferTests(unittest.TestCase):
    def setUp(self):
        for key, value in (("system", "Linux"), ("machine", "x86_64")):
            context = patch.object(buffer.platform, key, return_value=value)
            context.start(); self.addCleanup(context.stop)
        self.events = []
        self.fail = None
        self.info = SimpleNamespace(st_mode=stat.S_IFCHR, st_rdev=123)
        self.open = Mock(return_value=10)
        self.inheritable = Mock(return_value=False)
        def ioctl(fd, request, arg):
            self.events.append(("ioctl", fd, request))
            if request == self.fail:
                raise OSError("fixture ioctl failure")
            if request == buffer.GEM_CREATE:
                self.assertEqual((arg.request.bo_size, arg.request.alignment, arg.request.domains, arg.request.domain_flags), (4096, 4096, 2, 0))
                arg.result.handle = 7
            elif request == buffer.PRIME_HANDLE_TO_FD:
                self.assertEqual((arg.handle, arg.flags, arg.fd), (7, 0x80002, -1))
                arg.fd = 11
            elif request == buffer.GEM_CLOSE:
                self.assertEqual((arg.handle, arg.pad), (7, 0))
            else:
                raise AssertionError("unexpected ioctl")
        self.ioctl = ioctl
        self.close = Mock(side_effect=lambda fd: self.events.append(("close", fd)))

    def owner(self):
        return buffer.DmaFixtureBuffer(open_fd=self.open, fstat=lambda fd: self.info,
            close_fd=self.close, ioctl=self.ioctl, effective_uid=lambda: 0,
            get_inheritable=self.inheritable)

    def test_uapi_and_exact_allocation_export_cleanup(self):
        self.assertEqual(ctypes.sizeof(buffer.GemCreate), 32)
        self.assertEqual(ctypes.sizeof(buffer.PrimeHandle), 12)
        self.assertEqual(ctypes.sizeof(buffer.GemClose), 8)
        with self.owner() as owner:
            self.assertEqual(owner.allocate("/dev/dri/renderD150", 123), 11)
            self.assertEqual(owner.export_fd, 11)
            self.open.assert_called_once_with("/dev/dri/renderD150", 0xa0002)
        self.assertEqual(self.events, [("ioctl", 10, 0xc0206440), ("ioctl", 10, 0xc00c642d),
            ("close", 11), ("ioctl", 10, 0x40086409), ("close", 10)])
        owner.close()
        self.assertEqual(self.close.call_count, 2)

    def test_create_and_export_failures_release_acquired_ownership(self):
        for request, expected in ((buffer.GEM_CREATE, [("close", 10)]),
            (buffer.PRIME_HANDLE_TO_FD, [("ioctl", 10, buffer.GEM_CLOSE), ("close", 10)])):
            self.events.clear(); self.fail = request
            owner = self.owner()
            with self.assertRaises(OSError):
                owner.allocate("/dev/dri/renderD150", 123)
            self.assertEqual(self.events[-len(expected):], expected)
            self.assertIsNone(owner.render_fd)
            self.assertIsNone(owner.handle)

    def test_export_validation_failure_closes_export_and_gem(self):
        self.inheritable.return_value = True
        owner = self.owner()
        with self.assertRaises(ValueError):
            owner.allocate("/dev/dri/renderD150", 123)
        self.assertEqual(self.events[-3:], [("close", 11), ("ioctl", 10, buffer.GEM_CLOSE), ("close", 10)])

    def test_identity_failure_never_allocates(self):
        self.info.st_rdev = 999
        with self.assertRaises(ValueError):
            self.owner().allocate("/dev/dri/renderD150", 123)
        self.assertEqual(self.events, [("close", 10)])

    def test_open_and_fstat_failures_do_not_leak_render_fd(self):
        owner = self.owner()
        self.open.side_effect = OSError("open refused")
        with self.assertRaises(OSError):
            owner.allocate("/dev/dri/renderD150", 123)
        self.close.assert_not_called()
        self.open.side_effect = None
        owner._fstat = Mock(side_effect=OSError("fstat refused"))
        with self.assertRaises(OSError):
            owner.allocate("/dev/dri/renderD150", 123)
        self.assertEqual(self.events, [("close", 10)])

    def test_cleanup_attempts_remaining_ownership_after_failure(self):
        owner = self.owner()
        owner.allocate("/dev/dri/renderD150", 123)
        self.fail = buffer.GEM_CLOSE
        self.close.side_effect = lambda fd: (_ for _ in ()).throw(OSError("close")) if fd == 11 else self.events.append(("close", fd))
        with self.assertRaises(RuntimeError):
            owner.close()
        self.assertEqual(self.events[-1], ("close", 10))
        self.assertIsNone(owner.render_fd)

    def test_invalid_path_and_replay_never_open_again(self):
        owner = self.owner()
        for path in ("/dev/dri/card1", "/tmp/renderD150", "/dev/dri/../renderD150"):
            with self.assertRaises(ValueError):
                owner.allocate(path, 123)
        self.open.assert_not_called()
        owner.allocate("/dev/dri/renderD150", 123)
        with self.assertRaises(ValueError):
            owner.allocate("/dev/dri/renderD151", 124)
        self.assertEqual(self.open.call_count, 1)
        owner.close()

    def test_root_and_architecture_guard(self):
        with self.assertRaises(ValueError):
            buffer.DmaFixtureBuffer(effective_uid=lambda: 1000)
        with patch.object(buffer.platform, "machine", return_value="aarch64"), self.assertRaises(ValueError):
            self.owner()


if __name__ == "__main__":
    unittest.main()
