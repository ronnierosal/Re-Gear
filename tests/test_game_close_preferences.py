from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.delivery.game_close_preferences import (  # noqa: E402
    FILENAME,
    MAX_RECORDS,
    GameClosePreferenceStore,
)
from hdm.domain.game_close_consent import (  # noqa: E402
    GameClosePreference,
    InterruptIntent,
)


HADES = GameClosePreference(
    "1145360", InterruptIntent.DISCONNECT, skip_confirmation=True
)


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name).resolve()
        self.store = GameClosePreferenceStore(self.root)

    def test_nothing_stored_reads_as_no_answer(self) -> None:
        self.assertIsNone(self.store.load("1145360", InterruptIntent.DISCONNECT))
        self.assertEqual(self.store.load_all(), ())

    def test_an_answer_survives_a_round_trip(self) -> None:
        self.store.remember(HADES)

        self.assertEqual(
            self.store.load("1145360", InterruptIntent.DISCONNECT), HADES
        )

    def test_an_answer_is_keyed_by_intent_as_well_as_game(self) -> None:
        self.store.remember(HADES)

        self.assertIsNone(self.store.load("1145360", InterruptIntent.SLEEP))

    def test_an_answer_is_never_returned_for_another_game(self) -> None:
        self.store.remember(HADES)

        self.assertIsNone(self.store.load("220", InterruptIntent.DISCONNECT))

    def test_both_intents_can_be_answered_for_one_game(self) -> None:
        sleep = GameClosePreference(
            "1145360", InterruptIntent.SLEEP, relaunch_after=True
        )
        self.store.remember(HADES)
        self.store.remember(sleep)

        self.assertEqual(self.store.load("1145360", InterruptIntent.SLEEP), sleep)
        self.assertEqual(
            self.store.load("1145360", InterruptIntent.DISCONNECT), HADES
        )

    def test_answering_again_replaces_rather_than_accumulates(self) -> None:
        self.store.remember(HADES)
        changed = GameClosePreference(
            "1145360", InterruptIntent.DISCONNECT, skip_confirmation=False
        )
        self.store.remember(changed)

        self.assertEqual(self.store.load_all(), (changed,))

    def test_forgetting_returns_one_game_to_being_asked(self) -> None:
        other = GameClosePreference(
            "220", InterruptIntent.DISCONNECT, skip_confirmation=True
        )
        self.store.remember(HADES)
        self.store.remember(other)

        self.store.forget("1145360", InterruptIntent.DISCONNECT)

        self.assertIsNone(self.store.load("1145360", InterruptIntent.DISCONNECT))
        self.assertEqual(self.store.load("220", InterruptIntent.DISCONNECT), other)

    def test_forgetting_one_intent_leaves_the_other_answered(self) -> None:
        sleep = GameClosePreference("1145360", InterruptIntent.SLEEP, True)
        self.store.remember(HADES)
        self.store.remember(sleep)

        self.store.forget("1145360", InterruptIntent.DISCONNECT)

        self.assertEqual(self.store.load("1145360", InterruptIntent.SLEEP), sleep)

    def test_forgetting_something_never_stored_is_not_an_error(self) -> None:
        self.store.forget("1145360", InterruptIntent.SLEEP)

        self.assertEqual(self.store.load_all(), ())


class DurabilityTests(unittest.TestCase):
    """Losing a stored answer must cost a prompt, never a save."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name).resolve()
        self.store = GameClosePreferenceStore(self.root)

    def test_unparseable_content_reads_as_no_answer(self) -> None:
        (self.root / FILENAME).write_bytes(b"{not json")

        self.assertEqual(self.store.load_all(), ())

    def test_a_future_schema_reads_as_no_answer_rather_than_guessing(self) -> None:
        (self.root / FILENAME).write_text(
            json.dumps({"schema_version": 99, "preferences": []}), encoding="ascii"
        )

        self.assertEqual(self.store.load_all(), ())

    def test_one_corrupt_entry_does_not_discard_the_others(self) -> None:
        (self.root / FILENAME).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "preferences": [
                        {"steam_app_id": "not-an-app-id", "intent": "sleep"},
                        {
                            "steam_app_id": "1145360",
                            "intent": "disconnect",
                            "skip_confirmation": True,
                            "relaunch_after": False,
                        },
                    ],
                }
            ),
            encoding="ascii",
        )

        self.assertEqual(self.store.load_all(), (HADES,))

    def test_an_unknown_intent_is_dropped_rather_than_coerced(self) -> None:
        # A record whose intent cannot be read cannot be matched to an action,
        # and guessing which action the player agreed to is the whole hazard.
        (self.root / FILENAME).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "preferences": [
                        {
                            "steam_app_id": "1145360",
                            "intent": "shutdown",
                            "skip_confirmation": True,
                            "relaunch_after": False,
                        }
                    ],
                }
            ),
            encoding="ascii",
        )

        self.assertEqual(self.store.load_all(), ())

    def test_a_symlinked_store_is_refused_loudly(self) -> None:
        # Not a corrupt preference: someone redirecting a root-written file.
        target = self.root / "elsewhere.json"
        target.write_text("{}", encoding="ascii")
        try:
            (self.root / FILENAME).symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable on this platform")

        with self.assertRaises(ValueError):
            self.store.load_all()

    def test_a_relative_state_root_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            GameClosePreferenceStore(Path("relative/state"))

    def test_the_newest_answer_survives_the_bound(self) -> None:
        for index in range(MAX_RECORDS + 5):
            self.store.remember(
                GameClosePreference(
                    str(index + 1), InterruptIntent.DISCONNECT, skip_confirmation=True
                )
            )

        stored = self.store.load_all()
        self.assertEqual(len(stored), MAX_RECORDS)
        self.assertEqual(
            stored[-1].steam_app_id, str(MAX_RECORDS + 5)
        )
        # The oldest was dropped, so that game is asked about again.
        self.assertIsNone(self.store.load("1", InterruptIntent.DISCONNECT))


class ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.store = GameClosePreferenceStore(Path(self._temporary.name).resolve())

    def test_a_non_numeric_app_id_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self.store.remember(
                GameClosePreference("../etc", InterruptIntent.SLEEP, True)
            )

    def test_a_non_boolean_answer_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self.store.remember(
                GameClosePreference("1145360", InterruptIntent.SLEEP, "yes")  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
