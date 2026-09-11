"""Linux fixture verification; no real sysfs mutations."""
import sys
from pathlib import Path
from dataclasses import replace
from tempfile import TemporaryDirectory
import unittest
from threading import Event, Thread
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from regear.adapters.steamos import whole_dock_writer as m

@unittest.skipUnless(sys.platform == 'linux', 'Linux descriptor semantics')
class WriterTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        root_patch = patch.object(m, 'SYSFS_DEVICES_ROOT', self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        self.usb = self.target(('pci0000:00', '0000:09:00.0'))
        self.router = self.target(('domain0', '0-0', '0-1'))
        self.up = self.root.joinpath(*self.usb.parts)
        self.rp = self.root.joinpath(*self.router.parts)
        (self.up / 'class').write_text('0x0c0330')
        (self.up / 'remove').write_bytes(b'')
        (self.rp / 'authorized').write_bytes(b'1')
        (self.root / 'domain0' / 'deauthorization').write_bytes(b'1')
    def target(self, parts):
        paths = [self.root]
        for part in parts:
            paths.append(paths[-1] / part)
            paths[-1].mkdir()
        return m.SysfsTarget(parts, tuple(m.NodeIdentity(p.stat().st_dev, p.stat().st_ino) for p in paths))
    def test_exact_bytes_and_duplicate(self):
        writer = m.WholeDockSysfsWriter()
        writer.remove_usb(self.usb, lambda: True)
        writer.deauthorize(self.router, lambda: True)
        self.assertEqual((self.up / 'remove').read_bytes(), b'1')
        self.assertEqual((self.rp / 'authorized').read_bytes(), b'0')
        with self.assertRaises(m.WriterRefused):
            writer.remove_usb(self.usb, lambda: True)
    def test_guard_exact_true_and_latched(self):
        for value in (False, None, 1):
            writer = m.WholeDockSysfsWriter()
            with self.assertRaises(m.WriterRefused):
                writer.remove_usb(self.usb, lambda: value)
            with self.assertRaises(m.WriterRefused):
                writer.deauthorize(self.router, lambda: True)
        self.assertEqual((self.up / 'remove').read_bytes(), b'')
    def test_wrong_identity(self):
        bad = replace(self.usb, identities=self.usb.identities[:-1] + (m.NodeIdentity(0, 0),))
        with self.assertRaises(m.WriterRefused):
            m.WholeDockSysfsWriter().remove_usb(bad, lambda: True)
    def test_wrong_class(self):
        (self.up / 'class').write_text('0x060400')
        with self.assertRaises(m.WriterRefused):
            m.WholeDockSysfsWriter().remove_usb(self.usb, lambda: True)
    def test_attribute_symlink(self):
        node = self.up / 'remove'
        other = self.up / 'untouched'
        other.write_bytes(b'')
        node.unlink()
        node.symlink_to(other)
        with self.assertRaises(OSError):
            m.WholeDockSysfsWriter().remove_usb(self.usb, lambda: True)
        self.assertEqual(other.read_bytes(), b'')
    def test_directory_symlink(self):
        other = self.up.with_name('other')
        self.up.rename(other)
        self.up.symlink_to(other)
        with self.assertRaises(OSError):
            m.WholeDockSysfsWriter().remove_usb(self.usb, lambda: True)
    def test_failed_write_latches(self):
        writer = m.WholeDockSysfsWriter()
        with patch.object(m.os, 'write', side_effect=TimeoutError('unresolved')):
            with self.assertRaises(TimeoutError):
                writer.remove_usb(self.usb, lambda: True)
        with self.assertRaises(m.WriterRefused):
            writer.deauthorize(self.router, lambda: True)
    def test_host_router(self):
        host = replace(self.router, parts=self.router.parts[:-1], identities=self.router.identities[:-1])
        with self.assertRaises(m.WriterRefused):
            m.WholeDockSysfsWriter().deauthorize(host, lambda: True)
    def test_unsupported_domain(self):
        (self.root / 'domain0' / 'deauthorization').write_bytes(b'0')
        with self.assertRaises(m.WriterRefused):
            m.WholeDockSysfsWriter().deauthorize(self.router, lambda: True)
    def test_reentrant_guard(self):
        writer = m.WholeDockSysfsWriter()
        def guard():
            writer.deauthorize(self.router, lambda: True)
            return True
        with self.assertRaises(m.WriterRefused):
            writer.remove_usb(self.usb, guard)
        self.assertEqual((self.up / 'remove').read_bytes(), b'')
    def test_path_escape(self):
        bad = replace(self.usb, parts=('..', self.usb.parts[-1]))
        with self.assertRaises(m.WriterRefused):
            m.WholeDockSysfsWriter().remove_usb(bad, lambda: True)
    def test_close_failure_keeps_latch(self):
        writer = m.WholeDockSysfsWriter()
        original = m.os.close
        ready = [False]
        def guard():
            ready[0] = True
            return True
        def close(fd):
            original(fd)
            if ready[0]:
                ready[0] = False
                raise OSError('close failure')
        with patch.object(m.os, 'close', side_effect=close):
            with self.assertRaises(OSError):
                writer.remove_usb(self.usb, guard)
        with self.assertRaises(m.WriterRefused):
            writer.deauthorize(self.router, lambda: True)
    def test_concurrent_tunnel_call_is_refused_without_queueing(self):
        writer = m.WholeDockSysfsWriter()
        entered, release = Event(), Event()
        errors = []
        def guard():
            entered.set()
            return release.wait(3)
        def first():
            try:
                writer.remove_usb(self.usb, guard)
            except Exception as error:
                errors.append(error)
        thread = Thread(target=first)
        thread.start()
        try:
            self.assertTrue(entered.wait(3))
            with self.assertRaisesRegex(m.WriterRefused, 'writer_busy'):
                writer.deauthorize(self.router, lambda: True)
            self.assertEqual((self.rp / 'authorized').read_bytes(), b'1')
        finally:
            release.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual((self.up / 'remove').read_bytes(), b'1')
        self.assertEqual((self.rp / 'authorized').read_bytes(), b'1')

if __name__ == '__main__':
    unittest.main()
