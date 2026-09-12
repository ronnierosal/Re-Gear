import os
from pathlib import Path
import sys
import unittest
import subprocess
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from regear.delivery import held_session_helper as h


class UserBoundaryTests(unittest.TestCase):
    def test_root_cannot_prepare_or_mutate(self):
        with patch.object(h.os, 'geteuid', return_value=0, create=True), patch.object(h, '_root') as root:
            for action in ('prepare', 'hold', 'restore', 'status'):
                self.assertEqual(h.dispatch(action, 'a' * 32)['code'], 'held_helper.unavailable')
            root.assert_not_called()


@unittest.skipUnless(sys.platform == 'linux', 'Linux directory descriptor fixtures')
class HelperFixtures(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.uid = os.geteuid() or 1000
        for relative in ('1000' if self.uid == 1000 else str(self.uid),
                         str(self.uid) + '/systemd', str(self.uid) + '/systemd/user'):
            path = self.root / relative
            path.mkdir(mode=0o700)
            if os.geteuid() == 0:
                os.chown(path, self.uid, -1)
        self.boot = self.root / 'boot'
        self.boot.write_text('12345678-1234-1234-1234-123456789abc\n')
        self.states = {unit: 'active' for unit in h.HELD_UNITS}
        fixture = self
        class Commands:
            def run(self, operation, unit=None):
                if operation == 'load':
                    return 'masked' if (fixture.root / str(fixture.uid) / 'systemd/user' / unit).is_symlink() else 'loaded'
                if operation == 'state':
                    return fixture.states[unit]
                if operation in ('start', 'stop'):
                    fixture.states[unit] = 'active' if operation == 'start' else 'inactive'
                return True
        self.commands = Commands()

    def call(self, action, pins=None):
        # Root CI fixtures simulate the user boundary; created directories/files
        # are chowned through wrapper operations, not a system user mutation.
        real_mkdir, real_open, real_symlink = os.mkdir, os.open, os.symlink
        def opened(name, flags, mode=0o777, *, dir_fd=None):
            fd = real_open(name, flags, mode, dir_fd=dir_fd)
            if flags & os.O_CREAT and os.fstat(fd).st_uid == 0:
                os.fchown(fd, self.uid, -1)
            return fd
        actual_uid = os.geteuid()
        def symlink_owned(source, target, *, dir_fd=None):
            real_symlink(source, target, dir_fd=dir_fd)
            if actual_uid == 0:
                os.chown(target, self.uid, -1, dir_fd=dir_fd, follow_symlinks=False)
        def mkdir_owned(name, mode=0o777, *, dir_fd=None):
            real_mkdir(name, mode, dir_fd=dir_fd)
            if actual_uid == 0:
                os.chown(name, self.uid, -1, dir_fd=dir_fd)
        with patch.object(h, '_root', side_effect=lambda _: real_open(self.root, os.O_RDONLY | os.O_DIRECTORY)), \
                patch.object(h.os, 'geteuid', return_value=self.uid), \
                patch.object(h.os, 'mkdir', side_effect=mkdir_owned), \
                patch.object(h.os, 'symlink', side_effect=symlink_owned), \
                patch.object(h.os, 'open', side_effect=opened), \
                patch.object(h, '_snapshot'):
            return h.dispatch(action, ('0' if action == 'audit' else 'a') * 32, pins, uid=self.uid,
                              runtime_root=self.root, boot_path=self.boot, commands=self.commands)

    def test_prepare_pins_and_changed_pins_refuse(self):
        prepared = self.call('prepare')
        self.assertEqual(prepared['code'], 'held_helper.prepared')
        pins = prepared['pins']
        self.assertEqual(self.call('status', pins)['code'], 'held_helper.status')
        self.assertEqual(self.call('hold', {**pins, 'units_inode': 1})['code'], 'held_helper.identity_changed')

    def test_prepare_is_exclusive(self):
        self.assertEqual(self.call('prepare')['code'], 'held_helper.prepared')
        self.assertEqual(self.call('prepare')['code'], 'held_helper.unavailable')

    def test_boot_change_refuses_before_hold(self):
        pins = self.call('prepare')['pins']
        self.boot.write_text('22345678-1234-1234-1234-123456789abc\n')
        self.assertEqual(self.call('hold', pins)['code'], 'held_helper.identity_changed')

    def test_hold_restore_and_repeat_restore(self):
        pins = self.call('prepare')['pins']
        self.assertEqual(self.call('hold', pins)['code'], 'held_helper.held')
        self.assertTrue(self.call('status', pins)['held'])
        restored = self.call('restore', pins)
        self.assertTrue(restored['restored'])
        self.assertTrue(all(value == 'active' for value in self.states.values()))
        self.assertEqual(self.call('restore', pins)['code'], 'held_recovery.already_restored')
        self.assertFalse(self.call('status', pins)['ownership_active'])

    def test_hold_failure_attempts_restore(self):
        pins = self.call('prepare')['pins']
        original = self.commands.run
        def failing(operation, unit=None):
            if operation == 'stop':
                return None
            return original(operation, unit)
        self.commands.run = failing
        result = self.call('hold', pins)
        self.assertEqual(result['code'], 'held_helper.hold_failed')
        self.assertTrue(result['restored'])

    def test_snapshot_regular_sources_are_private_and_exclusive(self):
        lease = self.root / 'snapshot'
        lease.mkdir(mode=0o700)
        fd = os.open(lease, os.O_RDONLY | os.O_DIRECTORY)
        try:
            h._snapshot(fd)
            copied = lease / 'code/regear/delivery/held_session_helper.py'
            self.assertTrue(copied.is_file())
            self.assertEqual(copied.stat().st_mode & 0o777, 0o400)
            self.assertEqual((lease / 'code').stat().st_mode & 0o777, 0o700)
            check = subprocess.run([sys.executable, str(copied), '--help'],
                                   capture_output=True, timeout=10, check=False)
            self.assertEqual(check.returncode, 0, check.stderr.decode())
            with self.assertRaises(FileExistsError):
                h._snapshot(fd)
        finally:
            os.close(fd)

    def test_prepare_creates_missing_override_directories(self):
        (self.root / str(self.uid) / 'systemd/user').rmdir()
        (self.root / str(self.uid) / 'systemd').rmdir()
        self.assertEqual(self.call('prepare')['code'], 'held_helper.prepared')
        self.assertTrue((self.root / str(self.uid) / 'systemd/user').is_dir())

    def test_existing_unit_configuration_is_not_overwritten(self):
        pins = self.call('prepare')['pins']
        target = self.root / str(self.uid) / 'systemd/user' / h.HELD_UNITS[0]
        target.write_text('foreign configuration')
        result = self.call('hold', pins)
        self.assertEqual(result['code'], 'held_helper.hold_failed')
        self.assertEqual(target.read_text(), 'foreign configuration')
        self.assertTrue(all(value == 'active' for value in self.states.values()))

    def test_audit_no_history_does_not_create_directories(self):
        self.assertTrue(self.call('audit')['settled'])
        self.assertFalse((self.root / str(self.uid) / 'regear-held').exists())

    def test_audit_unfinished_then_finished(self):
        pins = self.call('prepare')['pins']
        self.assertFalse(self.call('audit')['settled'])
        self.assertEqual(self.call('hold', pins)['code'], 'held_helper.held')
        self.assertFalse(self.call('audit')['settled'])
        self.assertTrue(self.call('restore', pins)['restored'])
        self.assertTrue(self.call('audit')['settled'])

    def test_audit_missing_lock_does_not_recreate_it(self):
        self.call('prepare')
        lock = self.root / str(self.uid) / 'regear-held' / ('a' * 32) / 'mask-journal.lock'
        lock.unlink()
        self.assertEqual(self.call('audit')['code'], 'held_helper.unavailable')
        self.assertFalse(lock.exists())

    def test_audit_rejects_quarantine_and_unknown_entries(self):
        pins = self.call('prepare')['pins']
        self.call('hold', pins)
        self.call('restore', pins)
        lease = self.root / str(self.uid) / 'regear-held' / ('a' * 32)
        for name in ('retired-' + 'a' * 32 + '-gamescope-session.target', 'unexpected'):
            path = lease / name
            path.write_text('unresolved')
            self.assertFalse(self.call('audit')['settled'])
            path.unlink()

    def test_audit_rejects_unknown_token_entry_and_old_boot(self):
        pins = self.call('prepare')['pins']
        self.call('restore', pins)
        directory = self.root / str(self.uid) / 'regear-held'
        (directory / 'unknown').mkdir()
        self.assertFalse(self.call('audit')['settled'])
        (directory / 'unknown').rmdir()
        self.boot.write_text('22345678-1234-1234-1234-123456789abc\n')
        self.assertFalse(self.call('audit')['settled'])


if __name__ == '__main__':
    unittest.main()
