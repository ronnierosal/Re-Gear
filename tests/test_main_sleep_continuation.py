"""The backend end of the sleep continuation: record, claim, refuse."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_main_process_delivery import load_main_module

BOOT = "b" * 64


class SleepContinuationRpcTests(unittest.TestCase):
    """A disconnect asked for as a sleep survives the session restart it causes.

    The panel that pressed the button is destroyed by the restart before its
    sleep step runs, so the wish is written with the disconnect and claimed by
    the panel that comes up afterwards. The claim consumes; a refusal consumes
    too; and none of it sleeps anything -- that stays with the panel and Steam.
    """

    def setUp(self):
        self.module = load_main_module(real_dock_gate=True)
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name).resolve()
        for target, value in (("CATALOG_ROOT", self.root), ("read_boot_hash", lambda: BOOT)):
            patcher = patch.object(self.module, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.plugin = self.module.Plugin.__new__(self.module.Plugin)

    def take(self):
        return asyncio.run(self.plugin.take_pending_sleep())

    def test_nothing_recorded_is_not_pending(self):
        payload = self.take()
        self.assertEqual(payload, {"schema_version": 1, "pending": False,
                                   "code": "sleep_continuation.nothing_recorded"})

    def test_a_recorded_continuation_is_claimed_exactly_once(self):
        self.assertTrue(asyncio.run(self.plugin._record_sleep_continuation()))
        first = self.take()
        self.assertIs(first["pending"], True)
        self.assertEqual(first["code"], "sleep_continuation.pending")
        second = self.take()
        self.assertIs(second["pending"], False)
        self.assertEqual(second["code"], "sleep_continuation.nothing_recorded")

    def test_clearing_leaves_nothing_to_claim(self):
        asyncio.run(self.plugin._record_sleep_continuation())
        asyncio.run(self.plugin._clear_sleep_continuation())
        self.assertIs(self.take()["pending"], False)

    def test_a_record_from_another_boot_is_refused_and_consumed(self):
        with patch.object(self.module, "read_boot_hash", lambda: "a" * 64):
            asyncio.run(self.plugin._record_sleep_continuation())
        payload = self.take()
        self.assertIs(payload["pending"], False)
        self.assertEqual(payload["code"], "sleep_continuation.different_boot")
        self.assertEqual(self.take()["code"], "sleep_continuation.nothing_recorded")

    def test_a_record_that_lived_through_a_suspend_is_refused(self):
        # Written as if the machine then slept for 100 s: boottime moved on
        # while monotonic did not. The panel that wakes must not sleep it again.
        import time
        store = self.module.PendingSleepStore(self.root)
        store.record(self.module.PendingSleep(
            BOOT, time.monotonic(),
            self.module._relaunch_now(self.module.RelaunchClock.BOOTTIME) - 100.0))
        self.assertEqual(self.take()["code"], "sleep_continuation.slept_since")

    def test_an_old_record_is_refused(self):
        import time
        store = self.module.PendingSleepStore(self.root)
        store.record(self.module.PendingSleep(
            BOOT, time.monotonic() - 1000.0,
            self.module._relaunch_now(self.module.RelaunchClock.BOOTTIME) - 1000.0))
        self.assertEqual(self.take()["code"], "sleep_continuation.expired")

    def test_a_record_that_cannot_be_written_does_not_raise(self):
        with patch.object(self.module, "CATALOG_ROOT", Path("relative/never")):
            self.assertFalse(asyncio.run(self.plugin._record_sleep_continuation()))


if __name__ == "__main__":
    unittest.main()
