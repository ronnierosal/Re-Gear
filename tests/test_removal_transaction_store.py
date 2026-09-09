from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.delivery.removal_transaction_store import (  # noqa: E402
    MAX_BYTES,
    RECORD_FILENAME,
    FileRemovalTransactionStore,
    decode,
    encode,
)
from hdm.domain.removal_transaction import (  # noqa: E402
    FunctionProgress,
    RemovalTransaction,
    RemovalTransactionState,
    record_progress,
)
from hdm.domain.removal_transaction import plan as plan_transaction  # noqa: E402


GPU = "0000:08:00.0"
AUDIO = "0000:08:00.1"


def planned() -> RemovalTransaction:
    return plan_transaction(
        owner_id="regear",
        device_set="egpu-stable-id",
        addresses=(AUDIO, GPU),
        now_ns=1_700_000_000_000_000_000,
    )


class EncodingTests(unittest.TestCase):
    def test_a_record_survives_a_round_trip_unchanged(self) -> None:
        record = record_progress(planned(), AUDIO, FunctionProgress.REMOVED)
        self.assertEqual(decode(encode(record)), record)

    def test_encoding_is_deterministic_and_carries_no_host_data(self) -> None:
        record = planned()
        self.assertEqual(encode(record), encode(record))
        value = json.loads(encode(record))
        self.assertEqual(
            set(value),
            {
                "schema_version",
                "owner_id",
                "device_set",
                "state",
                "functions",
                "started_at_ns",
            },
        )

    def test_a_record_this_module_did_not_write_is_refused(self) -> None:
        """Every malformed form raises; none of them decodes to a usable record.

        A record that decodes into something plausible is worse than one that
        raises: it would describe a removal that never happened over a device
        that may be half detached.
        """
        good = json.loads(encode(planned()))
        broken = [
            b"",
            b"{",
            b"[]",
            b'"text"',
            b"\xff\xfe not utf-8",
            b"x" * (MAX_BYTES + 1),
            json.dumps({**good, "schema_version": 2}).encode(),
            json.dumps({**good, "schema_version": "1"}).encode(),
            json.dumps({**good, "state": "half"}).encode(),
            json.dumps({**good, "started_at_ns": "soon"}).encode(),
            json.dumps({**good, "owner_id": 7}).encode(),
            json.dumps({**good, "functions": []}).encode(),
            json.dumps({**good, "functions": [{"address": GPU}]}).encode(),
            json.dumps(
                {**good, "functions": [{"address": GPU, "progress": "maybe"}]}
            ).encode(),
            json.dumps(
                {**good, "functions": [{"address": "not-an-address", "progress": "pending"}]}
            ).encode(),
            json.dumps({key: good[key] for key in good if key != "state"}).encode(),
            json.dumps({**good, "extra": 1}).encode(),
        ]
        for data in broken:
            with self.subTest(data=data[:40]):
                with self.assertRaises(ValueError):
                    decode(data)


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name).resolve()
        self.store = FileRemovalTransactionStore(self.root)

    def test_nothing_stored_reads_as_no_transaction(self) -> None:
        self.assertIsNone(self.store.load())

    def test_a_saved_record_reads_back_and_a_later_save_replaces_it(self) -> None:
        self.store.save(planned())
        self.assertEqual(self.store.load(), planned())

        advanced = record_progress(planned(), AUDIO, FunctionProgress.REMOVED)
        self.store.save(advanced)
        self.assertEqual(self.store.load(), advanced)
        self.assertIs(self.store.load().state, RemovalTransactionState.IN_PROGRESS)

    def test_an_unreadable_record_raises_rather_than_reading_as_absent(self) -> None:
        """The difference this protects is the whole point of the record.

        None means nothing was ever planned. A corrupt file must not say that:
        it may be the only trace of a device that is half detached.
        """
        (self.root / RECORD_FILENAME).write_bytes(b"{ truncated")
        with self.assertRaises(ValueError):
            self.store.load()

    def test_clearing_removes_the_record_and_is_safe_when_there_is_none(self) -> None:
        self.store.save(planned())
        self.store.clear()
        self.assertIsNone(self.store.load())
        self.store.clear()
        self.assertIsNone(self.store.load())

    def test_only_a_transaction_may_be_stored(self) -> None:
        for value in ({"state": "planned"}, None, "planned"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.store.save(value)

    def test_a_relative_root_is_refused_before_anything_is_written(self) -> None:
        with self.assertRaises(ValueError):
            FileRemovalTransactionStore(Path("relative/path"))

    def test_a_root_that_is_not_a_real_directory_is_refused(self) -> None:
        store = FileRemovalTransactionStore(self.root / "absent")
        with self.assertRaises(ValueError):
            store.save(planned())

    def test_a_failed_save_leaves_no_temporary_file_and_no_stale_record(self) -> None:
        self.store.save(planned())
        with patch.object(os, "replace", side_effect=OSError("no rename")):
            with self.assertRaises(OSError):
                self.store.save(
                    record_progress(planned(), AUDIO, FunctionProgress.REMOVED)
                )
        self.assertEqual(
            sorted(path.name for path in self.root.iterdir()), [RECORD_FILENAME]
        )
        # The earlier record is intact: a failed save never destroys the record
        # describing a removal that may already be under way.
        self.assertEqual(self.store.load(), planned())

    def test_the_record_is_durable_before_save_returns(self) -> None:
        """The crash this survives happens between two writes to the PCI bus.

        Ordering, not merely eventual persistence: the bytes and the directory
        entry are both fsynced before a caller is allowed to issue the detach
        the record describes.
        """
        synced: list[str] = []
        real_fsync = os.fsync

        def record_fsync(descriptor):
            synced.append("fsync")
            return real_fsync(descriptor)

        with patch.object(os, "fsync", record_fsync):
            self.store.save(planned())
        # One for the file. On POSIX the directory is fsynced too, so the
        # rename itself survives; Windows has no directory descriptor to sync.
        self.assertGreaterEqual(len(synced), 2 if os.name == "posix" else 1)

    @unittest.skipUnless(os.name == "posix", "POSIX file modes")
    def test_the_record_is_not_world_readable(self) -> None:
        self.store.save(planned())
        mode = (self.root / RECORD_FILENAME).stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
