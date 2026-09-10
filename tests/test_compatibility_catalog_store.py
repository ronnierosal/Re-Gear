from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.delivery.compatibility_catalog_store import (  # noqa: E402
    GAME_CATALOG_FILENAME,
    HARDWARE_CATALOG_FILENAME,
    FileCompatibilityCatalogStore,
)
from regear.domain.game_compatibility import (  # noqa: E402
    CompatibilityEvidence,
    CompatibilityEvidenceKind,
    EgpuHandoffStatus,
    GameCompatibilityRecord,
    ObservedRenderGpu,
    promote_egpu_handoff,
)
from regear.domain.hardware_compatibility import (  # noqa: E402
    HardwareCapability,
    HardwareCatalogStatus,
    HardwareCompatibilityRecord,
    HardwareEvidence,
    HardwareEvidenceKind,
    promote_hardware_capability,
)


def game_record(catalog_id="game-1"):
    return GameCompatibilityRecord(
        catalog_id,
        "Fixture Game",
        "asus-rog-ally-x",
        "gpd-g1-rx7600mxt",
        "1234",
    )


def promoted_game():
    record = game_record()
    evidence = CompatibilityEvidence(
        "game-evidence-1",
        record.catalog_id,
        record.steam_app_id,
        CompatibilityEvidenceKind.HARDWARE_TEST,
        True,
        True,
        record.host_profile_id,
        record.egpu_profile_id,
        "0.2.0",
        "steamos-2026",
        "2026-08-31T12:00:00Z",
        ObservedRenderGpu.EXTERNAL,
    )
    return promote_egpu_handoff(record, EgpuHandoffStatus.VERIFIED, evidence)


def hardware_record(catalog_id="hardware-1"):
    return HardwareCompatibilityRecord(
        catalog_id,
        "asus-rog-ally-x",
        "gpd-g1-rx7600mxt",
    )


def promoted_hardware():
    record = hardware_record()
    evidence = HardwareEvidence(
        "hardware-evidence-1",
        HardwareCapability.EGPU_DETECTION,
        HardwareCatalogStatus.VERIFIED,
        HardwareEvidenceKind.READ_ONLY_HARDWARE_TEST,
        True,
        True,
        record.host_profile_id,
        record.egpu_profile_id,
        "0.2.0",
        "steamos-2026",
        "2026-08-31T12:00:00Z",
    )
    return promote_hardware_capability(
        record,
        HardwareCapability.EGPU_DETECTION,
        HardwareCatalogStatus.VERIFIED,
        evidence,
    )


class CompatibilityCatalogStoreTests(unittest.TestCase):
    def store(self, root, *, replace=None, token="temporary1"):
        kwargs = {"token_factory": lambda: token}
        if replace is not None:
            kwargs["replace"] = replace
        return FileCompatibilityCatalogStore(Path(root).resolve(), **kwargs)

    def test_round_trips_sorted_game_and_hardware_catalogs(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory)
            store.save_games((game_record("game-2"), promoted_game()))
            store.save_hardware((hardware_record("hardware-2"), promoted_hardware()))

            games = store.load_games()
            hardware = store.load_hardware()

            self.assertEqual([item.catalog_id for item in games], ["game-1", "game-2"])
            self.assertEqual(games[0].egpu_handoff, EgpuHandoffStatus.VERIFIED)
            self.assertEqual([item.catalog_id for item in hardware], ["hardware-1", "hardware-2"])
            self.assertEqual(
                hardware[0].status_for(HardwareCapability.EGPU_DETECTION),
                HardwareCatalogStatus.VERIFIED,
            )

    def test_existing_catalog_history_cannot_be_removed_or_diverged(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory)
            original_game = promoted_game()
            original_hardware = promoted_hardware()
            store.save_games((original_game,))
            store.save_hardware((original_hardware,))

            with self.assertRaisesRegex(ValueError, "cannot be removed"):
                store.save_games(())
            with self.assertRaisesRegex(ValueError, "cannot (change|diverge)"):
                store.save_games((game_record(),))
            with self.assertRaisesRegex(ValueError, "cannot be removed"):
                store.save_hardware(())
            with self.assertRaisesRegex(ValueError, "cannot (change|diverge)"):
                store.save_hardware((hardware_record(),))

            self.assertEqual(store.load_games(), (original_game,))
            self.assertEqual(store.load_hardware(), (original_hardware,))

    def test_corrupt_unknown_or_extra_schema_fields_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self.store(root)
            cases = (
                (GAME_CATALOG_FILENAME, b"not-json", "JSON"),
                (HARDWARE_CATALOG_FILENAME, json.dumps({"schema_version": 2, "records": []}).encode(), "schema"),
                (GAME_CATALOG_FILENAME, json.dumps({"schema_version": 1, "records": [], "extra": True}).encode(), "fields"),
            )
            for filename, data, message in cases:
                (root / filename).write_bytes(data)
                loader = store.load_games if filename == GAME_CATALOG_FILENAME else store.load_hardware
                with self.subTest(filename=filename, data=data), self.assertRaisesRegex(ValueError, message):
                    loader()
                (root / filename).unlink()

    def test_replace_failure_preserves_prior_catalog_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            initial = self.store(directory, token="temporary1")
            initial.save_games((game_record(),))

            def fail_replace(_source, _target):
                raise OSError("injected replace failure")

            failing = self.store(directory, replace=fail_replace, token="temporary2")
            with self.assertRaisesRegex(OSError, "injected"):
                failing.save_games((promoted_game(),))
            self.assertEqual(initial.load_games(), (game_record(),))
            self.assertEqual([item.name for item in Path(directory).iterdir()], [GAME_CATALOG_FILENAME])

    def test_catalog_files_are_private_and_never_include_delivery_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory)
            store.save_games((promoted_game(),))
            store.save_hardware((promoted_hardware(),))
            for filename in (GAME_CATALOG_FILENAME, HARDWARE_CATALOG_FILENAME):
                path = Path(directory) / filename
                if os.name == "posix":
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                data = path.read_text(encoding="utf-8")
                self.assertNotIn("/home/", data)
                self.assertNotIn("/sys/", data)
                self.assertNotIn("renderD", data)

    def test_relative_or_symlink_root_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "absolute"):
            FileCompatibilityCatalogStore(Path("relative"))
        with tempfile.TemporaryDirectory() as directory:
            real = Path(directory) / "real"
            link = Path(directory) / "link"
            real.mkdir()
            try:
                link.symlink_to(real, target_is_directory=True)
            except OSError:
                self.skipTest("directory symlinks are unavailable on this host")
            with self.assertRaisesRegex(ValueError, "real directory"):
                # Do not use self.store here: its normal fixture setup resolves
                # roots, which would turn this deliberately symlinked input into
                # the target directory before the store can reject it.
                FileCompatibilityCatalogStore(link.absolute()).load_games()


if __name__ == "__main__":
    unittest.main()
