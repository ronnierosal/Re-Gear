"""Linux filesystem tests for durable whole-dock admission and inhibition."""
import json
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from regear.delivery.whole_dock_claim import FILENAME, WholeDockClaim, WholeDockClaimStore


class WholeDockClaimValueTests(unittest.TestCase):
    def test_unbounded_or_non_categorical_identity_refused(self):
        for identity in ("", "x" * 257, "a/b", "a\n", 1, None):
            with self.assertRaises(ValueError):
                WholeDockClaim("operation", identity, "generation")

    def test_unknown_stage_refused(self):
        with self.assertRaises(ValueError):
            WholeDockClaim("operation", "binding", "generation", "safe_to_unplug")

    def test_duplicate_json_fields_refused(self):
        with self.assertRaises(ValueError):
            json.loads('{"operation":"a","operation":"b"}',
                       object_pairs_hook=WholeDockClaimStore._pairs)


def compete(path, output):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        store = WholeDockClaimStore(path, owner_uid=os.geteuid(), trusted_directory_fd=fd)
        output.put(store.claim(str(os.getpid()), "attachment", "generation"))
    finally:
        os.close(fd)


@unittest.skipUnless(sys.platform == "linux", "Linux descriptor-relative filesystem required")
class WholeDockClaimTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        self.store = self.make_store()

    def make_store(self):
        return WholeDockClaimStore(self.root, owner_uid=os.geteuid(), trusted_directory_fd=self.fd)

    def tearDown(self):
        os.close(self.fd)
        self.temp.cleanup()

    def test_independent_instances_reject_same_and_different_operation(self):
        self.assertFalse(self.store.inhibited())
        self.assertTrue(self.store.claim("one", "dock", "generation"))
        self.assertFalse(self.make_store().claim("one", "dock", "generation"))
        self.assertFalse(self.make_store().claim("two", "dock", "generation"))
        self.store.record("one", "prepared")
        self.store.record("one", "software_down")
        result = self.make_store().load()
        self.assertEqual((result.operation, result.binding, result.generation), ("one", "dock", "generation"))
        self.assertTrue(self.make_store().inhibited())
        with self.assertRaises(ValueError):
            self.store.record("two", "software_down")
        with self.assertRaises(ValueError):
            self.store.record("one", "prepared")

    def test_competing_processes_only_one_claim(self):
        ctx = multiprocessing.get_context("spawn")
        queue = ctx.Queue()
        children = [ctx.Process(target=compete, args=(str(self.root), queue)) for _ in range(4)]
        for child in children:
            child.start()
        for child in children:
            child.join(10)
            self.assertEqual(child.exitcode, 0)
        self.assertEqual(sum(queue.get(timeout=2) for _ in children), 1)
        queue.close()

    def test_release_progress_cannot_regress_before_teardown(self):
        self.assertTrue(self.store.claim("one", "dock", "generation"))
        self.store.record("one", "release_intent")
        self.store.record("one", "gpu_removed")
        with self.assertRaises(ValueError):
            self.store.record("one", "release_intent")
        self.store.record("one", "prepared")
        self.assertEqual(self.store.load().stage, "prepared")
        self.assertTrue(self.store.inhibited())

    def test_claim_directory_fsync_failure_retains_inhibit(self):
        fsync = os.fsync
        def fail_directory(fd):
            import stat
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("directory fsync failed")
            return fsync(fd)
        with patch("os.fsync", side_effect=fail_directory):
            with self.assertRaises(OSError):
                self.store.claim("one", "dock", "generation")
        self.assertTrue(self.make_store().inhibited())
        self.assertFalse(self.make_store().claim("two", "dock", "generation"))

    def test_partial_write_failure_retains_corrupt_blocking_claim(self):
        with patch("os.write", side_effect=OSError("write failed")):
            with self.assertRaises(OSError):
                self.store.claim("one", "dock", "generation")
        self.assertTrue(self.make_store().inhibited())
        self.assertFalse(self.make_store().claim("two", "dock", "generation"))

    def test_record_failure_retains_original_claim(self):
        self.store.claim("one", "dock", "generation")
        with patch("os.replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                self.store.record("one", "prepared")
        self.assertEqual(self.store.load().stage, "claimed")
        self.assertTrue(self.store.inhibited())

    def test_corrupt_duplicate_unknown_and_oversized_fail_closed(self):
        target = self.root / FILENAME
        for value in (b"{}", b"x" * 4097,
                      b'{"schema_version":1,"schema_version":1}',
                      json.dumps({"schema_version": True, "operation": "a", "binding": "b",
                                  "generation": "c", "stage": "claimed"}).encode()):
            target.write_bytes(value)
            target.chmod(0o600)
            self.assertTrue(self.store.inhibited())
            self.assertFalse(self.store.claim("one", "dock", "generation"))

    def test_final_symlink_is_never_followed(self):
        target = self.root / "outside"
        target.write_text("unchanged")
        (self.root / FILENAME).symlink_to(target)
        self.assertTrue(self.store.inhibited())
        self.assertFalse(self.store.claim("one", "dock", "generation"))
        with self.assertRaises(OSError):
            self.store.record("one", "prepared")
        self.assertEqual(target.read_text(), "unchanged")

    def test_production_traversal_refuses_symlink_ancestor(self):
        if os.geteuid() != 0:
            self.skipTest("production traversal requires root")
        # A secure root-owned location avoids /tmp's deliberately unsafe mode.
        with tempfile.TemporaryDirectory(dir="/root") as directory:
            parent = Path(directory)
            real = parent / "real"
            real.mkdir(mode=0o700)
            (parent / "alias").symlink_to(real, target_is_directory=True)
            store = WholeDockClaimStore(parent / "alias")
            self.assertTrue(store.inhibited())
            with self.assertRaises(OSError):
                store.claim("one", "dock", "generation")
            self.assertFalse((real / FILENAME).exists())

    def test_pinned_directory_survives_path_substitution(self):
        # Explicit fixture FD establishes the same pinned-directory boundary.
        old = self.root / "old"
        new = self.root / "new"
        old.mkdir(mode=0o700)
        new.mkdir(mode=0o700)
        fd = os.open(old, os.O_RDONLY | os.O_DIRECTORY)
        try:
            store = WholeDockClaimStore(old, owner_uid=os.geteuid(), trusted_directory_fd=fd)
            old.rename(self.root / "retained")
            old.symlink_to(new, target_is_directory=True)
            self.assertTrue(store.claim("one", "dock", "generation"))
            self.assertTrue((self.root / "retained" / FILENAME).exists())
            self.assertFalse((new / FILENAME).exists())
        finally:
            os.close(fd)

    def test_retirement_requires_exact_identity_stage_and_guard(self):
        self.store.claim("one", "dock", "generation")
        with self.assertRaises(ValueError):
            self.store.retire_reconnected("one", "dock", "generation", lambda: True)
        self.store.record("one", "software_reconnected")
        for identity in (("two", "dock", "generation"), ("one", "other", "generation"),
                         ("one", "dock", "other")):
            with self.assertRaises(ValueError):
                self.store.retire_reconnected(*identity, lambda: True)
        for value in (False, None, 1):
            with self.assertRaises(ValueError):
                self.store.retire_reconnected("one", "dock", "generation", lambda: value)
        self.assertTrue(self.store.inhibited())

    def test_retirement_keeps_audit_and_releases_inhibition(self):
        self.store.claim("one", "dock", "generation")
        self.store.record("one", "software_reconnected")
        original = (self.root / FILENAME).read_bytes()
        audit = self.store.retire_reconnected("one", "dock", "generation", lambda: True)
        self.assertEqual((self.root / audit).read_bytes(), original)
        self.assertFalse(self.store.inhibited())
        self.assertTrue(self.store.claim("next", "dock", "next-generation"))
        self.assertEqual((self.root / audit).read_bytes(), original)

    def test_retirement_fsync_failure_restores_claim(self):
        self.store.claim("one", "dock", "generation")
        self.store.record("one", "software_reconnected")
        fsync = os.fsync
        calls = [0]
        def fail_once(descriptor):
            calls[0] += 1
            if calls[0] == 1:
                raise OSError("directory durability failed")
            return fsync(descriptor)
        with patch("os.fsync", side_effect=fail_once):
            with self.assertRaises(OSError):
                self.store.retire_reconnected("one", "dock", "generation", lambda: True)
        self.assertTrue(self.store.inhibited())
        self.assertEqual(self.store.load().stage, "software_reconnected")

    def test_retirement_audit_collision_preserves_both(self):
        self.store.claim("one", "dock", "generation")
        self.store.record("one", "software_reconnected")
        existing = self.root / "completed-whole-dock-collision.json"
        existing.write_text("previous audit")
        with patch("regear.delivery.whole_dock_claim.secrets.token_hex", return_value="collision"):
            with self.assertRaises(OSError):
                self.store.retire_reconnected("one", "dock", "generation", lambda: True)
        self.assertTrue(self.store.inhibited())
        self.assertEqual(existing.read_text(), "previous audit")


if __name__ == "__main__":
    unittest.main()
