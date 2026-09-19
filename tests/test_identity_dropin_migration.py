import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.steamos.gamescope_user import GamescopeUserContext  # noqa: E402
from regear.delivery.gamescope_integration import GamescopeIntegrationStore  # noqa: E402
from regear.delivery.identity_dropin_migration import ManagedDropinMigration  # noqa: E402
from regear.delivery.identity_migration import IdentityMigrationError  # noqa: E402


class ManagedDropinMigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        home = self.root / "home" / "deck"
        home.mkdir(parents=True)
        plugin = self.root / "plugins" / "Re-Gear"
        shim = plugin / "bin" / "gamescope"
        shim.parent.mkdir(parents=True)
        shim.write_text("# Re-Gear Gamescope argument shim\n", encoding="utf-8")
        uid = getattr(os, "getuid", lambda: 1000)()
        gid = getattr(os, "getgid", lambda: 1000)()
        user = GamescopeUserContext(
            "deck", uid, gid, home,
            Path("/run/user") / str(uid), Path("/run/user") / str(uid) / "bus",
        )
        self.store = GamescopeIntegrationStore(
            plugin_root=plugin,
            user=user,
            effective_uid=lambda: 0,
            set_owner=lambda path, user_id, group_id: None,
        )
        self.store.target.parent.mkdir(parents=True)
        self.journal = self.root / "authority" / "dropin-journal.json"
        self.migration = ManagedDropinMigration(self.store, self.journal)
        self.legacy = self.store._superseded_renderings()[0]

    def _write(self, path: Path, value: str) -> None:
        path.write_bytes(value.encode("utf-8"))
        os.chmod(path, 0o600)

    def test_exact_former_file_moves_to_current_and_rolls_back(self):
        self._write(self.store.legacy_target, self.legacy)

        applied = self.migration.apply()
        self.assertEqual(applied["current"], "current")
        self.assertEqual(applied["former"], "absent")
        self.assertEqual(applied["journal_phase"], "committed")
        self.assertEqual(self.store.target.read_text(encoding="utf-8"), self.store.expected_text())

        rolled_back = self.migration.rollback()
        self.assertEqual(rolled_back["current"], "absent")
        self.assertEqual(rolled_back["former"], "former")
        self.assertEqual(rolled_back["journal_phase"], "rolled_back")
        self.assertEqual(self.store.legacy_target.read_text(encoding="utf-8"), self.legacy)

    def test_current_only_is_idempotent_without_creating_journal(self):
        self._write(self.store.target, self.store.expected_text())
        first = self.migration.apply()
        second = self.migration.apply()
        self.assertEqual(first, second)
        self.assertEqual(first["current"], "current")
        self.assertIsNone(first["journal_phase"])
        self.assertFalse(self.journal.exists())

    def test_both_without_journal_and_edited_former_refuse(self):
        self._write(self.store.target, self.store.expected_text())
        self._write(self.store.legacy_target, self.legacy)
        with self.assertRaisesRegex(IdentityMigrationError, "both"):
            self.migration.apply()
        self.store.target.unlink()
        self.store.legacy_target.write_bytes(b"edited\n")
        with self.assertRaisesRegex(IdentityMigrationError, "not exact"):
            self.migration.apply()

    def test_resume_from_exact_dual_file_crash_state(self):
        self._write(self.store.legacy_target, self.legacy)
        document = {
            "schema": 1,
            "operation_id": "a" * 32,
            "phase": "prepared",
            "legacy": self.legacy,
            "current": self.store.expected_text(),
        }
        self.migration._write_journal(document)
        self._write(self.store.target, self.store.expected_text())

        result = self.migration.apply()
        self.assertEqual(result["journal_phase"], "committed")
        self.assertFalse(self.store.legacy_target.exists())

    def test_changed_current_file_blocks_rollback_and_preserves_both(self):
        self._write(self.store.legacy_target, self.legacy)
        self.migration.apply()
        self.store.target.write_bytes(b"changed\n")

        with self.assertRaisesRegex(IdentityMigrationError, "changed before rollback"):
            self.migration.rollback()
        self.assertEqual(self.store.target.read_text(encoding="utf-8"), "changed\n")
        self.assertFalse(self.store.legacy_target.exists())


if __name__ == "__main__":
    unittest.main()
