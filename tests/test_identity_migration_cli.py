from __future__ import annotations

import importlib.util
import os
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
    def conflict_fixture(self, root: Path):
        former = root / "former-control"
        current = root / "regear" / "control"
        archive = root / "regear" / "pre-migration-control-v1"
        journal = root / "regear" / "identity-control-conflict-v1.json"
        former.mkdir(mode=0o700)
        current.mkdir(mode=0o700, parents=True)
        os.chmod(current.parent, 0o700)
        audio = b'{"schema_version":1,"sink_name":"fixture"}\n'
        for directory in (former, current):
            (directory / "portable-audio.json").write_bytes(audio)
            os.chmod(directory / "portable-audio.json", 0o600)
        for name in ("dock-mutation.lock", "whole-dock-claim.lock"):
            (current / name).write_bytes(b"")
            os.chmod(current / name, 0o600)
        (former / "completed-history.json").write_text("{}\n", encoding="ascii")
        os.chmod(former / "completed-history.json", 0o600)
        move = tool.DirectoryMove("runtime", former, current, None)
        migration = tool.IdentityMigration((move,), root / "migration.json")
        record = tool.ControlConflictRecord(journal, archive)
        return migration, record, former, current, archive

    def test_duplicate_runtime_reconciliation_archives_fresh_root_whole(self):
        with tempfile.TemporaryDirectory() as directory:
            migration, record, former, current, archive = self.conflict_fixture(
                Path(directory)
            )
            result = tool.reconcile_duplicate_runtime(migration, record)
            self.assertEqual(result["phase"], "committed")
            self.assertTrue(former.is_dir())
            self.assertFalse(current.exists())
            self.assertEqual(
                {path.name for path in archive.iterdir()},
                {"dock-mutation.lock", "whole-dock-claim.lock", "portable-audio.json"},
            )
            self.assertEqual(record.load()["phase"], "committed")

    def test_duplicate_runtime_reconciliation_refuses_active_former_state(self):
        with tempfile.TemporaryDirectory() as directory:
            migration, record, former, current, archive = self.conflict_fixture(
                Path(directory)
            )
            blocker = former / "whole-dock-claim.json"
            blocker.write_text("{}\n", encoding="ascii")
            os.chmod(blocker, 0o600)
            with self.assertRaisesRegex(tool.IdentityMigrationError, "active state"):
                tool.reconcile_duplicate_runtime(migration, record)
            self.assertTrue(current.is_dir())
            self.assertFalse(archive.exists())
            self.assertFalse(record.path.exists())

    def test_duplicate_runtime_reconciliation_refuses_nonfresh_current_root(self):
        with tempfile.TemporaryDirectory() as directory:
            migration, record, _, current, archive = self.conflict_fixture(
                Path(directory)
            )
            unexpected = current / "unexpected.json"
            unexpected.write_text("{}\n", encoding="ascii")
            os.chmod(unexpected, 0o600)
            with self.assertRaisesRegex(tool.IdentityMigrationError, "exact fresh"):
                tool.reconcile_duplicate_runtime(migration, record)
            self.assertTrue(current.is_dir())
            self.assertFalse(archive.exists())

    def test_duplicate_runtime_reconciliation_refuses_different_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            migration, record, _, current, archive = self.conflict_fixture(
                Path(directory)
            )
            (current / "portable-audio.json").write_bytes(b'{"sink_name":"different"}\n')
            with self.assertRaisesRegex(tool.IdentityMigrationError, "audio state differs"):
                tool.reconcile_duplicate_runtime(migration, record)
            self.assertTrue(current.is_dir())
            self.assertFalse(archive.exists())
            self.assertFalse(record.path.exists())

    def test_duplicate_runtime_reconciliation_resumes_after_rename(self):
        with tempfile.TemporaryDirectory() as directory:
            migration, record, former, current, archive = self.conflict_fixture(
                Path(directory)
            )
            manifest = tool._fresh_manifest(current, former)
            with record.hold():
                record.create(manifest)
            current.rename(archive)
            result = tool.reconcile_duplicate_runtime(migration, record)
            self.assertEqual(result["phase"], "committed")
            self.assertFalse(current.exists())
            self.assertTrue(archive.is_dir())

    def test_duplicate_runtime_committed_archive_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            migration, record, _, _, archive = self.conflict_fixture(Path(directory))
            tool.reconcile_duplicate_runtime(migration, record)
            (archive / "portable-audio.json").write_text("changed\n", encoding="ascii")
            with self.assertRaisesRegex(tool.IdentityMigrationError, "changed|differs"):
                tool.reconcile_duplicate_runtime(migration, record)

    def test_apply_refuses_prepared_or_orphaned_conflict_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            migration, record, former, current, archive = self.conflict_fixture(
                Path(directory)
            )
            manifest = tool._fresh_manifest(current, former)
            with record.hold():
                record.create(manifest)
            current.rename(archive)
            with self.assertRaisesRegex(tool.IdentityMigrationError, "rerun reconcile"):
                tool.require_conflict_resolved_for_apply(migration, record)

        with tempfile.TemporaryDirectory() as directory:
            migration, record, _, current, archive = self.conflict_fixture(
                Path(directory)
            )
            current.rename(archive)
            with self.assertRaisesRegex(tool.IdentityMigrationError, "without its journal"):
                tool.require_conflict_resolved_for_apply(migration, record)

    def test_apply_accepts_only_exact_committed_conflict_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            migration, record, _, _, archive = self.conflict_fixture(Path(directory))
            tool.reconcile_duplicate_runtime(migration, record)
            tool.require_conflict_resolved_for_apply(migration, record)
            (archive / "portable-audio.json").write_text("changed\n", encoding="ascii")
            with self.assertRaisesRegex(tool.IdentityMigrationError, "changed|differs"):
                tool.require_conflict_resolved_for_apply(migration, record)

    def test_committed_archive_survives_live_audio_updates_after_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            migration, conflict, _, current, archive = self.conflict_fixture(root)
            tool.reconcile_duplicate_runtime(migration, conflict)
            archived_audio = (archive / "portable-audio.json").read_bytes()
            combined = tool.CombinedMigrationRecord(root / "combined.json")
            dropin = SimpleNamespace(
                preflight_apply=unittest.mock.Mock(return_value=False),
                inspect=unittest.mock.Mock(return_value={"journal_phase": None}),
            )
            tool.apply_combined(migration, dropin, combined, conflict)
            (current / "portable-audio.json").write_bytes(
                b'{"schema_version":1,"sink_name":"updated"}\n'
            )
            tool.apply_combined(migration, dropin, combined, conflict)
            self.assertEqual(combined.load()["phase"], "committed")
            self.assertEqual((archive / "portable-audio.json").read_bytes(), archived_audio)

            changed_journal = conflict.load()
            audio_entry = next(
                entry for entry in changed_journal["manifest"]["entries"]
                if entry["name"] == "portable-audio.json"
            )
            audio_entry["sha256"] = "0" * 64
            with conflict.hold():
                conflict.write(changed_journal)
            with self.assertRaisesRegex(tool.IdentityMigrationError, "archive changed"):
                tool.apply_combined(migration, dropin, combined, conflict)

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

    def test_steamos_gamescope_wl_process_blocks_offline_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            process = proc / "123"
            process.mkdir()
            (process / "comm").write_text("gamescope-wl\n", encoding="utf-8")
            (process / "cmdline").write_bytes(b"/usr/bin/gamescope\0-e\0")
            self.assertEqual(tool._active_processes(proc), ("gamescope",))

    def test_steamos_gamescope_wl_environment_is_observed(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            process = proc / "123"
            process.mkdir()
            (process / "comm").write_text("gamescope-wl\n", encoding="utf-8")
            (process / "environ").write_bytes(
                b"REGEAR_STATE_ROOT=/home/deck/.local/share/regear\0"
            )
            self.assertEqual(tool._gamescope_environment_status(proc), "current")

    def test_process_inspection_errors_refuse_offline_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            process = proc / "123"
            process.mkdir()
            comm = process / "comm"
            cmdline = process / "cmdline"
            comm.write_text("gamescope\n", encoding="utf-8")
            cmdline.write_bytes(b"gamescope\0")
            original_read_bytes = Path.read_bytes

            def unreadable_cmdline(path):
                if path == cmdline:
                    raise PermissionError("denied")
                return original_read_bytes(path)

            with (
                patch.object(Path, "read_bytes", unreadable_cmdline),
                self.assertRaisesRegex(
                    tool.IdentityMigrationError, "process inspection"
                ),
            ):
                tool._active_processes(proc)

            original_read_text = Path.read_text

            def unreadable_comm(path, *args, **kwargs):
                if path == comm:
                    raise OSError("unreadable")
                return original_read_text(path, *args, **kwargs)

            with (
                patch.object(Path, "read_text", unreadable_comm),
                self.assertRaisesRegex(
                    tool.IdentityMigrationError, "process inspection"
                ),
            ):
                tool._active_processes(proc)

    def test_disappearing_process_is_a_bounded_race(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            process = proc / "123"
            process.mkdir()
            comm = process / "comm"
            comm.write_text("python3\n", encoding="utf-8")
            (process / "cmdline").write_bytes(b"python3\0")
            original = Path.read_text

            def disappeared(path, *args, **kwargs):
                if path == comm:
                    raise FileNotFoundError(path)
                return original(path, *args, **kwargs)

            with patch.object(Path, "read_text", disappeared):
                self.assertEqual(tool._active_processes(proc), ())

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

    def test_rollback_resumes_when_never_started_participants_have_no_journals(self):
        idle = SimpleNamespace(journal_phase=None, locations=())
        for phase in ("prepared", "rolling_back", "dropin_rolled_back"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                migration = SimpleNamespace(
                    inspect=unittest.mock.Mock(return_value=idle),
                    rollback=unittest.mock.Mock(),
                )
                dropin = SimpleNamespace(
                    inspect=unittest.mock.Mock(return_value={"journal_phase": None}),
                    rollback=unittest.mock.Mock(),
                )
                record = tool.CombinedMigrationRecord(
                    Path(directory) / "combined.json"
                )
                document = record.create(directories=True, dropin=True)
                if phase != "prepared":
                    document["rollback_directories"] = False
                    document["rollback_dropin"] = False
                    document["phase"] = phase
                    record.write(document)

                tool.rollback_combined(migration, dropin, record)

                migration.rollback.assert_not_called()
                dropin.rollback.assert_not_called()
                self.assertEqual(record.load()["phase"], "rolled_back")

    def test_rollback_resumes_at_each_boundary_for_started_participants(self):
        committed = SimpleNamespace(journal_phase="committed", locations=())
        rolled_back = SimpleNamespace(journal_phase="rolled_back", locations=())
        cases = (
            ("committed", 1),
            ("rolling_back", 1),
            ("dropin_rolled_back", 0),
        )
        for phase, expected_dropin_calls in cases:
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                migration = SimpleNamespace(
                    inspect=unittest.mock.Mock(return_value=committed),
                    rollback=unittest.mock.Mock(return_value=rolled_back),
                )
                dropin = SimpleNamespace(
                    inspect=unittest.mock.Mock(
                        return_value={"journal_phase": "committed"}
                    ),
                    rollback=unittest.mock.Mock(
                        return_value={"journal_phase": "rolled_back"}
                    ),
                )
                record = tool.CombinedMigrationRecord(
                    Path(directory) / "combined.json"
                )
                document = record.create(directories=True, dropin=True)
                if phase == "committed":
                    document["phase"] = phase
                else:
                    document["rollback_directories"] = True
                    document["rollback_dropin"] = True
                    document["phase"] = phase
                record.write(document)

                tool.rollback_combined(migration, dropin, record)

                self.assertEqual(dropin.rollback.call_count, expected_dropin_calls)
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
