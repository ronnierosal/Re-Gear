"""Cross-process admission without blocking or implicit claim clearing."""
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from regear.delivery.dock_mutation_gate import DockMutationGate, DockMutationDenied, LOCK_FILENAME
from regear.delivery.whole_dock_claim import WholeDockClaimStore, FILENAME


def attempt(path, result):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        gate = DockMutationGate(path, owner_uid=os.geteuid(), trusted_directory_fd=descriptor)
        try:
            with gate.admit():
                result.put("admitted")
        except DockMutationDenied:
            result.put("denied")
    finally:
        os.close(descriptor)


@unittest.skipUnless(sys.platform == "linux", "Linux locking required")
class DockMutationGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        self.options = dict(owner_uid=os.geteuid(), trusted_directory_fd=self.fd)
        self.gate = DockMutationGate(self.root, **self.options)
        self.claims = WholeDockClaimStore(self.root, **self.options)

    def tearDown(self):
        os.close(self.fd)
        self.temp.cleanup()

    def test_instances_and_nested_entry_fail_immediately(self):
        with self.gate.admit():
            with self.assertRaises(DockMutationDenied):
                with DockMutationGate(self.root, **self.options).admit():
                    self.fail("concurrent admission")
            with self.assertRaises(DockMutationDenied):
                with self.gate.admit(allow_inhibited=True):
                    self.fail("nested admission")
        with self.gate.admit():
            pass

    def test_other_process_excluded_until_release(self):
        ctx = multiprocessing.get_context("spawn")
        queue = ctx.Queue()
        with self.gate.admit():
            child = ctx.Process(target=attempt, args=(str(self.root), queue))
            child.start()
            child.join(10)
            self.assertEqual(child.exitcode, 0)
            self.assertEqual(queue.get(timeout=2), "denied")
        child = ctx.Process(target=attempt, args=(str(self.root), queue))
        child.start()
        child.join(10)
        self.assertEqual(child.exitcode, 0)
        self.assertEqual(queue.get(timeout=2), "admitted")
        queue.close()

    def test_teardown_claim_blocks_next_ordinary_mutation(self):
        with self.gate.admit():
            self.assertTrue(self.claims.claim("operation", "attachment", "generation"))
        with self.assertRaises(DockMutationDenied):
            with self.gate.admit():
                self.fail("inhibited")
        with self.gate.admit(allow_inhibited=True):
            self.claims.record("operation", "prepared")
        self.assertTrue(self.claims.inhibited())

    def test_corrupt_claim_denied(self):
        target = self.root / FILENAME
        target.write_text("corrupt")
        target.chmod(0o600)
        with self.assertRaises(DockMutationDenied):
            with self.gate.admit():
                self.fail("corrupt claim must inhibit")

    def test_claim_writer_lock_denied_without_wait(self):
        import fcntl
        descriptor = os.open(self.root / "whole-dock-claim.lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(DockMutationDenied):
                with self.gate.admit():
                    self.fail("claim writer must inhibit")
        finally:
            os.close(descriptor)

    def test_symlink_lock_and_claim_refused(self):
        outside = self.root / "outside"
        outside.write_text("unchanged")
        for name in (LOCK_FILENAME, FILENAME, "whole-dock-claim.lock"):
            target = self.root / name
            target.unlink(missing_ok=True)
            target.symlink_to(outside)
            with self.assertRaises(DockMutationDenied):
                with self.gate.admit():
                    self.fail("symlink allowed")
            target.unlink()
        self.assertEqual(outside.read_text(), "unchanged")

    def test_body_error_propagates_and_releases(self):
        with self.assertRaisesRegex(ValueError, "body failure"):
            with self.gate.admit():
                raise ValueError("body failure")
        with self.gate.admit():
            pass

    def test_non_boolean_override_refused(self):
        for value in (1, "true", None):
            with self.assertRaises(DockMutationDenied):
                with self.gate.admit(allow_inhibited=value):
                    self.fail("invalid override")


if __name__ == "__main__":
    unittest.main()
