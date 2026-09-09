from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.delivery.relaunch_intent_store import (  # noqa: E402
    FILENAME,
    RelaunchIntentStore,
)
from hdm.domain.relaunch_intent import (  # noqa: E402
    MAX_AGE_SECONDS,
    RelaunchIntent,
    RelaunchVerdict,
    decide_relaunch,
)


BOOT = "b" * 64
INTENT = RelaunchIntent("1145360", BOOT, 1200.0)


class DecisionTests(unittest.TestCase):
    def test_a_fresh_intent_from_this_boot_relaunches(self) -> None:
        decision = decide_relaunch(INTENT, boot_hash=BOOT, now_boot_seconds=1205.0)

        self.assertIs(decision.verdict, RelaunchVerdict.RELAUNCH)
        self.assertTrue(decision.should_relaunch)
        self.assertEqual(decision.steam_app_id, "1145360")

    def test_nothing_recorded_is_not_a_refusal(self) -> None:
        # Distinct states: one is the ordinary case, the other is worth a code
        # in a bug report.
        decision = decide_relaunch(None, boot_hash=BOOT, now_boot_seconds=1.0)

        self.assertIs(decision.verdict, RelaunchVerdict.NOTHING_RECORDED)
        self.assertFalse(decision.should_relaunch)

    def test_a_reboot_ends_every_claim_the_record_had(self) -> None:
        # The player turned the machine off. Whatever they wanted before that
        # is finished.
        decision = decide_relaunch(
            INTENT, boot_hash="c" * 64, now_boot_seconds=1205.0
        )

        self.assertIs(decision.verdict, RelaunchVerdict.REFUSED)
        self.assertEqual(decision.code, "relaunch.different_boot")

    def test_an_unidentifiable_boot_refuses_rather_than_assuming(self) -> None:
        decision = decide_relaunch(INTENT, boot_hash="", now_boot_seconds=1205.0)

        self.assertIs(decision.verdict, RelaunchVerdict.REFUSED)
        self.assertEqual(decision.code, "relaunch.different_boot")

    def test_a_stale_intent_is_refused(self) -> None:
        # A player who walked away must not come back to a game that started
        # itself.
        decision = decide_relaunch(
            INTENT, boot_hash=BOOT, now_boot_seconds=1200.0 + MAX_AGE_SECONDS + 1
        )

        self.assertEqual(decision.code, "relaunch.expired")

    def test_the_boundary_itself_is_still_honoured(self) -> None:
        decision = decide_relaunch(
            INTENT, boot_hash=BOOT, now_boot_seconds=1200.0 + MAX_AGE_SECONDS
        )

        self.assertTrue(decision.should_relaunch)

    def test_an_intent_recorded_in_the_future_is_refused(self) -> None:
        decision = decide_relaunch(INTENT, boot_hash=BOOT, now_boot_seconds=1199.0)

        self.assertEqual(decision.code, "relaunch.recorded_in_the_future")

    def test_a_disturbed_device_outranks_every_other_fact(self) -> None:
        # A half-detached eGPU needs a person, not a game launching into it.
        decision = decide_relaunch(
            INTENT,
            boot_hash=BOOT,
            now_boot_seconds=1201.0,
            device_disturbed=True,
        )

        self.assertIs(decision.verdict, RelaunchVerdict.REFUSED)
        self.assertEqual(decision.code, "relaunch.device_disturbed")

    def test_a_refusal_still_names_the_game_it_was_about(self) -> None:
        # So a caller can say what it declined to reopen.
        decision = decide_relaunch(
            INTENT, boot_hash="c" * 64, now_boot_seconds=1205.0
        )

        self.assertEqual(decision.steam_app_id, "1145360")


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name).resolve()
        self.store = RelaunchIntentStore(self.root)

    def test_nothing_recorded_reads_as_none(self) -> None:
        self.assertIsNone(self.store.peek())
        self.assertIsNone(self.store.take())

    def test_an_intent_survives_a_round_trip(self) -> None:
        self.store.record(INTENT)

        self.assertEqual(self.store.peek(), INTENT)

    def test_taking_consumes_it_exactly_once(self) -> None:
        # A relaunch that does happen must not happen twice.
        self.store.record(INTENT)

        self.assertEqual(self.store.take(), INTENT)
        self.assertIsNone(self.store.take())

    def test_recording_replaces_rather_than_queues(self) -> None:
        # Two games cannot both be the game that was closed.
        self.store.record(INTENT)
        second = replace(INTENT, steam_app_id="220")
        self.store.record(second)

        self.assertEqual(self.store.take(), second)
        self.assertIsNone(self.store.take())

    def test_clearing_removes_it(self) -> None:
        self.store.record(INTENT)

        self.store.clear()

        self.assertIsNone(self.store.peek())

    def test_clearing_nothing_is_not_an_error(self) -> None:
        self.store.clear()

    def test_unreadable_content_reads_as_nothing_recorded(self) -> None:
        # Failing the other way would start a game nobody asked for.
        (self.root / FILENAME).write_bytes(b"\xff\xfe not json")

        self.assertIsNone(self.store.peek())

    def test_a_record_with_no_boot_identity_is_discarded(self) -> None:
        (self.root / FILENAME).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "steam_app_id": "1145360",
                    "boot_hash": "",
                    "recorded_boot_seconds": 1.0,
                }
            ),
            encoding="ascii",
        )

        self.assertIsNone(self.store.peek())

    def test_a_malformed_app_id_is_discarded(self) -> None:
        (self.root / FILENAME).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "steam_app_id": "; rm -rf /",
                    "boot_hash": BOOT,
                    "recorded_boot_seconds": 1.0,
                }
            ),
            encoding="ascii",
        )

        self.assertIsNone(self.store.peek())

    def test_a_boolean_timestamp_is_not_a_number(self) -> None:
        (self.root / FILENAME).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "steam_app_id": "1145360",
                    "boot_hash": BOOT,
                    "recorded_boot_seconds": True,
                }
            ),
            encoding="ascii",
        )

        self.assertIsNone(self.store.peek())

    def test_a_future_schema_is_discarded_rather_than_guessed(self) -> None:
        (self.root / FILENAME).write_text(
            json.dumps({"schema_version": 99, "steam_app_id": "1145360"}),
            encoding="ascii",
        )

        self.assertIsNone(self.store.peek())

    def test_a_symlinked_record_is_refused_loudly(self) -> None:
        target = self.root / "elsewhere.json"
        target.write_text("{}", encoding="ascii")
        try:
            (self.root / FILENAME).symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable on this platform")

        with self.assertRaises(ValueError):
            self.store.peek()

    def test_a_relative_state_root_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            RelaunchIntentStore(Path("relative"))

    def test_an_invalid_app_id_is_never_written(self) -> None:
        with self.assertRaises(ValueError):
            self.store.record(replace(INTENT, steam_app_id="../etc"))

    def test_an_intent_with_no_boot_identity_is_never_written(self) -> None:
        with self.assertRaises(ValueError):
            self.store.record(replace(INTENT, boot_hash=""))


if __name__ == "__main__":
    unittest.main()
