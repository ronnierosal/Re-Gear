"""The sleep continuation record: pure decision and durable store."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from regear.delivery.sleep_continuation_store import PendingSleepStore
from regear.domain.sleep_continuation import (
    MAX_AGE_SECONDS,
    PendingSleep,
    decide_sleep_continuation,
)

BOOT = "b" * 64


def decide(record, boot=BOOT, mono=1000.0, boot_s=5000.0):
    return decide_sleep_continuation(
        record, boot_hash=boot, now_monotonic=mono, now_boottime=boot_s)


class DecideSleepContinuationTests(unittest.TestCase):
    def test_nothing_recorded(self):
        decision = decide(None)
        self.assertFalse(decision.should_sleep)
        self.assertEqual(decision.code, "sleep_continuation.nothing_recorded")

    def test_a_fresh_same_boot_record_continues(self):
        decision = decide(PendingSleep(BOOT, 990.0, 4990.0))
        self.assertTrue(decision.should_sleep)
        self.assertEqual(decision.code, "sleep_continuation.pending")

    def test_a_record_from_another_boot_is_refused(self):
        self.assertEqual(decide(PendingSleep("a" * 64, 990.0, 4990.0)).code,
                         "sleep_continuation.different_boot")
        # A boot that cannot be identified cannot be shown to be this one.
        self.assertEqual(decide(PendingSleep(BOOT, 990.0, 4990.0), boot="").code,
                         "sleep_continuation.different_boot")

    def test_awake_age_is_bounded(self):
        stale = PendingSleep(BOOT, 1000.0 - MAX_AGE_SECONDS - 1, 5000.0 - MAX_AGE_SECONDS - 1)
        self.assertEqual(decide(stale).code, "sleep_continuation.expired")
        # A record from the future is not fresh either.
        self.assertEqual(decide(PendingSleep(BOOT, 1001.0, 5001.0)).code,
                         "sleep_continuation.expired")

    def test_a_suspend_since_the_record_refuses(self):
        # Monotonic stopped for 100 s while boottime kept counting: the machine
        # slept in between. Sleeping it again on wake is not what was asked.
        record = PendingSleep(BOOT, 990.0, 4890.0)
        self.assertEqual(decide(record).code, "sleep_continuation.slept_since")


class PendingSleepStoreTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.store = PendingSleepStore(Path(self._temporary.name).resolve())

    def test_take_consumes_exactly_once(self):
        self.store.record(PendingSleep(BOOT, 1.5, 2.5))
        self.assertEqual(self.store.take(), PendingSleep(BOOT, 1.5, 2.5))
        self.assertIsNone(self.store.take())

    def test_record_replaces_rather_than_queues(self):
        self.store.record(PendingSleep(BOOT, 1.0, 2.0))
        self.store.record(PendingSleep(BOOT, 3.0, 4.0))
        self.assertEqual(self.store.take(), PendingSleep(BOOT, 3.0, 4.0))

    def test_clear_leaves_nothing(self):
        self.store.record(PendingSleep(BOOT, 1.0, 2.0))
        self.store.clear()
        self.assertIsNone(self.store.take())

    def test_an_unreadable_record_is_nothing_recorded(self):
        target = Path(self._temporary.name) / "pending-sleep.json"
        target.write_text("{not json", encoding="utf-8")
        self.assertIsNone(self.store.take())
        target.write_text('{"schema_version": 1, "boot_hash": "", "recorded_monotonic": 1, "recorded_boottime": 2}',
                          encoding="utf-8")
        self.assertIsNone(self.store.take())

    def test_invalid_records_are_refused_at_write(self):
        with self.assertRaises(ValueError):
            self.store.record(PendingSleep("", 1.0, 2.0))
        with self.assertRaises(ValueError):
            self.store.record(PendingSleep(BOOT, True, 2.0))


if __name__ == "__main__":
    unittest.main()
