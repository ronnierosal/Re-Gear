from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.delivery.saved_tv_store import (  # noqa: E402
    FILENAME,
    MAX_BYTES,
    SavedTvStore,
)
from regear.domain.models import (  # noqa: E402
    Confidence,
    DisplayKind,
    DisplayObservation,
)
from regear.domain.saved_tv import (  # noqa: E402
    SavedTvProfile,
    SavedTvState,
    decide_saved_tv,
    remember_docked_tv,
)


TV = DisplayObservation(
    stable_id="display:9f2c41ab77e0d135",
    kind=DisplayKind.EXTERNAL,
    connector="HDMI-A-1",
    connected=True,
    active=True,
    edid_ready=True,
    confidence=Confidence.VERIFIED,
)

PROFILE = SavedTvProfile(
    display_stable_id="display:9f2c41ab77e0d135",
    edid_identified=True,
    label="Living room TV",
)


class RememberTests(unittest.TestCase):
    """Only an explicitly successful dock leaves intent behind."""

    def test_a_successful_dock_is_remembered(self) -> None:
        profile = remember_docked_tv(
            display=TV, transition_succeeded=True, label="Living room TV"
        )

        self.assertIsNotNone(profile)
        self.assertEqual(profile.display_stable_id, TV.stable_id)
        self.assertTrue(profile.edid_identified)
        self.assertEqual(profile.label, "Living room TV")

    def test_a_transition_that_did_not_succeed_leaves_nothing(self) -> None:
        # Remembering one would later resume a player to a TV they never got
        # to, with no way for them to understand why.
        self.assertIsNone(remember_docked_tv(display=TV, transition_succeeded=False))

    def test_no_display_leaves_nothing(self) -> None:
        self.assertIsNone(remember_docked_tv(display=None, transition_succeeded=True))

    def test_only_a_verified_connected_external_display_is_a_tv(self) -> None:
        for change in (
            {"kind": DisplayKind.INTERNAL},
            {"kind": DisplayKind.UNKNOWN},
            {"connected": False},
            {"connected": None},
            {"confidence": Confidence.OBSERVED},
            {"confidence": Confidence.UNKNOWN},
            {"stable_id": ""},
        ):
            with self.subTest(change=change):
                self.assertIsNone(
                    remember_docked_tv(
                        display=replace(TV, **change), transition_succeeded=True
                    )
                )

    def test_identity_grade_is_recorded_honestly_not_demanded(self) -> None:
        # A profile without EDID identity is still worth remembering; it simply
        # waits for a manual switch instead of resuming by itself.
        profile = remember_docked_tv(
            display=replace(TV, edid_ready=False), transition_succeeded=True
        )

        self.assertIsNotNone(profile)
        self.assertFalse(profile.edid_identified)

        decision = decide_saved_tv(
            profile=profile, displays=(TV,), scan_complete=True
        )
        self.assertIs(decision.state, SavedTvState.SETTLED)
        self.assertFalse(decision.may_continue)


class StoreRoundTripTests(unittest.TestCase):
    def store(self, root: Path) -> SavedTvStore:
        return SavedTvStore(root)

    def test_nothing_remembered_reads_as_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(self.store(Path(directory)).load())

    def test_a_profile_survives_a_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(Path(directory))
            store.record(PROFILE)

            self.assertEqual(store.load(), PROFILE)

    def test_reading_does_not_consume_it(self) -> None:
        # A standing preference, not a one-shot: the same TV is resumed to
        # every time it appears.
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(Path(directory))
            store.record(PROFILE)

            self.assertEqual(store.load(), PROFILE)
            self.assertEqual(store.load(), PROFILE)

    def test_docking_somewhere_new_replaces_rather_than_accumulates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(Path(directory))
            store.record(PROFILE)
            other = replace(PROFILE, display_stable_id="display:0011223344556677")
            store.record(other)

            self.assertEqual(store.load(), other)

    def test_forgetting_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(Path(directory))
            store.record(PROFILE)
            store.forget()
            store.forget()

            self.assertIsNone(store.load())

    def test_a_record_is_not_world_readable(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX modes are unavailable on this host")
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(Path(directory))
            store.record(PROFILE)

            mode = (Path(directory) / FILENAME).stat().st_mode
            self.assertEqual(mode & 0o077, 0)


class StoreRefusalTests(unittest.TestCase):
    """Every read failure is "nothing remembered", which does nothing."""

    def write(self, root: Path, raw: str) -> None:
        (root / FILENAME).write_text(raw, encoding="utf-8", newline="\n")

    def test_corruption_reads_as_nothing_remembered(self) -> None:
        for raw in (
            "",
            "not json",
            "[]",
            json.dumps({"schema_version": 99, "display_stable_id": "display:a"}),
            json.dumps({"schema_version": 1}),
            json.dumps({"schema_version": 1, "display_stable_id": ""}),
            json.dumps(
                {"schema_version": 1, "display_stable_id": "a b", "edid_identified": True}
            ),
        ):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.write(root, raw)

                self.assertIsNone(SavedTvStore(root).load())

    def test_a_record_that_cannot_say_how_it_was_identified_is_not_a_record(self) -> None:
        # Without that, nothing can say whether resuming to it is safe.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(
                root,
                json.dumps(
                    {
                        "schema_version": 1,
                        "display_stable_id": "display:9f2c41ab77e0d135",
                        "edid_identified": "yes",
                    }
                ),
            )

            self.assertIsNone(SavedTvStore(root).load())

    def test_an_oversized_record_reads_as_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "x" * (MAX_BYTES + 1))

            self.assertIsNone(SavedTvStore(root).load())

    def test_an_invalid_identity_is_refused_on_the_way_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SavedTvStore(Path(directory))

            for bad in ("", "has space", "x" * 129, "new\nline"):
                with self.subTest(bad=bad):
                    with self.assertRaises(ValueError):
                        store.record(replace(PROFILE, display_stable_id=bad))

    def test_a_relative_state_root_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            SavedTvStore(Path("relative/path"))

    def test_a_symlinked_record_is_refused_loudly(self) -> None:
        # Not corruption: someone redirecting the file.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            elsewhere = root / "elsewhere.json"
            elsewhere.write_text("{}", encoding="utf-8")
            try:
                (root / FILENAME).symlink_to(elsewhere)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable on this host")

            with self.assertRaises(ValueError):
                SavedTvStore(root).load()


class LabelTests(unittest.TestCase):
    """A label is EDID text off a cable: bounded, never matched on."""

    def test_a_label_is_bounded_and_stripped_of_control_characters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SavedTvStore(Path(directory))
            store.record(replace(PROFILE, label="A" * 200))

            loaded = store.load()
            self.assertLessEqual(len(loaded.label), 64)

    def test_a_label_cannot_reflow_a_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SavedTvStore(Path(directory))
            store.record(replace(PROFILE, label="TV\r\nSafe to unplug the cable"))

            loaded = store.load()
            self.assertNotIn("\n", loaded.label)
            self.assertNotIn("\r", loaded.label)

    def test_the_label_is_never_what_gets_matched(self) -> None:
        # Identity is the identity. A relabelled TV is the same TV.
        relabelled = replace(PROFILE, label="Something else entirely")

        decision = decide_saved_tv(
            profile=relabelled, displays=(TV,), scan_complete=True
        )

        self.assertIs(decision.state, SavedTvState.READY)


if __name__ == "__main__":
    unittest.main()
