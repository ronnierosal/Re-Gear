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


@unittest.skipUnless(sys.platform == 'linux', 'Linux directory descriptor semantics')
class MaskLeaseJournalTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.root.chmod(0o700)
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, fd)
        self.fd = fd
        self.journal = m.MaskLeaseJournal(fd, owner_uid=os.geteuid())
        self.addCleanup(self.journal.close)
        self.intent = m.MaskLeaseIntent('a' * 32, 'b' * 64, ('gamescope-session.target',))
        self.identity = m.MaskIdentity('gamescope-session.target', 'a' * 32, 1, 2)

    def start(self):
        self.journal.create_intent(self.intent)

    def test_intent_and_mask_immutable_recovery_blocks_future_records(self):
        with self.journal.locked():
            self.start()
            self.assertEqual(self.journal.load_intent(), self.intent)
            self.assertTrue(self.journal.record_mask(self.intent, self.identity))
            with self.assertRaises(FileExistsError):
                self.journal.record_mask(self.intent, self.identity)
            self.assertEqual(self.journal.begin_recovery(self.intent), (self.identity,))
            with self.assertRaises(ValueError):
                self.journal.record_mask(self.intent, self.identity)
            with self.assertRaises(ValueError):
                self.journal.finish(self.intent, lambda: False)
            self.assertFalse((self.root / 'finished.json').exists())
            self.assertTrue(self.journal.finish(self.intent, lambda: True))

    def test_same_directory_separate_watchdog_lock_is_nonblocking(self):
        other = m.MaskLeaseJournal(self.fd, owner_uid=os.geteuid())
        self.addCleanup(other.close)
        with self.journal.locked():
            with self.assertRaises(BlockingIOError):
                with other.locked():
                    self.fail('overlapping owner')
        with other.locked():
            other.create_intent(self.intent)

    def test_lock_required_for_reads_and_writes(self):
        with self.assertRaises(ValueError):
            self.start()
        with self.assertRaises(ValueError):
            self.journal.load_intent()

    def test_foreign_token_or_boot_refuses(self):
        with self.journal.locked():
            self.start()
            for intent in (m.MaskLeaseIntent('c' * 32, 'b' * 64, self.intent.prior_active),
                           m.MaskLeaseIntent('a' * 32, 'c' * 64, self.intent.prior_active)):
                with self.assertRaises(ValueError):
                    self.journal.begin_recovery(intent)

    def test_corrupt_or_symlink_intent_fails_closed(self):
        with self.journal.locked():
            target = self.root / 'intent.json'
            for content in ('{"token":1,"token":2}', 'x' * 4097, '[]'):
                target.write_text(content)
                target.chmod(0o600)
                with self.assertRaises((ValueError, UnicodeError)):
                    self.journal.load_intent()
                target.unlink()
            target.symlink_to('/dev/null')
            with self.assertRaises(OSError):
                self.journal.load_intent()

    def test_finish_requires_recovery_and_exact_true(self):
        with self.journal.locked():
            self.start()
            with self.assertRaises(ValueError):
                self.journal.finish(self.intent, lambda: True)
            self.journal.begin_recovery(self.intent)
            with self.assertRaises(ValueError):
                self.journal.finish(self.intent, lambda: 1)

    def test_record_fsync_failure_leaves_fail_closed_record(self):
        with self.journal.locked():
            self.start()
            with patch.object(m.os, 'fsync', side_effect=OSError('durability')):
                with self.assertRaises(OSError):
                    self.journal.record_mask(self.intent, self.identity)
            with self.assertRaises(FileExistsError):
                self.journal.record_mask(self.intent, self.identity)

    def test_unsafe_directory_refused(self):
        self.root.chmod(0o755)
        with self.assertRaises(ValueError):
            m.MaskLeaseJournal(self.fd, owner_uid=os.geteuid())

    def test_corrupt_recovery_marker_blocks_both_publication_and_finish(self):
        with self.journal.locked():
            self.start()
            marker = self.root / 'recovering.json'
            marker.write_text('{"schema_version":true,"token":"' + self.intent.token
                              + '","boot_identity":"' + self.intent.boot_identity + '"}')
            marker.chmod(0o600)
            with self.assertRaises(ValueError):
                self.journal.begin_recovery(self.intent)
            with self.assertRaises(ValueError):
                self.journal.record_mask(self.intent, self.identity)
            with self.assertRaises(ValueError):
                self.journal.finish(self.intent, lambda: True)

    def test_finish_rechecks_evidence_after_verification(self):
        with self.journal.locked():
            self.start()
            self.journal.begin_recovery(self.intent)
            def changed():
                (self.root / 'recovering.json').unlink()
                return True
            with self.assertRaises(ValueError):
                self.journal.finish(self.intent, changed)
            self.assertFalse((self.root / 'finished.json').exists())

    def test_completion_is_idempotent_but_requires_fresh_verification(self):
        with self.journal.locked():
            self.start()
            self.assertTrue(self.journal.ownership_active(self.intent))
            self.assertFalse(self.journal.is_finished(self.intent))
            self.journal.begin_recovery(self.intent)
            self.assertFalse(self.journal.ownership_active(self.intent))
            self.journal.finish(self.intent, lambda: True)
            previous = (self.root / 'finished.json').stat().st_ino
            self.assertTrue(self.journal.is_finished(self.intent))
            self.assertFalse(self.journal.ownership_active(self.intent))
            with self.assertRaises(ValueError):
                self.journal.finish(self.intent, lambda: False)
            self.assertTrue(self.journal.finish(self.intent, lambda: True))
            self.assertEqual((self.root / 'finished.json').stat().st_ino, previous)

    def test_corrupt_completion_refuses_read_guard_and_finish(self):
        with self.journal.locked():
            self.start()
            self.journal.begin_recovery(self.intent)
            marker = self.root / 'finished.json'
            marker.write_text('{}')
            marker.chmod(0o600)
            for read in (lambda: self.journal.is_finished(self.intent),
                         lambda: self.journal.ownership_active(self.intent),
                         lambda: self.journal.finish(self.intent, lambda: True)):
                with self.assertRaises(ValueError):
                    read()

    def test_completed_marker_without_recovery_is_corrupt(self):
        with self.journal.locked():
            self.start()
            self.journal._write('finished.json', self.journal._marker(self.intent))
            with self.assertRaises(ValueError):
                self.journal.is_finished(self.intent)

    def test_ownership_guard_validates_mask_records(self):
        with self.journal.locked():
            self.start()
            record = self.root / (self.identity.unit + '.mask.json')
            record.write_text('{}')
            record.chmod(0o600)
            with self.assertRaises(ValueError):
                self.journal.ownership_active(self.intent)

    def test_constructor_fstat_failure_closes_duplicate(self):
        duplicate = os.dup(self.fd)
        with patch.object(m.os, 'dup', return_value=duplicate), \
                patch.object(m.os, 'fstat', side_effect=OSError('failed')):
            with self.assertRaises(OSError):
                m.MaskLeaseJournal(self.fd, owner_uid=os.geteuid())
        with self.assertRaises(OSError):
            os.fstat(duplicate)

    def test_recovery_lock_serializes_only_recovery_and_releases_on_error(self):
        other = m.MaskLeaseJournal(self.fd, owner_uid=os.geteuid())
        self.addCleanup(other.close)
        with self.assertRaisesRegex(ValueError, 'runner failure'):
            with self.journal.recovery_locked():
                with self.assertRaises(BlockingIOError):
                    with other.recovery_locked():
                        self.fail('overlapping recovery')
                with other.locked():
                    other.create_intent(self.intent)
                with self.assertRaises(ValueError):
                    self.journal.load_intent()
                raise ValueError('runner failure')
        with other.recovery_locked():
            with other.locked():
                self.assertEqual(other.load_intent(), self.intent)

    def test_recovery_lock_rejects_symlink(self):
        (self.root / 'recovery-executor.lock').symlink_to('/dev/null')
        with self.assertRaises(OSError):
            with self.journal.recovery_locked():
                self.fail('unsafe lock')


if __name__ == '__main__':
    unittest.main()
