from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.delivery.graphics_management_state import (  # noqa: E402
    RECORD_VERSION,
    Lifecycle,
    ManagementRecord,
    ManagementState,
    ManagementStateStore,
)


def record(**overrides):
    values = dict(
        identity="620.proton.abcdef",
        target_path="/tmp/game/graphics.ini",
        managed_digest="a" * 64,
        baseline_payload_name="00000001.aa.bak",
        baseline_digest="b" * 64,
        mode="portable",
        profile_version=1,
        schema_id="ue-gameusersettings",
        schema_version="5",
        schema_signature="A/x;B/y",
    )
    values.update(overrides)
    return ManagementRecord(**values)


class ManagementStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "state"
        self.store = ManagementStateStore(self.root)

    def test_relative_root_is_refused(self):
        with self.assertRaises(ValueError):
            ManagementStateStore(Path("state"))

    def test_round_trip(self):
        original = record()
        self.store.save(original)
        lookup = self.store.load(original.identity)
        self.assertIs(lookup.state, ManagementState.LOADED)
        self.assertTrue(lookup.trusted)
        self.assertEqual(lookup.record, original)

    def test_the_record_format_version_is_not_the_game_schema_version(self):
        # These were once the same JSON key, so every record read back as
        # unrecognised and no conflict could ever be detected.
        self.store.save(record(schema_version="5"))
        written = json.loads((self.root / "620.proton.abcdef.json").read_text())
        self.assertEqual(written["record_version"], RECORD_VERSION)
        self.assertEqual(written["schema_version"], "5")

    def test_a_missing_record_is_absent_not_untrusted(self):
        # The distinction is the whole point: absent may be a first enrollment,
        # untrusted never is.
        lookup = self.store.load("620.proton.nothing")
        self.assertIs(lookup.state, ManagementState.ABSENT)
        self.assertIsNone(lookup.record)
        self.assertFalse(lookup.trusted)

    def test_a_corrupt_record_is_untrusted_not_absent(self):
        self.store.save(record())
        (self.root / "620.proton.abcdef.json").write_text("{not json", encoding="utf-8")
        lookup = self.store.load("620.proton.abcdef")
        self.assertIs(lookup.state, ManagementState.UNTRUSTED)
        self.assertFalse(lookup.trusted)
        self.assertTrue(lookup.detail)

    def test_a_deleted_record_is_absent_and_a_truncated_one_is_untrusted(self):
        self.store.save(record())
        path = self.root / "620.proton.abcdef.json"
        path.write_text("", encoding="utf-8")
        self.assertIs(self.store.load("620.proton.abcdef").state, ManagementState.UNTRUSTED)
        path.unlink()
        self.assertIs(self.store.load("620.proton.abcdef").state, ManagementState.ABSENT)

    def test_a_record_naming_another_target_is_untrusted(self):
        self.store.save(record())
        path = self.root / "620.proton.abcdef.json"
        value = json.loads(path.read_text())
        value["identity"] = "620.proton.somewhere-else"
        path.write_text(json.dumps(value), encoding="utf-8")
        self.assertIs(self.store.load("620.proton.abcdef").state, ManagementState.UNTRUSTED)

    def test_a_record_from_a_future_format_is_not_trusted(self):
        self.store.save(record())
        path = self.root / "620.proton.abcdef.json"
        value = json.loads(path.read_text())
        value["record_version"] = RECORD_VERSION + 1
        path.write_text(json.dumps(value), encoding="utf-8")
        self.assertIs(self.store.load("620.proton.abcdef").state, ManagementState.UNTRUSTED)

    def test_stop_managing_keeps_the_baseline_and_clears_the_claim(self):
        self.store.save(record())
        updated = self.store.stop_managing("620.proton.abcdef")
        self.assertFalse(updated.managing)
        self.assertIs(updated.lifecycle, Lifecycle.STOPPED)
        self.assertEqual(updated.baseline_payload_name, "00000001.aa.bak")
        self.assertFalse(self.store.load("620.proton.abcdef").record.managing)

    def test_stop_managing_an_unmanaged_target_is_none(self):
        self.assertIsNone(self.store.stop_managing("620.proton.nothing"))

    def test_forget_removes_the_record_and_is_idempotent(self):
        self.store.save(record())
        self.store.forget("620.proton.abcdef")
        self.assertIs(self.store.load("620.proton.abcdef").state, ManagementState.ABSENT)
        self.store.forget("620.proton.abcdef")

    def test_lifecycle_round_trips_and_drives_managing(self):
        self.store.save(record(lifecycle=Lifecycle.RESTORED))
        loaded = self.store.load("620.proton.abcdef").record
        self.assertIs(loaded.lifecycle, Lifecycle.RESTORED)
        self.assertFalse(loaded.managing)
        self.assertTrue(loaded.settled)

    def test_managed_is_neither_settled_nor_stopped(self):
        self.store.save(record())
        loaded = self.store.load("620.proton.abcdef").record
        self.assertTrue(loaded.managing)
        self.assertFalse(loaded.settled)

    def test_settle_records_the_digest_that_was_left_behind(self):
        self.store.save(record())
        updated = self.store.settle("620.proton.abcdef", Lifecycle.ROLLED_BACK, "c" * 64)
        self.assertIs(updated.lifecycle, Lifecycle.ROLLED_BACK)
        self.assertEqual(updated.managed_digest, "c" * 64)
        # The baseline reference survives a lifecycle change.
        self.assertEqual(updated.baseline_payload_name, "00000001.aa.bak")

    def test_resume_only_applies_to_a_stopped_target(self):
        self.store.save(record())
        self.assertIsNone(self.store.resume_managing("620.proton.abcdef"))
        self.store.stop_managing("620.proton.abcdef")
        resumed = self.store.resume_managing("620.proton.abcdef")
        self.assertIs(resumed.lifecycle, Lifecycle.ROLLED_BACK)

    def test_an_unknown_lifecycle_value_is_untrusted(self):
        self.store.save(record())
        path = self.root / "620.proton.abcdef.json"
        value = json.loads(path.read_text())
        value["lifecycle"] = "management.something_else"
        path.write_text(json.dumps(value), encoding="utf-8")
        self.assertIs(self.store.load("620.proton.abcdef").state, ManagementState.UNTRUSTED)

    def test_a_version_one_record_is_untrusted_rather_than_upgraded(self):
        # Guessing a lifecycle for an older record would be exactly the assumed
        # authorship the rest of this module refuses.
        self.store.save(record())
        path = self.root / "620.proton.abcdef.json"
        value = json.loads(path.read_text())
        value["record_version"] = 1
        value.pop("lifecycle")
        value["managing"] = True
        path.write_text(json.dumps(value), encoding="utf-8")
        self.assertIs(self.store.load("620.proton.abcdef").state, ManagementState.UNTRUSTED)

    def test_invalid_identity_is_refused(self):
        for value in ("", "../escape", "a/b", "x" * 200):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.load(value)

    def test_a_symlinked_record_is_not_read(self):
        self.store.save(record())
        target = self.root / "620.proton.abcdef.json"
        link = self.root / "620.proton.linked.json"
        link.symlink_to(target)
        self.assertIs(self.store.load("620.proton.linked").state, ManagementState.UNTRUSTED)

    def test_no_temporary_files_are_left_behind(self):
        self.store.save(record())
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.endswith(".tmp")], [])


if __name__ == "__main__":
    unittest.main()
