"""Real Linux directory-descriptor fixtures; never touches system unit paths."""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from regear.delivery import runtime_mask_lease as m


@unittest.skipUnless(sys.platform == 'linux', 'Linux directory descriptor semantics')
class RuntimeMaskLeaseTests(unittest.TestCase):
    unit = 'gamescope-session.target'
    token = 'a' * 32

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.units = self.root / 'units'
        self.private = self.root / 'private'
        self.units.mkdir(mode=0o700)
        self.private.mkdir(mode=0o700)
        self.ufd = os.open(self.units, os.O_RDONLY | os.O_DIRECTORY)
        self.lfd = os.open(self.private, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.ufd)
        self.addCleanup(os.close, self.lfd)
        self.lease = m.RuntimeMaskLease(self.ufd, self.lfd, owner_uid=os.geteuid())
        self.addCleanup(self.lease.close)

    def create(self):
        return self.lease.create(self.unit, self.token, lambda identity: True)

    def anchor(self):
        return self.private / (self.token + '-' + self.unit)

    def retired(self):
        return self.private / ('retired-' + self.token + '-' + self.unit)

    def test_publish_after_journal_and_restore_idempotently(self):
        def record(identity):
            self.assertFalse(os.path.lexists(self.units / self.unit))
            self.assertEqual(self.anchor().lstat().st_ino, identity.inode)
            self.assertEqual(os.readlink(self.anchor()), '/dev/null')
            return True
        identity = self.lease.create(self.unit, self.token, record)
        self.assertEqual((self.units / self.unit).lstat().st_ino, identity.inode)
        self.assertTrue(self.lease.restore(identity))
        self.assertFalse(os.path.lexists(self.units / self.unit))
        self.assertTrue(self.anchor().is_symlink())
        self.assertTrue(self.lease.restore(identity))

    def test_prior_mask_or_configuration_is_not_clobbered(self):
        for existing_mask in (True, False):
            with self.subTest(existing_mask=existing_mask):
                target = self.units / self.unit
                if existing_mask:
                    target.symlink_to('/dev/null')
                else:
                    target.write_text('foreign configuration')
                previous = target.lstat().st_ino
                with self.assertRaises(FileExistsError):
                    self.create()
                self.assertEqual(target.lstat().st_ino, previous)
                if not existing_mask:
                    self.assertEqual(target.read_text(), 'foreign configuration')
                target.unlink()
                self.anchor().unlink()

    def test_journal_requires_exact_true(self):
        for answer in (False, None, 1, 'yes'):
            with self.subTest(answer=answer):
                with self.assertRaises(ValueError):
                    self.lease.create(self.unit, self.token, lambda identity: answer)
                self.assertFalse(os.path.lexists(self.units / self.unit))
                self.assertTrue(self.anchor().is_symlink())
                self.anchor().unlink()

    def test_journal_exception_does_not_publish(self):
        def fail(identity):
            raise OSError('journal failed')
        with self.assertRaises(OSError):
            self.lease.create(self.unit, self.token, fail)
        self.assertFalse(os.path.lexists(self.units / self.unit))

    def test_foreign_replacement_is_returned_unchanged(self):
        identity = self.create()
        target = self.units / self.unit
        target.unlink()
        target.write_text('replacement')
        inode = target.lstat().st_ino
        self.assertFalse(self.lease.restore(identity))
        self.assertEqual(target.lstat().st_ino, inode)
        self.assertEqual(target.read_text(), 'replacement')
        self.assertFalse(os.path.lexists(self.retired()))

    def test_owned_interrupted_quarantine_is_finished(self):
        identity = self.create()
        os.rename(self.units / self.unit, self.retired())
        self.assertTrue(self.lease.restore(identity))
        self.assertFalse(os.path.lexists(self.retired()))
        self.assertTrue(self.anchor().is_symlink())

    def test_foreign_interrupted_quarantine_returns_to_empty_slot(self):
        identity = self.create()
        (self.units / self.unit).unlink()
        self.retired().write_text('displaced foreign entry')
        self.assertFalse(self.lease.restore(identity))
        self.assertEqual((self.units / self.unit).read_text(), 'displaced foreign entry')

    def test_foreign_quarantine_cannot_clobber_new_live_entry(self):
        identity = self.create()
        (self.units / self.unit).unlink()
        (self.units / self.unit).write_text('new live entry')
        self.retired().write_text('older displaced entry')
        self.assertFalse(self.lease.restore(identity))
        self.assertEqual((self.units / self.unit).read_text(), 'new live entry')
        self.assertEqual(self.retired().read_text(), 'older displaced entry')

    def test_invalid_names_refused_without_entries(self):
        for unit, token in (('../evil', self.token), ('unknown.service', self.token),
                            (self.unit, '../evil'), (self.unit, 'A' * 32),
                            (self.unit, 'a' * 31), (None, self.token)):
            with self.subTest(unit=unit, token=token):
                with self.assertRaises(ValueError):
                    self.lease.create(unit, token, lambda identity: True)
        self.assertEqual(list(self.private.iterdir()), [])
        self.assertEqual(list(self.units.iterdir()), [])

    def test_unsafe_directory_or_wrong_owner_refused(self):
        with self.assertRaises(ValueError):
            m.RuntimeMaskLease(self.ufd, self.lfd, owner_uid=os.geteuid() + 1)
        with self.assertRaises(ValueError):
            m.RuntimeMaskLease(self.ufd, self.ufd, owner_uid=os.geteuid())
        os.chmod(self.private, 0o777)
        with self.assertRaises(ValueError):
            m.RuntimeMaskLease(self.ufd, self.lfd, owner_uid=os.geteuid())

    def test_missing_anchor_never_removes_live_configuration(self):
        identity = self.create()
        self.anchor().unlink()
        self.assertFalse(self.lease.restore(identity))
        self.assertTrue((self.units / self.unit).is_symlink())


if __name__ == '__main__':
    unittest.main()
