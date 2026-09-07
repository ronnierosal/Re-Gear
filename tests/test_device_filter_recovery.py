from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
import unittest
import sys
from unittest.mock import Mock

from backend.hdm.delivery.device_filter_journal import JournalRecord
from backend.hdm.delivery.device_filter_lifecycle import FilterLifecycle, OwnedFilter, Phase, PairedOwnership, PairedReceiveIdentity, PairedStage, DirectCleanupStage
from backend.hdm.delivery.device_filter_kernel import DirectPinAbsent
from backend.hdm.delivery.device_filter_recovery import FilterRecovery
from tests.test_device_filter_journal import binding, JournalFileTests


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.binding = binding()
        self.owner = OwnedFilter(42, "d" * 64, True, True, 43, 1234)
        self.record = JournalRecord(3, FilterLifecycle(self.binding, Phase.ATTACHED, self.owner))
        self.locked = False
        self.events = []
        self.transaction = Mock()
        self.transaction.read.side_effect = lambda *_: self.record
        def change(*args):
            action=args[-1]
            if action in ('direct_detached_verified','direct_cleanup_complete'):
                self.events.append(action)
                self.record=replace(self.record,revision=self.record.revision+1,
                    direct_cleanup=DirectCleanupStage.DETACHED_VERIFIED if action=='direct_detached_verified' else DirectCleanupStage.COMPLETE)
                return self.record
            self.events.append("commit_cancel")
            self.record = JournalRecord(self.record.revision + 1, self.record.lifecycle.after_crash(), paired=self.record.paired)
            return self.record
        self.transaction.change.side_effect = change
        @contextmanager
        def transaction():
            self.locked = True
            try:
                yield self.transaction
            finally:
                self.locked = False
        self.journal = Mock()
        self.journal.transaction = transaction
        self.kernel = Mock()
        self.kernel.__enter__ = Mock(return_value=self.kernel)
        self.kernel.__exit__ = Mock(return_value=False)
        self.directory = Mock(fd=7)
        self.directory.__enter__ = Mock(return_value=self.directory)
        self.directory.__exit__ = Mock(return_value=False)
        self.factory = Mock(return_value=self.kernel)
        self.directory_factory = Mock(return_value=self.directory)
        self.unlink = Mock()
        self.controller = FilterRecovery(self.journal, kernel_factory=self.factory,
            directory_factory=self.directory_factory, unlink=self.unlink)
        for name in ("recover", "detach", "close", "recover_detached"):
            def event(*args, name=name):
                self.assertTrue(self.locked)
                self.assertEqual(self.record.lifecycle.phase, Phase.CANCELLED)
                self.events.append(name)
            getattr(self.kernel, name).side_effect = event
        def unlink(*args, **kwargs):
            self.assertTrue(self.locked)
            self.events.append("unlink")
        self.unlink.side_effect = unlink

    def run_recovery(self, **kwargs):
        return self.controller.recover(self.binding.operation, self.binding.unit,
            current_boot_hash=kwargs.get("boot", self.binding.boot_hash))

    def test_cancel_persisted_before_exact_detach_and_inert_cleanup(self):
        result = self.run_recovery()
        self.assertEqual(result.outcome, "owned_pin_removed")
        self.assertEqual(self.events, ["commit_cancel", "recover", "detach", "close", "recover_detached", "direct_detached_verified", "unlink", "direct_cleanup_complete"])
        self.assertFalse(result.launch_authorized)
        self.assertFalse(result.disconnect_clearance)
        self.assertFalse(self.locked)

    def test_post_grant_recovery_never_opens_or_removes_pin(self):
        for phase in (Phase.GRANTED, Phase.RECOVERY_REQUIRED):
            with self.subTest(phase=phase):
                self.record = replace(self.record, lifecycle=replace(self.record.lifecycle, phase=phase))
                self.assertEqual(self.run_recovery().outcome, "session_recovery_required")
                self.directory_factory.assert_not_called()
                self.unlink.assert_not_called()

    def test_old_boot_does_not_reuse_kernel_identity(self):
        self.assertEqual(self.run_recovery(boot="f" * 64).outcome, "different_boot_unresolved")
        self.transaction.change.assert_not_called()
        self.directory_factory.assert_not_called()
        with self.assertRaises(ValueError):
            self.run_recovery(boot="")

    def test_missing_pin_is_not_release_proof(self):
        self.kernel.recover.side_effect = DirectPinAbsent()
        result = self.run_recovery()
        self.assertEqual(result.outcome, "pin_missing_unverified")
        self.kernel.detach.assert_not_called()
        self.unlink.assert_not_called()
        self.assertFalse(result.disconnect_clearance)

    def test_inert_pin_can_be_cleaned_without_second_detach(self):
        self.kernel.recover.side_effect = ValueError("zero cgroup ID on detached link")
        self.assertEqual(self.run_recovery().outcome, "owned_pin_removed")
        self.kernel.detach.assert_not_called()
        self.assertEqual(self.kernel.recover_detached.call_count,2)

    def test_foreign_or_unreadable_pin_never_removed(self):
        self.kernel.recover.side_effect = RuntimeError("foreign")
        self.kernel.recover_detached.side_effect = RuntimeError("foreign")
        with self.assertRaises(RuntimeError):
            self.run_recovery()
        self.unlink.assert_not_called()
        self.kernel.detach.assert_not_called()
        self.assertFalse(self.locked)

    def test_persistence_failure_prevents_kernel_action(self):
        self.transaction.change.side_effect = OSError("fsync failed")
        with self.assertRaises(OSError):
            self.run_recovery()
        self.directory_factory.assert_not_called()

    def test_detach_or_readback_failure_does_not_unpin(self):
        for name in ("detach", "recover_detached"):
            with self.subTest(name=name):
                self.setUp()
                getattr(self.kernel, name).side_effect = OSError("injected")
                with self.assertRaises(OSError):
                    self.run_recovery()
                self.unlink.assert_not_called()

    def test_pending_owner_recovered_without_persistence_claim(self):
        self.record = replace(self.record, lifecycle=FilterLifecycle(self.binding,
            Phase.PIN_PENDING, replace(self.owner, survives_owner_exit=False)))
        self.assertEqual(self.run_recovery().outcome, "owned_pin_removed")
        self.assertFalse(self.record.lifecycle.owned.survives_owner_exit)

    def test_request_without_owner_never_touches_kernel(self):
        self.record = JournalRecord(1, FilterLifecycle(self.binding))
        self.assertEqual(self.run_recovery().outcome, "cancelled_without_owned_identity")
        self.directory_factory.assert_not_called()

    def test_detach_proof_failure_retains_pin_then_inert_retry(self):
        original=self.transaction.change.side_effect
        def fail(*args):
            if args[-1]=='direct_detached_verified':raise OSError('proof fsync')
            return original(*args)
        self.transaction.change.side_effect=fail
        with self.assertRaises(OSError):self.run_recovery()
        self.unlink.assert_not_called()
        self.assertIsNone(self.record.direct_cleanup)
        self.transaction.change.side_effect=original
        self.kernel.recover.side_effect=ValueError('already inert')
        self.assertEqual(self.run_recovery().outcome,'owned_pin_removed')
        self.assertEqual(self.record.direct_cleanup,DirectCleanupStage.COMPLETE)

    def test_unlinked_pin_complete_commit_failure_retries_from_proof(self):
        original=self.transaction.change.side_effect
        def fail(*args):
            if args[-1]=='direct_cleanup_complete':raise OSError('complete fsync')
            return original(*args)
        self.transaction.change.side_effect=fail
        with self.assertRaises(OSError):self.run_recovery()
        self.assertEqual(self.record.direct_cleanup,DirectCleanupStage.DETACHED_VERIFIED)
        self.unlink.assert_called_once()
        self.transaction.change.side_effect=original
        self.kernel.recover_detached.side_effect=DirectPinAbsent()
        self.kernel.recover.reset_mock();self.unlink.reset_mock()
        self.assertEqual(self.run_recovery().outcome,'owned_pin_removed')
        self.kernel.recover.assert_not_called();self.unlink.assert_not_called()
        self.assertEqual(self.record.direct_cleanup,DirectCleanupStage.COMPLETE)
        self.factory.reset_mock()
        self.assertEqual(self.run_recovery().outcome,'owned_pin_removed')
        self.factory.assert_not_called()

    def test_generic_enoent_and_foreign_inert_identity_never_complete(self):
        self.record=replace(self.record,lifecycle=self.record.lifecycle.cancel(),direct_cleanup=DirectCleanupStage.DETACHED_VERIFIED)
        for error in (FileNotFoundError('metadata'),RuntimeError('foreign')):
            self.kernel.recover_detached.side_effect=error
            with self.assertRaises(type(error)):self.run_recovery()
            self.unlink.assert_not_called()
            self.assertEqual(self.record.direct_cleanup,DirectCleanupStage.DETACHED_VERIFIED)

    def test_close_failure_does_not_commit_complete(self):
        self.kernel.__exit__.side_effect=FileNotFoundError('close')
        with self.assertRaises(FileNotFoundError):self.run_recovery()
        self.assertNotEqual(self.record.direct_cleanup,DirectCleanupStage.COMPLETE)


    def paired_controller(self):
        self.record = replace(self.record, paired=PairedOwnership(70,
            PairedStage.RECEIVE_CONFIRMED, PairedReceiveIdentity(71, 72, 73, 74)))
        self.paired_recovery = Mock()
        self.controller.receive_recovery = self.paired_recovery
        def complete(*args, **kwargs):
            self.assertTrue(self.locked)
            self.assertEqual(self.record.lifecycle.phase, Phase.CANCELLED)
            self.events.append("paired_complete")
            self.record = replace(self.record, revision=self.record.revision + 1,
                paired=replace(self.record.paired, stage=PairedStage.COMPLETE))
            return SimpleNamespace(completed=True, outcome="paired_removed", revision=self.record.revision)
        self.paired_recovery.recover.side_effect = complete

    def test_paired_cleanup_precedes_existing_device_cleanup_under_lock(self):
        self.paired_controller()
        result = self.run_recovery()
        self.assertEqual(result.outcome, "owned_pin_removed")
        self.assertLess(self.events.index("paired_complete"), self.events.index("detach"))
        self.assertFalse(self.paired_recovery.recover.call_args.kwargs["prior_owner_quiesced"])

    def test_unresolved_pair_preserves_device_filter(self):
        self.paired_controller()
        self.paired_recovery.recover.side_effect = None
        self.paired_recovery.recover.return_value = SimpleNamespace(
            completed=False, outcome="receive_still_present", revision=4)
        self.assertEqual(self.run_recovery().outcome, "receive_still_present")
        self.factory.assert_not_called()
        self.unlink.assert_not_called()

    def test_pair_completion_requires_durable_complete_record(self):
        self.paired_controller()
        self.paired_recovery.recover.side_effect = None
        self.paired_recovery.recover.return_value = SimpleNamespace(completed=True)
        with self.assertRaises(ValueError): self.run_recovery()
        self.factory.assert_not_called()

    def test_postgrant_pair_and_wrong_boot_never_call_pair_coordinator(self):
        self.paired_controller()
        self.assertEqual(self.run_recovery(boot="f"*64).outcome, "different_boot_unresolved")
        with self.assertRaises(ValueError):
            replace(self.record, lifecycle=replace(self.record.lifecycle, phase=Phase.GRANTED))
        self.paired_recovery.recover.assert_not_called()
        self.factory.assert_not_called()


@unittest.skipUnless(sys.platform == "linux", "requires Linux dirfd/flock semantics")
class RecoveryJournalTests(unittest.TestCase):
    setUp = JournalFileTests.setUp
    instance = JournalFileTests.instance
    args = JournalFileTests.args
    attach = JournalFileTests.attach
    # Exercise recovery against real durable storage and only fake the kernel.
    def test_recovery_reload_preserves_postgrant_filter(self):
        from backend.hdm.delivery.device_filter_recovery import FilterRecovery
        attached = self.attach()
        granted = self.journal.grant(*self.args(), attached.revision,
            observed=self.binding, now=2, no_game=True,
            inherited_scan_complete=True, inherited_descriptors_free=True)
        directory = Mock()
        result = FilterRecovery(self.instance(), directory_factory=directory).recover(
            *self.args(), current_boot_hash=self.binding.boot_hash)
        self.assertEqual(result.outcome, "session_recovery_required")
        loaded = self.instance().read(*self.args())
        self.assertEqual(loaded.lifecycle.phase, Phase.RECOVERY_REQUIRED)
        self.assertEqual(loaded.revision, granted.revision + 1)
        self.assertFalse(loaded.delivery_granted)
        directory.assert_not_called()

    def test_cleanup_failure_leaves_durable_cancelled_owner(self):
        from backend.hdm.delivery.device_filter_recovery import FilterRecovery
        attached = self.attach()
        def unavailable():
            raise OSError("bpffs unavailable")
        with self.assertRaises(OSError):
            FilterRecovery(self.instance(), directory_factory=unavailable).recover(
                *self.args(), current_boot_hash=self.binding.boot_hash)
        loaded = self.instance().read(*self.args())
        self.assertEqual(loaded.lifecycle.phase, Phase.CANCELLED)
        self.assertEqual(loaded.lifecycle.owned, self.owner)
        self.assertEqual(loaded.revision, attached.revision + 1)

del JournalFileTests
