"""Actual new filesystem journals must remain readable by frozen173 decoder."""
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from tests import test_presentation_boot_retirement as boot_fixture
from tests.fixtures.legacy_transition_journal_reader import journal_from_dict as legacy_reader
from tests.test_presentation_completion import committed
from regear.delivery.transition_journal_store import FileTransitionJournalStore


class RollbackCompatibilityTests(unittest.TestCase):
    def test_actual_retained_result_is_readable_by_frozen_rollback_decoder(self):
        harness = boot_fixture.BootRetirementCompositionTests()
        harness.setUp()
        self.addCleanup(harness.doCleanups)
        result = harness.create_retained()
        value = json.loads((harness.root / "active-transition.json").read_text())
        rolled_back = legacy_reader(value)
        self.assertEqual(rolled_back.operation_id, result.operation_id)
        self.assertEqual(rolled_back.entries, result.entries)
        self.assertEqual(rolled_back.origin_boot_id, "")
        # This final check uses the new service. It is not a certification of
        # an installed old-runtime rollback or its main.py composition.
        self.assertTrue(harness.service().acknowledge(rolled_back.operation_id))
        self.assertIsNone(harness.store.load_current())

    def test_completed_receipt_remains_readable_to_strict_rollback_decoder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            store = FileTransitionJournalStore(root)
            receipt = replace(committed(), origin_boot_id=boot_fixture.OLD_BOOT)
            store.save(receipt)
            store.retire_committed(receipt.operation_id)
            raw = json.loads((root / "completed-presentation.json").read_text())
            legacy = legacy_reader(raw)
            self.assertEqual(legacy.entries, receipt.entries)
            self.assertEqual(legacy.operation_id, receipt.operation_id)

    def test_legacy_journal_without_sidecar_does_not_gain_boot_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            store = FileTransitionJournalStore(Path(directory).resolve())
            journal = committed()
            store.save(journal)
            self.assertEqual(store.load_current().origin_boot_id, "")

    def test_foreign_sidecar_does_not_retrofit_legacy_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            store = FileTransitionJournalStore(root)
            journal = committed()
            store.save(journal)
            (root / "presentation-origin-boot.json").write_text(json.dumps({
                "schema_version": 1, "operation_id": "foreign-operation", "request_id": journal.request_id,
                "started_at": journal.entries[0].occurred_at, "origin_boot_id": boot_fixture.OLD_BOOT}))
            self.assertEqual(store.load_current().origin_boot_id, "")

    def test_origin_publication_failure_prevents_active_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            store = FileTransitionJournalStore(root)
            with patch.object(store, "_replace", side_effect=OSError("origin publication failure")):
                with self.assertRaises(OSError):
                    store.save(replace(committed(), origin_boot_id=boot_fixture.OLD_BOOT))
            self.assertFalse((root / "active-transition.json").exists())

    def test_sidecar_identity_binds_request_and_first_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            store = FileTransitionJournalStore(root)
            journal = replace(committed(), origin_boot_id=boot_fixture.OLD_BOOT)
            store.save(journal)
            raw = json.loads((root / "presentation-origin-boot.json").read_text())
            for key in ("request_id", "started_at"):
                changed = dict(raw)
                changed[key] = "different"
                (root / "presentation-origin-boot.json").write_text(json.dumps(changed))
                self.assertEqual(store.load_current().origin_boot_id, "")


if __name__ == "__main__":
    unittest.main()
