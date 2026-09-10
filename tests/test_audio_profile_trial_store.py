from dataclasses import replace
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from backend.hdm.delivery.audio_profile_trial_state import AudioTrialRecord, AudioTrialPhase
from backend.hdm.delivery.audio_profile_trial_store import AudioTrialStore, AudioTrialTransaction, encode_record, decode_record


def record():
    return AudioTrialRecord("op", "a" * 64, "b" * 64, "0000:03:00.1", "output:hdmi", "portable", 1000)


class AudioStoreCodecTests(unittest.TestCase):
    def test_pending_none_single_and_multiple_are_read_only(self):
        from unittest.mock import Mock
        store = Mock()
        tx = AudioTrialTransaction(store, 9)
        restored = replace(record(), phase=AudioTrialPhase.RESTORED)
        for records, expected in (((), None), ((restored,), None),
                                   ((restored, replace(record(), operation="active")), replace(record(), operation="active"))):
            with patch.object(tx, "_records", return_value=records):
                self.assertEqual(tx.pending(), expected)
        with patch.object(tx, "_records", return_value=(record(), replace(record(), operation="other"))):
            with self.assertRaises(ValueError):
                tx.pending()
        store._audio_write.assert_not_called()

    def test_roundtrip_all_phases(self):
        for phase in AudioTrialPhase:
            value = replace(record(), phase=phase)
            self.assertEqual(decode_record(encode_record(value)), value)

    def test_strict_schema_and_size(self):
        raw = encode_record(record())
        for data in (b"", bytes(4097), b"\xff", b"[]", raw.replace(b'"schema":1', b'"schema":true'),
                     raw.replace(b'"revision":1', b'"revision":true'),
                     raw.replace(b'"prepared"', b'"unknown"'), b'{"schema":1,' + raw[1:],
                     raw[:-1] + b',"extra":1}', b'{"schema":NaN}'):
            with self.assertRaises(ValueError):
                decode_record(data)

    def test_transition_matrix_is_enforced_before_write(self):
        from unittest.mock import Mock
        # A reboot can interrupt a trial at any step, so every non-terminal
        # phase reaches "abandoned". Neither terminal phase leads anywhere.
        allowed = {
            "prepared": {"off_requested", "restore_requested", "restored", "recovery_required",
                         "abandoned"},
            "off_requested": {"off_observed", "restore_requested", "restored", "recovery_required",
                              "abandoned"},
            "off_observed": {"restore_requested", "restored", "recovery_required", "abandoned"},
            "restore_requested": {"restore_requested", "restored", "recovery_required", "abandoned"},
            "recovery_required": {"restore_requested", "restored", "abandoned"},
            "restored": set(), "abandoned": set()}
        for before in AudioTrialPhase:
            for after in AudioTrialPhase:
                store = Mock()
                old = replace(record(), phase=before)
                new = replace(old, revision=2, phase=after)
                store._audio_read.return_value = old
                tx = AudioTrialTransaction(store, 9)
                if after.value in allowed[before.value]:
                    self.assertEqual(tx.save(old, new), new)
                    store._audio_write.assert_called_once()
                else:
                    with self.assertRaises(ValueError):
                        tx.save(old, new)
                    store._audio_write.assert_not_called()

    def test_an_abandoned_record_is_terminal_but_stays_a_replay_tombstone(self):
        from unittest.mock import Mock
        # A record retired with its boot is finished. It must not be pending --
        # nothing can revalidate it -- and it must not refuse the next trial,
        # which was the whole reason a cross-boot record wedged the install.
        # It stays on disk so its own operation can never replay.
        abandoned = replace(record(), phase=AudioTrialPhase.ABANDONED)
        store = Mock()
        tx = AudioTrialTransaction(store, 9)
        with patch.object(tx, "_records", return_value=(abandoned,)):
            self.assertIsNone(tx.pending())
            fresh = replace(record(), operation="next")
            self.assertEqual(tx.create(fresh), fresh)
            store._audio_write.assert_called_once_with(9, fresh, initial=True)
            with self.assertRaises(ValueError):
                tx.create(replace(record(), operation="op"))
        self.assertEqual(store._audio_write.call_count, 1)


@unittest.skipUnless(sys.platform == "linux", "Linux journal fixture")
class AudioStoreLinuxTests(unittest.TestCase):
    def test_pending_real_records_and_corruption(self):
        with self.store.transaction() as tx:
            self.assertIsNone(tx.pending())
            tx.create(record())
            self.assertEqual(tx.pending(), record())
            tx.save(record(), replace(record(), revision=2, phase=AudioTrialPhase.RESTORED))
            self.assertIsNone(tx.pending())
            # Simulate inconsistent externally recovered storage. Public create
            # cannot produce two simultaneous active records.
            self.store._audio_write(tx.directory, replace(record(), operation="one"), initial=True)
            self.store._audio_write(tx.directory, replace(record(), operation="two"), initial=True)
            with self.assertRaises(ValueError):
                tx.pending()
        target = next(self.path.glob("*.json"))
        target.write_bytes(b"malformed")
        with self.store.transaction() as tx, self.assertRaises(ValueError):
            tx.pending()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)
        self.store = AudioTrialStore(owner_uid=os.getuid(), trusted_directory_fd=self.fd)

    def test_create_cas_and_restored_tombstone(self):
        original = record()
        with self.store.transaction() as tx:
            tx.create(original)
            with self.assertRaises(ValueError):
                tx.create(replace(original, operation="second"))
            restored = replace(original, revision=2, phase=AudioTrialPhase.RESTORED)
            tx.save(original, restored)
            self.assertEqual(tx.read("op"), restored)
            with self.assertRaises(ValueError):
                tx.create(original)
            tx.create(replace(original, operation="second"))
        with self.assertRaises(ValueError):
            tx.read("op")

    def test_stale_cas_and_identity_change(self):
        original = record()
        with self.store.transaction() as tx:
            tx.create(original)
            for newer in (replace(original, revision=3), replace(original, revision=2, uid=1001)):
                with self.assertRaises(ValueError):
                    tx.save(original, newer)
            tx.save(original, replace(original, revision=2, phase=AudioTrialPhase.OFF_REQUESTED))
            with self.assertRaises(ValueError):
                tx.save(original, replace(original, revision=2, phase=AudioTrialPhase.OFF_REQUESTED))

    def test_symlink_and_unsafe_file_rejected(self):
        with self.store.transaction() as tx:
            tx.create(record())
        target = next(self.path.glob("*.json"))
        target.chmod(0o666)
        with self.store.transaction() as tx, self.assertRaises(ValueError):
            tx.read("op")
        target.unlink()
        target.symlink_to(self.path / "missing")
        with self.store.transaction() as tx, self.assertRaises(OSError):
            tx.read("op")

    def test_uncertain_save_can_be_reconciled_by_read(self):
        original = record()
        changed = replace(original, revision=2, phase=AudioTrialPhase.OFF_REQUESTED)
        with self.store.transaction() as tx:
            tx.create(original)
        real_sync = os.fsync
        def fail_directory(fd):
            if os.fstat(fd).st_ino == os.fstat(self.fd).st_ino:
                raise OSError("directory sync failed")
            real_sync(fd)
        with patch("backend.hdm.delivery.audio_profile_trial_store.os.fsync", side_effect=fail_directory):
            with self.store.transaction() as tx, self.assertRaises(OSError):
                tx.save(original, changed)
        with self.store.transaction() as tx:
            self.assertEqual(tx.read("op"), changed)

    def test_record_bound_prevents_new_operation(self):
        with self.store.transaction() as tx:
            tx.create(record())
            tx.save(record(), replace(record(), revision=2, phase=AudioTrialPhase.RESTORED))
        with patch("backend.hdm.delivery.audio_profile_trial_store.MAX_RECORDS", 1):
            with self.store.transaction() as tx, self.assertRaises(ValueError):
                tx.create(replace(record(), operation="second"))

    def test_incomplete_crash_temporary_is_preserved_without_blocking_recovery(self):
        temporary = self.path / (".pending-" + "a" * 32)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(fd, b'{"incomplete":')
        os.close(fd)
        with self.store.transaction() as tx:
            tx.create(record())
            tx.save(record(), replace(record(), revision=2, phase=AudioTrialPhase.RESTORED))
            second = replace(record(), operation="second")
            tx.create(second)
            tx.save(second, replace(second, revision=2, phase=AudioTrialPhase.RESTORED))
        self.assertTrue(temporary.exists())
        temporary.chmod(0o666)
        with self.store.transaction() as tx, self.assertRaises(ValueError):
            tx.create(replace(record(), operation="third"))


if __name__ == "__main__":
    unittest.main()
