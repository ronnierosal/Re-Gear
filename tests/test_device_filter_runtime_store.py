from dataclasses import replace
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from backend.hdm.delivery.device_filter_runtime_bundle import build_runtime_bundle
from backend.hdm.delivery.device_filter_runtime_store import RuntimeStore, _validate


def bundle():
    sources = {"hdm/delivery/" + name: b"# fixture\n" for name in (
        "device_filter_bootstrap.py", "gamescope_wrapper.py", "steam_trial_wrapper.py", "device_filter_wrapper.py")}
    sources.update({"hdm/__init__.py": b"", "hdm/delivery/__init__.py": b""})
    return build_runtime_bundle(sources, session_sha256="a" * 64)


class RuntimeStoreValidationTests(unittest.TestCase):
    def test_tampered_bundle_rejected(self):
        original = bundle()
        for changes in ({"archive": original.archive + b"changed"}, {"digest": "b" * 64},
                        {"path": "/tmp/runtime.pyz"}, {"gamescope_shim": b"other"},
                        {"steam_argv": ("steam",)}, {"session_argv": ("session",)}):
            with self.assertRaises(ValueError):
                _validate(replace(original, **changes))

    def test_fixture_requires_paired_authority(self):
        for options in ({"owner_uid": 1}, {"trusted_directory_fd": 2},
                        {"owner_uid": True, "trusted_directory_fd": 2}):
            with self.assertRaises(ValueError):
                RuntimeStore(**options)


@unittest.skipUnless(sys.platform == "linux", "Linux immutable runtime fixture")
class RuntimeStoreLinuxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)
        self.store = RuntimeStore(owner_uid=os.getuid(), trusted_directory_fd=self.fd)
        self.bundle = bundle()

    def test_publication_readback_and_no_overwrite(self):
        result = self.store.publish(self.bundle)
        self.assertEqual(result, self.store.verify(self.bundle))
        target = self.root / result.digest
        self.assertEqual((target / "runtime.pyz").read_bytes(), self.bundle.archive)
        self.assertEqual((target / "runtime.pyz").stat().st_mode & 0o777, 0o444)
        self.assertEqual((target / "bin/gamescope").stat().st_mode & 0o777, 0o555)
        with self.assertRaises(OSError):
            self.store.publish(self.bundle)
        self.assertEqual(list(self.root.iterdir()), [target])

    def test_existing_target_symlink_not_followed_or_replaced(self):
        target = self.root / self.bundle.digest
        target.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            self.store.publish(self.bundle)
        with self.assertRaises(OSError):
            self.store.verify(self.bundle)
        self.assertTrue(target.is_symlink())

    def test_unsafe_parent_rejected(self):
        self.root.chmod(0o777)
        try:
            with self.assertRaises(ValueError):
                self.store.publish(self.bundle)
        finally:
            self.root.chmod(0o700)

    def test_write_failure_cleans_only_temporary_entries(self):
        unrelated = self.root / "preserve"
        unrelated.write_text("keep")
        with patch("backend.hdm.delivery.device_filter_runtime_store.os.write", side_effect=OSError("write failure")):
            with self.assertRaises(OSError):
                self.store.publish(self.bundle)
        self.assertEqual(list(self.root.iterdir()), [unrelated])

    def test_postpublication_fsync_failure_retains_runtime(self):
        real_fsync = os.fsync
        def fail_parent(fd):
            if os.fstat(fd).st_ino == os.fstat(self.fd).st_ino:
                raise OSError("parent sync failed")
            return real_fsync(fd)
        with patch("backend.hdm.delivery.device_filter_runtime_store.os.fsync", side_effect=fail_parent):
            with self.assertRaises(OSError):
                self.store.publish(self.bundle)
        self.assertTrue((self.root / self.bundle.digest / "runtime.pyz").exists())
        with patch("backend.hdm.delivery.device_filter_runtime_store.os.fsync", side_effect=OSError("still not durable")):
            with self.assertRaises(OSError):
                self.store.verify(self.bundle)
        self.store.verify(self.bundle)

    def test_file_symlink_and_modified_content_rejected(self):
        self.store.publish(self.bundle)
        archive = self.root / self.bundle.digest / "runtime.pyz"
        archive.unlink()
        archive.symlink_to(self.root / "absent")
        with self.assertRaises(OSError):
            self.store.verify(self.bundle)


if __name__ == "__main__":
    unittest.main()
