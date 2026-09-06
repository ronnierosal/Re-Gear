import concurrent.futures
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from hdm.delivery.gamescope_wrapper import GamescopeLaunchConfig
from hdm.delivery.portable_trial_store import PortableTrialStore


class Config:
    def __init__(self, value):
        self.value = value
    def load(self):
        return self.value
    def restore(self, value):
        self.value = value


class TrialStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = PortableTrialStore(self.root)
        self.expected = GamescopeLaunchConfig("a" * 64, "portable", "eDP-1")
        self.values = dict(operation_id="operation-123", boot_id_sha256="a" * 64,
            generation="generation-123", internal_gpu="1002:150e", internal_connector="eDP-1",
            egpu_binding_sha256="b" * 64, original_config=None,
            expected_config=self.expected, expires_at=100.0)

    def test_missing(self):
        self.assertIsNone(self.store.read())
        self.assertIsNone(self.store.consume())

    @unittest.skipUnless(os.name == "posix", "POSIX file modes required")
    def test_modes_ignore_restrictive_umask(self):
        previous = os.umask(0o077)
        try:
            self.store.arm(**self.values)
            self.store.consume()
        finally:
            os.umask(previous)
        self.assertEqual(stat.S_IMODE((self.root / "portable-vulkan-trial.json").stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE((self.root / "portable-vulkan-trial.consumed").stat().st_mode), 0o600)

    def test_double_consume_and_rearm(self):
        self.store.arm(**self.values)
        self.assertEqual(self.store.consume()["operation_id"], "operation-123")
        self.assertIsNone(PortableTrialStore(self.root).consume())
        with self.assertRaises((ValueError, FileExistsError)):
            self.store.arm(**self.values)

    def test_outstanding_record_blocks_rearm(self):
        self.store.arm(**self.values)
        with self.assertRaises(FileExistsError):
            self.store.arm(**self.values)

    def test_concurrent_consumption(self):
        self.store.arm(**self.values)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: PortableTrialStore(self.root).consume(), range(8)))
        self.assertEqual(sum(value is not None for value in results), 1)

    def test_cancel_wrong_operation(self):
        self.store.arm(**self.values)
        with self.assertRaises(ValueError):
            self.store.cancel("wrong")
        self.store.cancel("operation-123")
        self.assertIsNone(self.store.consume())

    def test_restore_absent_and_exact_original(self):
        for original in (None, GamescopeLaunchConfig("a" * 64, "portable", "eDP-2")):
            with self.subTest(original=original), tempfile.TemporaryDirectory() as directory:
                store = PortableTrialStore(Path(directory))
                store.arm(**dict(self.values, original_config=original))
                config = Config(self.expected)
                store.restore_original(config, "operation-123")
                self.assertEqual(config.value, original)
                self.assertIsNone(store.consume())
                store.restore_original(config, "operation-123")

    def test_restore_conflict_and_wrong_operation(self):
        self.store.arm(**self.values)
        config = Config(GamescopeLaunchConfig("a" * 64, "portable", "eDP-3"))
        with self.assertRaises(ValueError):
            self.store.restore_original(config, "operation-123")
        with self.assertRaises(ValueError):
            self.store.restore_original(Config(self.expected), "wrong")

    def test_corrupt_and_oversize(self):
        path = self.root / "portable-vulkan-trial.json"
        for content in ("bad", "{}", "x" * 16385):
            path.write_text(content)
            with self.assertRaises(ValueError):
                self.store.read()

    def test_invalid_expiry_and_identity(self):
        for change in (dict(expires_at=float("nan")), dict(expires_at=True),
                       dict(expires_at=-1), dict(operation_id="../escape")):
            with self.assertRaises(ValueError):
                self.store.arm(**dict(self.values, **change))

    def test_symlink_record(self):
        target = self.root / "target"
        target.write_text("{}")
        try:
            (self.root / "portable-vulkan-trial.json").symlink_to(target)
        except OSError:
            self.skipTest("symlink creation unavailable")
        with self.assertRaises(ValueError):
            self.store.read()


if __name__ == "__main__":
    unittest.main()
