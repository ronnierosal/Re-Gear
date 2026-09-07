"""Linux fd-relative metadata reader fixtures; no live process authorization."""
import os
import sys
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from hdm.delivery.device_filter_peer import WaitingPeerIdentity
from hdm.delivery.inherited_resource_scan import scan_inherited_resources


@unittest.skipUnless(sys.platform == 'linux', 'Linux directory-FD and symlink fixtures')
class NativeInheritedReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for part in ('fd', 'fdinfo', 'map_files'):
            (self.root / part).mkdir()
        self.target = self.root / 'ordinary-file'
        self.target.write_bytes(b'not read by collector')
        for part in ('fd/3', 'map_files/1000-2000'):
            (self.root / part).symlink_to(self.target)
        self.proc_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.proc_fd)
        identity = WaitingPeerIdentity(123, 1000, 77, 'a'*32,
            'gamescope-session.service', '/fixture', 1, 2)
        self.peer = SimpleNamespace(proc_fd=self.proc_fd, revalidate=lambda: identity)
        self.write_info(self.target.stat().st_ino)

    def write_info(self, inode):
        (self.root / 'fdinfo/3').write_text(f'pos:\t0\nflags:\t02000000\nmnt_id:\t12\nino:\t{inode}\n')

    def scan(self):
        return scan_inherited_resources(self.peer, ((1,3),), deadline=20, clock=lambda:10)

    def test_real_relative_reader_never_opens_target(self):
        real_open = os.open
        opened = []
        def tracked(path, flags, **kwargs):
            opened.append(path)
            return real_open(path, flags, **kwargs)
        with patch('hdm.delivery.inherited_resource_scan.os.open', side_effect=tracked):
            result = self.scan()
        self.assertTrue(result.complete)
        self.assertEqual(set(opened), {'fd', 'fdinfo/3', 'map_files'})

    def test_missing_mapping_target_is_incomplete(self):
        (self.root / 'map_files/1000-2000').unlink()
        (self.root / 'map_files/1000-2000').symlink_to(self.root/'missing')
        self.assertFalse(self.scan().complete)

    def test_device_alias_is_detected_by_stat(self):
        target = Path('/dev/null')
        if not target.exists(): self.skipTest('null control absent')
        (self.root/'fd/3').unlink()
        (self.root/'fd/3').symlink_to(target)
        self.write_info(target.stat().st_ino)
        result = self.scan()
        self.assertTrue(result.complete)
        self.assertTrue(result.target_character_seen)


if __name__ == '__main__': unittest.main()
