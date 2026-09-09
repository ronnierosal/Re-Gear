from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from backend.hdm.delivery.device_filter_journal import (
    FilterJournal, JournalRecord, decode_record, encode_record, _key, _acquire_lock,
)
from backend.hdm.delivery.device_filter_lifecycle import FilterLifecycle, LaunchBinding, OwnedFilter, Phase


def binding():
    return LaunchBinding("a" * 64, "journal-test", "gamescope-session.service", "b" * 32,
                         1000, 123, 456, 1, 789, "c" * 64, 100.0)


class JournalCodecTests(unittest.TestCase):
    def test_stalled_writer_has_bounded_lock_wait(self):
        locking = Mock(LOCK_EX=2, LOCK_NB=4)
        locking.flock.side_effect = BlockingIOError("busy")
        wait = Mock()
        with self.assertRaises(TimeoutError):
            _acquire_lock(7, locking, wait=wait)
        self.assertEqual(locking.flock.call_count, 50)
        self.assertEqual(wait.call_count, 49)
        locking.flock.assert_called_with(7, 6)

    def test_contention_can_resolve_without_masking_other_errors(self):
        locking = Mock(LOCK_EX=2, LOCK_NB=4)
        locking.flock.side_effect = [BlockingIOError("busy"), None]
        wait = Mock()
        _acquire_lock(7, locking, wait=wait)
        wait.assert_called_once_with(0.02)
        locking.flock.side_effect = OSError("unavailable")
        with self.assertRaises(OSError):
            _acquire_lock(7, locking, wait=wait)

    def test_roundtrip_and_delivery_flag_never_persisted(self):
        record = JournalRecord(1, FilterLifecycle(binding()), True)
        restored = decode_record(encode_record(record))
        self.assertEqual(restored.lifecycle, record.lifecycle)
        self.assertFalse(restored.delivery_granted)

    def test_duplicate_nonfinite_and_unknown_fields_rejected(self):
        raw = encode_record(JournalRecord(1, FilterLifecycle(binding())))
        for invalid in (raw.replace(b'"schema":1', b'"schema":1,"schema":1'),
                        raw.replace(b'100.0', b'NaN'), raw.replace(b'100.0', b'1e999'),
                        raw[:-1] + b',"extra":1}', b"[]", b"x" * 8193):
            with self.assertRaises(ValueError):
                decode_record(invalid)

    def test_unknown_nested_fields_and_invalid_active_state_rejected(self):
        value = json.loads(encode_record(JournalRecord(1, FilterLifecycle(binding()))))
        value["binding"]["extra"] = True
        with self.assertRaises(ValueError):
            decode_record(json.dumps(value).encode())
        del value["binding"]["extra"]
        value["phase"] = "granted"
        with self.assertRaises(ValueError):
            decode_record(json.dumps(value).encode())

    def test_fixture_owner_cannot_relax_paths_without_explicit_fd(self):
        with self.assertRaises(ValueError):
            FilterJournal(owner_uid=1000)


@unittest.skipUnless(sys.platform == "linux", "requires Linux dirfd/flock semantics")
class JournalFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)
        self.journal = self.instance()
        self.binding = binding()
        self.owner = OwnedFilter(42, "d" * 64, True, True, 43, 1234)

    def instance(self):
        return FilterJournal(owner_uid=os.geteuid(), trusted_directory_fd=self.fd)

    def args(self):
        return self.binding.operation, self.binding.unit

    def attach(self):
        self.journal.create(self.binding)
        self.journal.prepare_pin(*self.args(), 1,
            owned=replace(self.owner, survives_owner_exit=False), observed=self.binding, now=1)
        return self.journal.attach(*self.args(), 2, owned=self.owner, observed=self.binding, now=1)

    def test_transaction_spans_durable_writes_and_expires(self):
        with self.journal.transaction() as transaction:
            transaction.create(self.binding)
            transaction.change(*self.args(), 1, "prepare_pin",
                owned=replace(self.owner, survives_owner_exit=False), observed=self.binding, now=1)
            record = transaction.change(*self.args(), 2, "attach",
                owned=self.owner, observed=self.binding, now=1)
            self.assertEqual(transaction.read(*self.args()).revision, record.revision)
            errors = []
            def cross_thread():
                try:
                    transaction.read(*self.args())
                except ValueError:
                    errors.append("rejected")
            thread = threading.Thread(target=cross_thread)
            thread.start()
            thread.join(timeout=2)
            self.assertEqual(errors, ["rejected"])
        with self.assertRaises(ValueError):
            transaction.read(*self.args())
        self.assertEqual(self.instance().read(*self.args()).revision, 3)

    def test_transaction_excludes_other_controller_and_releases_on_error(self):
        with self.assertRaisesRegex(RuntimeError, "controller interrupted"):
            with self.journal.transaction() as transaction:
                transaction.create(self.binding)
                with self.assertRaises(TimeoutError):
                    self.instance().cancel(*self.args(), 1)
                raise RuntimeError("controller interrupted")
        # The committed intent survives the exception; lock is released.
        self.assertEqual(self.instance().read(*self.args()).revision, 1)
        self.instance().cancel(*self.args(), 1)

    def test_exclusive_creation_and_cas_across_instances(self):
        self.journal.create(self.binding)
        with self.assertRaises(FileExistsError):
            self.instance().create(self.binding)
        self.instance().cancel(*self.args(), 1)
        with self.assertRaises(ValueError):
            self.journal.cancel(*self.args(), 1)

    def test_grant_commit_then_read_cannot_redeliver(self):
        attached = self.attach()
        granted = self.journal.grant(*self.args(), attached.revision,
            observed=self.binding, now=2, no_game=True,
            inherited_scan_complete=True, inherited_descriptors_free=True)
        self.assertTrue(granted.delivery_granted)
        for _ in range(2):
            loaded = self.instance().read(*self.args())
            self.assertEqual(loaded.lifecycle.phase, Phase.GRANTED)
            self.assertFalse(loaded.delivery_granted)
            self.assertEqual(loaded.revision, granted.revision)
        with self.assertRaises(ValueError):
            self.journal.grant(*self.args(), granted.revision, observed=self.binding,
                now=3, no_game=True, inherited_scan_complete=True, inherited_descriptors_free=True)
        recovered = self.instance().recover(*self.args(), granted.revision)
        self.assertEqual(recovered.lifecycle.phase, Phase.RECOVERY_REQUIRED)
        self.assertEqual(recovered.revision, granted.revision + 1)
        self.assertFalse(recovered.delivery_granted)

    def test_crash_recover_requires_exact_revision_and_preserves_owner(self):
        attached = self.attach()
        recovered = self.instance().recover(*self.args(), attached.revision)
        self.assertEqual(recovered.lifecycle.phase, Phase.CANCELLED)
        self.assertEqual(recovered.lifecycle.owned, self.owner)
        with self.assertRaises(ValueError):
            self.journal.recover(*self.args(), recovered.revision)

    def test_pending_identity_survives_reload_without_grant(self):
        self.journal.create(self.binding)
        ephemeral = replace(self.owner, survives_owner_exit=False)
        pending = self.journal.prepare_pin(*self.args(), 1,
            owned=ephemeral, observed=self.binding, now=1)
        loaded = self.instance().read(*self.args())
        self.assertEqual(loaded.lifecycle.phase, Phase.PIN_PENDING)
        self.assertEqual(loaded.lifecycle.owned, ephemeral)
        self.assertFalse(loaded.delivery_granted)
        with self.assertRaises(ValueError):
            self.instance().grant(*self.args(), pending.revision, observed=self.binding,
                now=2, no_game=True, inherited_scan_complete=True, inherited_descriptors_free=True)
        recovered = self.instance().recover(*self.args(), pending.revision)
        self.assertEqual(recovered.lifecycle.phase, Phase.CANCELLED)
        self.assertEqual(recovered.lifecycle.owned, ephemeral)
        self.assertFalse(recovered.delivery_granted)

    def test_partial_write_failure_preserves_original(self):
        self.journal.create(self.binding)
        write = os.write
        count = 0
        def failing(fd, raw):
            nonlocal count
            count += 1
            if count == 1:
                return write(fd, raw[:10])
            raise OSError("injected write failure")
        with patch("backend.hdm.delivery.device_filter_journal.os.write", side_effect=failing):
            with self.assertRaises(OSError):
                self.journal.cancel(*self.args(), 1)
        self.assertEqual(self.journal.read(*self.args()).revision, 1)
        self.assertEqual(list(self.root.glob(".pending-*")), [])

    def test_changed_binding_cancels_without_rewriting_identity(self):
        attached = self.attach()
        result = self.journal.grant(*self.args(), attached.revision,
            observed=replace(self.binding, invocation="e" * 32), now=2,
            no_game=True, inherited_scan_complete=True, inherited_descriptors_free=True)
        self.assertEqual(result.lifecycle.phase, Phase.CANCELLED)
        self.assertEqual(result.lifecycle.binding, self.binding)
        self.assertFalse(result.delivery_granted)

    def test_symlink_fifo_and_hardlink_records_rejected(self):
        target = self.root / _key(*self.args())
        outside = self.root / "other"
        outside.write_bytes(b"irrelevant")
        for make in (lambda: target.symlink_to(outside), lambda: os.mkfifo(target, 0o600),
                     lambda: os.link(outside, target)):
            make()
            try:
                with self.assertRaises((OSError, ValueError)):
                    self.journal.read(*self.args())
            finally:
                target.unlink()

    def test_lock_symlink_and_writable_directory_rejected(self):
        (self.root / "journal.lock").symlink_to(self.root / "absent")
        with self.assertRaises(OSError):
            self.journal.create(self.binding)
        (self.root / "journal.lock").unlink()
        self.root.chmod(0o777)
        with self.assertRaises(ValueError):
            self.journal.create(self.binding)
        self.root.chmod(0o700)

    def test_competing_instances_have_one_cas_winner(self):
        self.journal.create(self.binding)
        barrier = threading.Barrier(2)
        results = []
        def change():
            barrier.wait(timeout=5)
            try:
                self.instance().cancel(*self.args(), 1)
                results.append("won")
            except ValueError:
                results.append("stale")
        threads = [threading.Thread(target=change) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.assertCountEqual(results, ["won", "stale"])
