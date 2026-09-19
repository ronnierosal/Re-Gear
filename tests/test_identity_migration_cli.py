from __future__ import annotations

import importlib.util
from types import SimpleNamespace
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "migrate_regear_identity", ROOT / "scripts/migrate_regear_identity.py"
)
assert SPEC and SPEC.loader
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


class IdentityMigrationCliTests(unittest.TestCase):
    def test_gamescope_environment_requires_one_exact_current_identity(self):
        current = "/home/deck/.local/share/regear"
        self.assertEqual(
            tool._classify_gamescope_environment({"REGEAR_STATE_ROOT": current}),
            "current",
        )
        self.assertEqual(
            tool._classify_gamescope_environment(
                {"REGEAR_STATE_ROOT": current, "HDM_STATE_ROOT": "/former"}
            ),
            "ambiguous",
        )
        self.assertEqual(
            tool._classify_gamescope_environment(
                {"HDM_STATE_ROOT": "/home/deck/.local/share/handheld-dock-mode"}
            ),
            "former",
        )
        self.assertEqual(
            tool._classify_gamescope_environment({"HDM_STATE_ROOT": "/former"}),
            "unexpected",
        )
        self.assertEqual(tool._classify_gamescope_environment({}), "missing")
        self.assertEqual(
            tool._classify_gamescope_environment({"REGEAR_STATE_ROOT": "/edited"}),
            "unexpected",
        )

    def test_apply_guard_refuses_loader_or_runtime_process(self):
        with (
            patch.object(tool, "_plugin_loader_state", return_value="active"),
            patch.object(tool, "_active_processes") as processes,
            self.assertRaisesRegex(tool.IdentityMigrationError, "plugin_loader"),
        ):
            tool.require_offline()
        processes.assert_not_called()

        with (
            patch.object(tool, "_plugin_loader_state", return_value="inactive"),
            patch.object(tool, "_active_processes", return_value=("gamescope",)),
            self.assertRaisesRegex(tool.IdentityMigrationError, "gamescope"),
        ):
            tool.require_offline()

        for state in ("inactive", "failed"):
            with (
                patch.object(tool, "_plugin_loader_state", return_value=state),
                patch.object(tool, "_active_processes", return_value=()),
            ):
                tool.require_offline()

    def test_loader_state_must_be_explicit_and_old_backend_is_detected(self):
        completed = SimpleNamespace(returncode=1, stdout="", stderr="failed")
        with patch.object(tool.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(tool.IdentityMigrationError, "unavailable"):
                tool._plugin_loader_state()

        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            process = proc / "123"
            process.mkdir()
            (process / "comm").write_text("python3\n", encoding="utf-8")
            (process / "cmdline").write_bytes(
                b"python3\0/home/deck/homebrew/plugins/HandheldDockMode/main.py\0"
            )
            self.assertEqual(tool._active_processes(proc), ("regear_backend",))

    def test_gamescope_environment_reports_unreadable_instead_of_inactive(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            process = proc / "123"
            process.mkdir()
            (process / "comm").write_text("gamescope\n", encoding="utf-8")
            environ = process / "environ"
            environ.write_bytes(b"REGEAR_STATE_ROOT=/home/deck/.local/share/regear\0")
            original = Path.read_bytes

            def read_bytes(path):
                if path == environ:
                    raise PermissionError("denied")
                return original(path)

            with patch.object(Path, "read_bytes", read_bytes):
                self.assertEqual(tool._gamescope_environment_status(proc), "unreadable")

    def test_preflight_of_both_components_precedes_any_mutation(self):
        migration = SimpleNamespace(apply=unittest.mock.Mock())
        dropin = SimpleNamespace(
            preflight_apply=unittest.mock.Mock(
                side_effect=tool.IdentityMigrationError("edited drop-in")
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            record = tool.CombinedMigrationRecord(Path(directory) / "combined.json")
            with (
                patch.object(tool, "_preflight_directories", return_value=True),
                self.assertRaisesRegex(tool.IdentityMigrationError, "edited drop-in"),
            ):
                tool.apply_combined(migration, dropin, record)
            migration.apply.assert_not_called()
            self.assertFalse(record.path.exists())

    def test_interrupted_apply_resumes_from_combined_participation_record(self):
        status = SimpleNamespace(journal_phase="committed", locations=())
        migration = SimpleNamespace(
            apply=unittest.mock.Mock(
                side_effect=[RuntimeError("crash after subtransaction"), status]
            ),
            inspect=unittest.mock.Mock(return_value=status),
        )
        dropin = SimpleNamespace(
            preflight_apply=unittest.mock.Mock(return_value=True),
            apply=unittest.mock.Mock(return_value={"journal_phase": "committed"}),
            inspect=unittest.mock.Mock(return_value={"journal_phase": "committed"}),
        )
        with tempfile.TemporaryDirectory() as directory:
            record = tool.CombinedMigrationRecord(Path(directory) / "combined.json")
            with patch.object(tool, "_preflight_directories", return_value=True):
                with self.assertRaisesRegex(RuntimeError, "crash"):
                    tool.apply_combined(migration, dropin, record)
                self.assertEqual(record.load()["phase"], "prepared")
                tool.apply_combined(migration, dropin, record)
            self.assertEqual(record.load()["phase"], "committed")
            self.assertEqual(migration.apply.call_count, 2)
            dropin.apply.assert_called_once()

    def test_legacy_partial_rollback_restores_directories_without_dropin_journal(self):
        committed = SimpleNamespace(journal_phase="committed", locations=())
        rolled_back = SimpleNamespace(journal_phase="rolled_back", locations=())
        migration = SimpleNamespace(
            inspect=unittest.mock.Mock(return_value=committed),
            rollback=unittest.mock.Mock(return_value=rolled_back),
        )
        dropin = SimpleNamespace(
            inspect=unittest.mock.Mock(return_value={"journal_phase": None})
        )
        with tempfile.TemporaryDirectory() as directory:
            record = tool.CombinedMigrationRecord(Path(directory) / "combined.json")
            result, _ = tool.rollback_combined(migration, dropin, record)
            self.assertIs(result, rolled_back)
            migration.rollback.assert_called_once()
            self.assertEqual(record.load()["phase"], "rolled_back")

    def test_guard_is_read_only_and_tool_has_no_service_or_hardware_mutation(self):
        source = (ROOT / "scripts/migrate_regear_identity.py").read_text(encoding="utf-8")
        self.assertIn('"show",\n            "plugin_loader.service"', source)
        self.assertIn('"--property=ActiveState"', source)
        for forbidden in (
            '"stop"',
            '"start"',
            '"restart"',
            "shutdown",
            "suspend",
            "/sys/",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
