from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.delivery.graphics_backup import (  # noqa: E402
    BackupError,
    BackupManager,
    digest_of,
)


class BackupManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "graphics.ini"
        self.source.write_text("[G]\nk=1\n", encoding="utf-8")
        self.manager = BackupManager(self.base / "backups", limit=3)
        self.identity = "620.proton.graphics.ini"

    def test_relative_root_is_refused(self):
        with self.assertRaises(ValueError):
            BackupManager(Path("backups"))

    def test_capture_records_the_exact_bytes(self):
        payload = self.source.read_bytes()
        record = self.manager.capture(self.identity, self.source, "portable")
        self.assertEqual(record.digest, digest_of(payload))
        self.assertEqual(record.size, len(payload))
        self.assertEqual(self.manager.payload(record), payload)

    def test_capture_does_not_modify_the_source(self):
        before = self.source.read_bytes()
        self.manager.capture(self.identity, self.source, "portable")
        self.assertEqual(self.source.read_bytes(), before)

    def test_rotating_backups_are_bounded_and_pruned_oldest_first(self):
        original = self.source.read_bytes()
        self.manager.capture(self.identity, self.source, "portable")
        for index in range(5):
            self.source.write_text(f"[G]\nk={index}\n", encoding="utf-8")
            self.manager.capture(self.identity, self.source, "portable")
        records = self.manager.records(self.identity)
        # The limit bounds the rotating copies; the baseline is kept besides.
        self.assertEqual([record.sequence for record in records], [1, 4, 5, 6])
        self.assertEqual([record.baseline for record in records], [True, False, False, False])
        self.assertEqual(self.manager.payload(records[0]), original)
        payloads = sorted((self.manager.root / self.identity).glob("*.bak"))
        self.assertEqual(len(payloads), 4)

    def test_the_baseline_survives_any_number_of_later_captures(self):
        original = self.source.read_bytes()
        self.manager.capture(self.identity, self.source, "portable")
        for index in range(20):
            self.source.write_text(f"[G]\nk={index}\n", encoding="utf-8")
            self.manager.capture(self.identity, self.source, "tv_docked")
        baseline = self.manager.baseline(self.identity)
        self.assertTrue(baseline.verified)
        self.assertEqual(self.manager.payload(baseline.record), original)

    def test_exactly_one_baseline_is_ever_recorded(self):
        for _ in range(4):
            self.manager.capture(self.identity, self.source, "portable")
        baselines = [record for record in self.manager.records(self.identity) if record.baseline]
        self.assertEqual(len(baselines), 1)
        self.assertEqual(baselines[0].sequence, 1)

    def test_identities_are_bounded_independently(self):
        other = "570.native.graphics.ini"
        for _ in range(4):
            self.manager.capture(self.identity, self.source, "portable")
            self.manager.capture(other, self.source, "tv_docked")
        self.assertEqual(len(self.manager.records(self.identity)), 4)
        self.assertEqual(len(self.manager.records(other)), 4)

    def test_restore_puts_back_the_exact_bytes(self):
        original = self.source.read_bytes()
        record = self.manager.capture(self.identity, self.source, "portable")
        self.source.write_text("[G]\nk=99\n", encoding="utf-8")
        self.assertTrue(self.manager.restore(record, self.source))
        self.assertEqual(self.source.read_bytes(), original)

    def test_restore_refuses_a_tampered_payload(self):
        record = self.manager.capture(self.identity, self.source, "portable")
        (self.manager.root / self.identity / record.payload_name).write_bytes(b"tampered")
        with self.assertRaises(BackupError):
            self.manager.restore(record, self.source)
        self.assertEqual(self.source.read_text(encoding="utf-8"), "[G]\nk=1\n")

    def test_restore_refuses_a_symlinked_destination(self):
        record = self.manager.capture(self.identity, self.source, "portable")
        link = self.base / "linked.ini"
        link.symlink_to(self.source)
        with self.assertRaises(BackupError):
            self.manager.restore(record, link)

    def test_symlinked_source_is_not_backed_up(self):
        link = self.base / "linked.ini"
        link.symlink_to(self.source)
        with self.assertRaises(BackupError):
            self.manager.capture(self.identity, link, "portable")

    def test_missing_source_is_a_backup_error_not_an_empty_backup(self):
        with self.assertRaises(BackupError):
            self.manager.capture(self.identity, self.base / "absent.ini", "portable")
        self.assertEqual(self.manager.records(self.identity), ())

    def test_unreadable_record_is_skipped_rather_than_guessed(self):
        first = self.manager.capture(self.identity, self.source, "portable")
        second = self.manager.capture(self.identity, self.source, "portable")
        stem = first.payload_name[: -len(".bak")]
        (self.manager.root / self.identity / f"{stem}.json").write_text("{", encoding="utf-8")
        records = self.manager.records(self.identity)
        self.assertEqual([record.sequence for record in records], [second.sequence])

    def test_latest_is_the_newest_capture(self):
        self.manager.capture(self.identity, self.source, "portable")
        self.source.write_text("[G]\nk=2\n", encoding="utf-8")
        newest = self.manager.capture(self.identity, self.source, "tv_docked")
        self.assertEqual(self.manager.latest(self.identity).sequence, newest.sequence)
        self.assertEqual(self.manager.latest(self.identity).mode, "tv_docked")

    def test_no_temporary_files_are_left_behind(self):
        self.manager.capture(self.identity, self.source, "portable")
        leftovers = [
            path.name
            for path in (self.manager.root / self.identity).iterdir()
            if path.name.endswith(".tmp")
        ]
        self.assertEqual(leftovers, [])

    def test_invalid_identity_is_refused(self):
        for value in ("", "../escape", "a/b", "x" * 200):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.manager.capture(value, self.source, "portable")

    def test_restored_file_keeps_a_readable_mode(self):
        os.chmod(self.source, 0o640)
        record = self.manager.capture(self.identity, self.source, "portable")
        self.source.write_text("[G]\nk=3\n", encoding="utf-8")
        self.assertTrue(self.manager.restore(record, self.source))
        self.assertTrue(os.access(self.source, os.R_OK))


if __name__ == "__main__":
    unittest.main()
