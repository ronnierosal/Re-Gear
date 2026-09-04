import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from hdm.delivery.tdp_journal import FileTdpJournal, FILENAME, MAX_BYTES
from hdm.ports.tdp import TdpReading, TdpRegister, TdpSessionRecord


class TdpJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.journal = FileTdpJournal(self.root)
        self.reading = TdpReading("a" * 64, TdpRegister(15, 7, 30), TdpRegister(15, 15, 43), TdpRegister(15, 15, 53))
        self.record = TdpSessionRecord(self.reading, self.reading, "pending", 20)

    def test_pending_survives_reopen_then_active_and_clear_roundtrip(self):
        self.assertIsNone(self.journal.load())
        self.journal.save(self.record)
        self.assertEqual(FileTdpJournal(self.root).load(), self.record)
        active = replace(self.record, phase="active", pending_watts=None)
        self.journal.save(active)
        self.assertEqual(self.journal.load(), active)
        self.journal.save(None)
        self.assertIsNone(self.journal.load())

    def test_replace_failure_preserves_previous_state_and_removes_temporary(self):
        self.journal.save(self.record)
        with patch("hdm.delivery.tdp_journal.os.replace", side_effect=OSError("failure")):
            with self.assertRaises(OSError):
                self.journal.save(None)
        self.assertEqual(self.journal.load(), self.record)
        self.assertEqual([p.name for p in self.root.iterdir()], [FILENAME])

    def test_corrupt_duplicate_unknown_schema_or_oversized_is_not_empty(self):
        for text in ('{', '{"schema":1,"schema":1,"record":null}', '{"schema":true,"record":null}', '{"schema":2,"record":null}', ' ' * (MAX_BYTES + 1)):
            with self.subTest(text=text[:30]):
                (self.root / FILENAME).write_text(text)
                with self.assertRaises(ValueError):
                    self.journal.load()

    def test_invalid_nested_state_is_rejected(self):
        self.journal.save(self.record)
        original = json.loads((self.root / FILENAME).read_text())
        for name, value in (("phase", "bogus"), ("pending_watts", True), ("pending_watts", 31)):
            with self.subTest(name=name, value=value):
                payload = json.loads(json.dumps(original))
                payload["record"][name] = value
                (self.root / FILENAME).write_text(json.dumps(payload))
                with self.assertRaises(ValueError):
                    self.journal.load()

    def test_mismatched_baseline_is_rejected(self):
        with self.assertRaises(ValueError):
            TdpSessionRecord(self.reading, replace(self.reading, binding="b" * 64))

    def test_directory_target_is_rejected(self):
        (self.root / FILENAME).mkdir()
        with self.assertRaises(ValueError):
            self.journal.load()
        with self.assertRaises(ValueError):
            self.journal.save(None)

    def test_paths_and_private_details_do_not_enter_journal(self):
        self.journal.save(self.record)
        payload = (self.root / FILENAME).read_text()
        self.assertNotIn(str(self.root), payload)
        self.assertNotIn("username", payload)
        self.assertLess(len(payload), MAX_BYTES)


if __name__ == "__main__":
    unittest.main()
