from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.delivery.transition_journal_store import (  # noqa: E402
    JOURNAL_FILENAME,
    COMPLETED_FILENAME,
    MAX_JOURNAL_BYTES,
    FileTransitionJournalStore,
)
from regear.domain.control_plane import PlacementState, WorkflowState  # noqa: E402
from regear.domain.transition_journal import (  # noqa: E402
    JournalEventKind,
    TransitionJournal,
    append_journal_entry,
)


def append(journal, kind, code):
    return append_journal_entry(
        journal,
        kind=kind,
        occurred_at="2026-08-31T12:00:00Z",
        workflow_state=(
            WorkflowState.IDLE
            if kind is JournalEventKind.COMMITTED
            else WorkflowState.CONNECTING
        ),
        placement=PlacementState.PORTABLE,
        code=code,
    )


def requested(operation="operation-1"):
    return append(
        TransitionJournal(operation, "request-1"),
        JournalEventKind.REQUESTED,
        "request.accepted",
    )


def committed(operation="operation-1"):
    journal = requested(operation)
    journal = append(journal, JournalEventKind.OBSERVED, "snapshot.observed")
    journal = append(journal, JournalEventKind.VALIDATED, "plan.validated")
    journal = append(journal, JournalEventKind.PLANNED, "plan.ready")
    return append(journal, JournalEventKind.COMMITTED, "transition.committed")


def presentation(operation="operation-1", target=PlacementState.PORTABLE):
    journal = committed(operation)
    first = replace(journal.entries[0], details=(
        ("capability", "presentation_transition"),
        ("target_placement", target.value),
    ))
    last = replace(journal.entries[-1], placement=target)
    return replace(journal, entries=(first, *journal.entries[1:-1], last))


class TransitionJournalStoreTests(unittest.TestCase):
    def test_receipt_roundtrip_latest_only_and_exact_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory)
            for operation, target in (("one", PlacementState.PORTABLE), ("two", PlacementState.DOCKED_EGPU)):
                journal = presentation(operation, target)
                store.save(journal)
                with self.assertRaisesRegex(ValueError, "does not match"):
                    store.retire_committed("wrong")
                store.retire_committed(operation)
                store.retire_committed(operation)
                self.assertIsNone(store.load_current())
                self.assertEqual(self.store(directory).load_completed(), journal)
                self.assertEqual([p.name for p in Path(directory).iterdir()], [COMPLETED_FILENAME])
            with self.assertRaisesRegex(ValueError, "does not match"):
                store.clear_completed("one")
            store.clear_completed("two")
            self.assertIsNone(store.load_completed())

    def test_receipt_rejects_incomplete_failed_recovered_foreign_and_bad_target(self):
        valid = presentation()
        recovering = append(replace(valid, entries=valid.entries[:-1]), JournalEventKind.RECOVERY_STARTED, "recovery.started")
        bad_target = replace(valid.entries[0], details=(("capability", "presentation_transition"), ("target_placement", "Unknown")))
        cases = (
            replace(valid, entries=(replace(valid.entries[0], code="sleep.requested"), *valid.entries[1:])),
            replace(valid, entries=(*valid.entries[:-1], replace(valid.entries[-1], code="unexpected.committed"))),
            requested(),
            append(requested(), JournalEventKind.FAILED, "transition.failed"),
            append(recovering, JournalEventKind.RECOVERY_VERIFIED, "recovery.verified"),
            committed(),
            replace(valid, entries=(bad_target, *valid.entries[1:])),
            replace(valid, entries=(*valid.entries[:-1], replace(valid.entries[-1], placement=PlacementState.DOCKED_EGPU))),
        )
        for journal in cases:
            with self.subTest(journal=journal), tempfile.TemporaryDirectory() as directory:
                store = self.store(directory)
                store.save(journal)
                with self.assertRaises(ValueError):
                    store.retire_committed(journal.operation_id)
                self.assertEqual(store.load_current(), journal)
                self.assertIsNone(store.load_completed())

    def test_archive_replace_failure_preserves_active(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = presentation()
            self.store(directory).save(journal)
            def fail_replace(_source, _target):
                raise OSError("archive failed")
            store = self.store(directory, replace=fail_replace)
            with self.assertRaisesRegex(OSError, "archive failed"):
                store.retire_committed(journal.operation_id)
            self.assertEqual(store.load_current(), journal)
            self.assertIsNone(store.load_completed())

    def test_duplicate_after_archive_before_clear_is_retryable(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = presentation()
            store = self.store(directory)
            store.save(journal)
            with patch.object(Path, "unlink", side_effect=OSError("crash before clear")):
                with self.assertRaisesRegex(OSError, "crash"):
                    store.retire_committed(journal.operation_id)
            self.assertEqual(store.load_current(), journal)
            self.assertEqual(store.load_completed(), journal)
            store.retire_committed(journal.operation_id)
            self.assertIsNone(store.load_current())
            self.assertEqual(store.load_completed(), journal)

    def test_archive_fsync_failure_preserves_active(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = presentation()
            store = self.store(directory)
            store.save(journal)
            with patch("regear.delivery.transition_journal_store.os.fsync", side_effect=OSError("fsync failed")):
                with self.assertRaisesRegex(OSError, "fsync failed"):
                    store.retire_committed(journal.operation_id)
            self.assertEqual(store.load_current(), journal)
            self.assertIsNone(store.load_completed())
            self.assertEqual([p.name for p in Path(directory).iterdir()], [JOURNAL_FILENAME])

    def test_archive_directory_sync_failure_preserves_duplicate_for_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = presentation()
            store = self.store(directory)
            store.save(journal)
            with patch.object(store, "_sync_directory", side_effect=OSError("directory sync failed")):
                with self.assertRaisesRegex(OSError, "directory sync failed"):
                    store.retire_committed(journal.operation_id)
            self.assertEqual(store.load_current(), journal)
            self.assertEqual(store.load_completed(), journal)
            store.retire_committed(journal.operation_id)
            self.assertIsNone(store.load_current())

    def test_completed_loading_enforces_byte_bound_and_committed_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory)
            store.save(committed())
            path = Path(directory) / COMPLETED_FILENAME
            path.write_bytes((Path(directory) / JOURNAL_FILENAME).read_bytes())
            for action in (store.load_completed, lambda: store.clear_completed("operation-1")):
                with self.assertRaises(ValueError):
                    action()
            path.write_bytes(b" " * (MAX_JOURNAL_BYTES + 1))
            with self.assertRaisesRegex(ValueError, "byte bound"):
                store.load_completed()

    def test_completed_symlink_is_rejected_without_clearing_active(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory)
            journal = presentation()
            store.save(journal)
            try:
                (Path(directory) / COMPLETED_FILENAME).symlink_to(Path(directory) / JOURNAL_FILENAME)
            except OSError:
                self.skipTest("file symlinks are unavailable on this host")
            for action in (store.load_completed, lambda: store.clear_completed(journal.operation_id), lambda: store.retire_committed(journal.operation_id)):
                with self.assertRaisesRegex(ValueError, "symlink"):
                    action()
            self.assertEqual(store.load_current(), journal)

    def store(self, root, replace=None, tokens=None):
        kwargs = {
            "token_factory": lambda: next(iter(tokens or ["temporary1"])),
        }
        if replace is not None:
            kwargs["replace"] = replace
        return FileTransitionJournalStore(Path(root).resolve(), **kwargs)

    def test_save_load_append_and_idempotent_save(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory, tokens=["temporary1"])
            first = requested()
            store.save(first)
            self.assertEqual(store.load_current(), first)
            second = append(first, JournalEventKind.OBSERVED, "snapshot.observed")
            store = self.store(directory, tokens=["temporary2"])
            store.save(second)
            store.save(second)
            self.assertEqual(store.load_current(), second)

    def test_different_regressed_or_divergent_history_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory)
            first = requested()
            observed = append(first, JournalEventKind.OBSERVED, "snapshot.observed")
            store.save(observed)
            cases = (
                requested("operation-2"),
                first,
                append(first, JournalEventKind.BLOCKED, "transition.blocked"),
            )
            for replacement in cases:
                with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                    store.save(replacement)
            self.assertEqual(store.load_current(), observed)

    def test_replace_failure_preserves_prior_journal_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            initial_store = self.store(directory, tokens=["temporary1"])
            first = requested()
            initial_store.save(first)

            def fail_replace(_source, _target):
                raise OSError("injected replace failure")

            store = self.store(
                directory, replace=fail_replace, tokens=["temporary2"]
            )
            second = append(first, JournalEventKind.OBSERVED, "snapshot.observed")
            with self.assertRaisesRegex(OSError, "injected"):
                store.save(second)
            self.assertEqual(initial_store.load_current(), first)
            self.assertEqual(
                [path.name for path in Path(directory).iterdir()], [JOURNAL_FILENAME]
            )

    def test_only_matching_terminal_operation_can_be_cleared(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory)
            store.save(committed())
            with self.assertRaisesRegex(ValueError, "does not match"):
                store.clear_terminal("different-operation")
            store.clear_terminal("operation-1")
            self.assertIsNone(store.load_current())

            store = self.store(directory, tokens=["temporary2"])
            store.save(requested())
            with self.assertRaisesRegex(ValueError, "incomplete"):
                store.clear_terminal("operation-1")

    def test_corrupt_or_unknown_schema_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / JOURNAL_FILENAME
            for value in (b"not-json", json.dumps({"schema_version": 99}).encode()):
                path.write_bytes(value)
                with self.subTest(value=value), self.assertRaises(ValueError):
                    self.store(directory).load_current()

    def test_relative_or_symlink_root_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "absolute"):
            FileTransitionJournalStore(Path("relative"))
        with tempfile.TemporaryDirectory() as directory:
            real = Path(directory) / "real"
            link = Path(directory) / "link"
            real.mkdir()
            try:
                link.symlink_to(real, target_is_directory=True)
            except OSError:
                self.skipTest("directory symlinks are unavailable on this host")
            with self.assertRaisesRegex(ValueError, "real directory"):
                FileTransitionJournalStore(link.absolute()).load_current()




class HandoffJournalBindingTests(unittest.TestCase):
    def test_binding_is_strict_versioned_and_distinguishes_each_identity(self):
        from regear.delivery.transition_journal_store import handoff_operation_id
        boot="11111111-1111-1111-1111-111111111111"
        first=handoff_operation_id("fixture-request",boot,"a"*64)
        self.assertEqual(first,handoff_operation_id("fixture-request",boot,"a"*64))
        self.assertEqual(len(first),64)  # Existing supervised acknowledgement bound.
        for fields in (("other",boot,"a"*64),("fixture-request",boot,"b"*64),
                       ("fixture-request","22222222-2222-2222-2222-222222222222","a"*64)):
            self.assertNotEqual(first,handoff_operation_id(*fields))
        for fields in ((True,boot,"a"*64),("request","unknown","a"*64),("request",boot,"bad")):
            with self.assertRaises(ValueError):handoff_operation_id(*fields)


@unittest.skipUnless(sys.platform=="linux","Linux descriptor-relative admission required")
class AdmittedHandoffJournalTests(unittest.TestCase):
    def setUp(self):
        import os
        from regear.delivery.dock_mutation_gate import DockMutationGate
        from regear.delivery.transition_journal_store import handoff_operation_id
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY)
        self.options=dict(owner_uid=os.geteuid(),trusted_directory_fd=self.fd)
        self.gate=DockMutationGate(self.root,**self.options)
        self.store=FileTransitionJournalStore(self.root)
        self.generation="a"*64;self.boot="11111111-1111-1111-1111-111111111111"
        self.journal=append(TransitionJournal(handoff_operation_id("fixture-request",self.boot,self.generation),
            "fixture-request",origin_boot_id=self.boot),JournalEventKind.REQUESTED,"request.accepted")

    def tearDown(self):
        import os
        os.close(self.fd);self.temp.cleanup()

    def persist(self,admission,journal=None,generation=None):
        return self.store.persist_admitted(journal or self.journal,admission=admission,
            generation=generation or self.generation)

    def test_exact_readback_progression_and_lease_expiry(self):
        with self.gate.admit() as lease:
            evidence=self.persist(lease)
            self.assertTrue(evidence.is_current())
            updated=append(self.journal,JournalEventKind.OBSERVED,"snapshot.observed")
            later=self.persist(lease,updated)
            self.assertFalse(evidence.is_current())
            self.assertTrue(later.is_current())
        self.assertFalse(later.is_current())
        with self.assertRaises(Exception):self.persist(lease)

    def test_invalid_generation_request_boot_and_inhibited_admission_refuse(self):
        with self.gate.admit() as lease:
            for journal,generation in ((self.journal,"b"*64),
                (replace(self.journal,request_id="other"),self.generation),
                (replace(self.journal,origin_boot_id="22222222-2222-2222-2222-222222222222"),self.generation)):
                with self.assertRaises(ValueError):self.persist(lease,journal,generation)
        with self.gate.admit(allow_inhibited=True) as lease:
            self.assertIsNone(lease)
            with self.assertRaises(ValueError):self.persist(lease)
        self.assertIsNone(self.store.load_current())

    def test_file_fsync_failure_before_intent_has_no_fabricated_inhibition(self):
        with self.gate.admit() as lease:
            with patch("regear.delivery.transition_journal_store.os.fsync",side_effect=OSError("fixture")):
                with self.assertRaises(OSError):self.persist(lease)
        self.assertIsNone(self.store.load_current())

    def test_partial_origin_persistence_refuses_retry_without_reconciliation(self):
        import os
        original=os.replace;calls=[]
        def fail_second(*args,**kwargs):
            calls.append(args)
            if len(calls)==2:raise OSError("fixture second publication")
            return original(*args,**kwargs)
        with self.gate.admit() as lease:
            with patch("regear.delivery.transition_journal_store.os.replace",side_effect=fail_second):
                with self.assertRaises(OSError):self.persist(lease)
            with self.assertRaisesRegex(ValueError,"orphan"):self.persist(lease)
        self.assertIsNone(self.store.load_current())
        self.assertTrue((self.root/"presentation-origin-boot.json").exists())

    def test_root_replacement_and_competing_admission_refuse(self):
        from regear.delivery.dock_mutation_gate import DockMutationGate,DockMutationDenied
        moved=self.root.with_name(self.root.name+"-moved")
        with self.gate.admit() as lease:
            with self.assertRaises(DockMutationDenied):
                with DockMutationGate(self.root,**self.options).admit():pass
            self.root.rename(moved)
            try:
                self.root.mkdir(mode=0o700)
                with self.assertRaises(DockMutationDenied):self.persist(lease)
            finally:
                self.root.rmdir();moved.rename(self.root)

    def test_unsafe_symlink_target_and_sidecar_mismatch_refuse(self):
        with self.gate.admit() as lease:
            (self.root/JOURNAL_FILENAME).symlink_to("missing-fixture")
            with self.assertRaises(OSError):self.persist(lease)
            (self.root/JOURNAL_FILENAME).unlink()
            self.persist(lease)
            side=self.root/"presentation-origin-boot.json"
            payload=json.loads(side.read_text());payload["request_id"]="other"
            side.write_text(json.dumps(payload))
            with self.assertRaises(ValueError):self.persist(lease)

    def test_readback_mismatch_and_directory_fsync_failure_return_no_evidence(self):
        from regear.delivery.transition_journal_store import _PinnedJournal
        original=_PinnedJournal.load_current;calls=[]
        def changed(store):
            value=original(store);calls.append(True)
            return None if len(calls)>=3 else value
        with self.gate.admit() as lease:
            with patch.object(_PinnedJournal,"load_current",changed):
                with self.assertRaisesRegex(ValueError,"readback"):self.persist(lease)
        self.assertEqual(self.store.load_current(),self.journal)
        with self.gate.admit() as lease:
            with patch("regear.delivery.transition_journal_store.os.fsync",side_effect=OSError("fixture")):
                with self.assertRaises(OSError):self.persist(lease)

if __name__ == "__main__":
    unittest.main()
