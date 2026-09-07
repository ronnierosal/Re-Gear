from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
import stat
import os
import sys
import tempfile
import unittest

from backend.hdm.delivery.device_filter_attachment import AttachmentObservation, FilterAttachmentController
from backend.hdm.delivery.device_filter_journal import JournalRecord
from backend.hdm.delivery.device_filter_kernel import LinkIdentity
from backend.hdm.delivery.device_filter_lifecycle import FilterLifecycle, LaunchBinding, Phase


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.binding = LaunchBinding("a" * 64, "op", "gamescope-session.service",
            "b" * 32, 1000, 50, 100, 29, 1234, "c" * 64, 30)
        self.observation = AttachmentObservation(self.binding, ((226, 128),), True, True)
        self.record = JournalRecord(1, FilterLifecycle(self.binding))
        self.events = []
        self.fail = None
        self.attached = False
        self.identity = LinkIdentity(43, 42, 900)
        self.observations = 0
        self.stale_at = None
        test = self

        class Journal:
            @contextmanager
            def transaction(self):
                test.events.append("lock")
                try:
                    yield self
                finally:
                    test.events.append("unlock")

            def read(self, *_):
                return test.record

            def change(self, op, unit, revision, action, **kwargs):
                test.assertEqual(revision, test.record.revision)
                test.events.append(action)
                if test.fail == action:
                    raise OSError("write failed")
                state = getattr(test.record.lifecycle, "after_crash" if action == "recover" else action)(**kwargs)
                test.record = JournalRecord(revision + 1, state,
                    action == "grant" and state.phase is Phase.GRANTED)
                if test.fail == action + "_published":
                    raise OSError("directory sync failed")
                return test.record

        class Pins:
            fd = 8
            def __enter__(self):
                return self
            def __exit__(self, *_):
                test.events.append("pins_close")

        class Kernel:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                test.events.append("kernel_close")
            def query_program_ids(self, fd):
                return (7, 42) if test.attached else (7,)
            def load(self, code):
                test.events.append("load")
            def program_id(self):
                return 42
            def attach(self, fd):
                test.events.append("kernel_attach")
                test.attached = True
            def link_identity(self):
                return test.identity
            def pin(self, *args):
                test.events.append("pin")
                if test.fail == "pin":
                    raise OSError("pin exists")
            def recover(self, *args):
                test.events.append("readback")
                if test.fail == "readback":
                    raise OSError("readback failed")

        def observe():
            self.observations += 1
            if self.observations == self.stale_at:
                return replace(self.observation, no_game=False)
            return self.observation

        self.controller = FilterAttachmentController(Journal(), observe,
            kernel_factory=Kernel, pin_factory=Pins, clock=lambda: 10,
            fstat=lambda fd: SimpleNamespace(st_mode=stat.S_IFDIR, st_dev=29, st_ino=1234))

    def run_attach(self):
        return self.controller.attach("op", self.binding.unit, 9)

    def test_durable_pending_precedes_pin_and_readback_precedes_confirmation(self):
        result = self.run_attach()
        self.assertEqual(result.lifecycle.phase, Phase.ATTACHED)
        self.assertFalse(result.delivery_granted)
        self.assertTrue(result.lifecycle.owned.survives_owner_exit)
        self.assertEqual(self.events, ["lock", "load", "kernel_attach", "prepare_pin", "pin",
            "readback", "kernel_close", "attach", "kernel_close", "pins_close", "unlock"])

    def test_failures_at_durable_boundaries_cancel_without_unpin(self):
        for failure in ("prepare_pin", "prepare_pin_published", "pin", "readback",
                        "attach", "attach_published"):
            self.setUp()
            self.fail = failure
            with self.subTest(failure=failure), self.assertRaises(OSError):
                self.run_attach()
            self.assertEqual(self.record.lifecycle.phase, Phase.CANCELLED)
            self.assertEqual(self.events[-1], "unlock")
            self.assertIn("kernel_close", self.events)
            self.assertNotIn("grant", self.events)
            if failure == "prepare_pin":
                self.assertNotIn("pin", self.events)

    def test_stale_observation_at_every_checkpoint_cancels(self):
        for checkpoint in range(1, 5):
            self.setUp()
            self.stale_at = checkpoint
            with self.subTest(checkpoint=checkpoint), self.assertRaises(ValueError):
                self.run_attach()
            self.assertEqual(self.record.lifecycle.phase, Phase.CANCELLED)

    def test_initial_game_wrapper_binding_and_fd_fail_before_kernel(self):
        for changes in ({"no_game": False}, {"no_game": 1}, {"waiting_wrapper_verified": False},
                        {"binding": replace(self.binding, invocation="d" * 32)},
                        {"denied_devices": ()}):
            self.setUp()
            self.observation = replace(self.observation, **changes)
            with self.assertRaises(ValueError):
                self.run_attach()
            self.assertNotIn("load", self.events)
        self.setUp()
        self.controller.fstat = lambda fd: SimpleNamespace(st_mode=stat.S_IFDIR, st_dev=29, st_ino=99)
        with self.assertRaises(ValueError):
            self.run_attach()
        self.assertNotIn("load", self.events)

    def test_wrong_kernel_owner_never_pins(self):
        for identity in (LinkIdentity(43, 99, 900),):
            self.setUp()
            self.identity = identity
            with self.assertRaises(ValueError):
                self.run_attach()
            self.assertNotIn("pin", self.events)

    def test_replay_does_not_cancel_completed_attachment(self):
        self.run_attach()
        before = self.record
        with self.assertRaises(ValueError):
            self.run_attach()
        self.assertEqual(self.record, before)

    @unittest.skipUnless(sys.platform == "linux", "requires real journal dirfd semantics")
    def test_attachment_persists_through_real_journal_reload(self):
        from backend.hdm.delivery.device_filter_journal import FilterJournal
        with tempfile.TemporaryDirectory() as root:
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                info = os.fstat(fd)
                self.binding = replace(self.binding, cgroup_dev=info.st_dev, cgroup_inode=info.st_ino)
                self.observation = replace(self.observation, binding=self.binding)
                journal = FilterJournal(owner_uid=os.geteuid(), trusted_directory_fd=fd)
                journal.create(self.binding)
                self.controller.journal = journal
                self.controller.fstat = os.fstat
                result = self.controller.attach("op", self.binding.unit, fd)
                loaded = journal.read("op", self.binding.unit)
                self.assertEqual(loaded.lifecycle, result.lifecycle)
                self.assertEqual(loaded.revision, 3)
                self.assertFalse(loaded.delivery_granted)
                self.assertEqual(loaded.lifecycle.owned.kernel_cgroup_id, 900)
            finally:
                os.close(fd)

    def test_expired_request_fails_before_kernel(self):
        self.controller.clock = lambda: 30
        with self.assertRaises(ValueError):
            self.run_attach()
        self.assertNotIn("load", self.events)


if __name__ == "__main__":
    unittest.main()
