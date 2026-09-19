import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.delivery.identity_migration import (
    DirectoryMove,
    IdentityMigration,
    IdentityMigrationError,
    LocationState,
    default_moves,
)
from regear.delivery.gamescope_wrapper import GamescopeLaunchConfig
from regear.delivery.portable_trial_store import PortableTrialStore


class IdentityMigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.runtime_parent = self.root / "system"
        self.user_parent = self.root / "share"
        self.runtime_parent.mkdir()
        self.user_parent.mkdir()
        self.runtime_old = self.runtime_parent / "old-control"
        self.runtime_current = self.runtime_parent / "control"
        self.user_old = self.user_parent / "old-user"
        self.user_current = self.user_parent / "regear"
        uid = os.geteuid() if hasattr(os, "geteuid") else None
        allowed_uids = None if uid is None else frozenset((uid,))
        self.moves = (
            DirectoryMove("runtime", self.runtime_old, self.runtime_current, allowed_uids),
            DirectoryMove("user", self.user_old, self.user_current, allowed_uids),
        )
        self.journal = self.root / "identity-migration.json"
        self.migration = IdentityMigration(
            self.moves,
            self.journal,
            token_factory=lambda: "a" * 32,
        )

    @staticmethod
    def _create(path: Path, files: dict[str, bytes] | None = None) -> None:
        path.mkdir(mode=0o700)
        os.chmod(path, 0o700)
        for relative, data in (files or {}).items():
            target = path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            os.chmod(target, 0o600)

    def _journal_document(self, phase: str, *, completed=(), moves=None) -> dict:
        selected = self.moves if moves is None else moves
        return {
            "schema": 1,
            "operation_id": "b" * 32,
            "phase": phase,
            "moves": [
                {"name": item.name, "old": str(item.old), "current": str(item.current)}
                for item in selected
            ],
            "completed": list(completed),
        }

    def _write_journal(self, phase: str, *, completed=(), moves=None) -> None:
        self.journal.write_text(
            json.dumps(self._journal_document(phase, completed=completed, moves=moves)),
            encoding="ascii",
        )

    @staticmethod
    def _arm_trial(root: Path, *, terminal: bool) -> None:
        store = PortableTrialStore(root)
        operation_id = "operation-123"
        store.arm(
            operation_id=operation_id,
            boot_id_sha256="a" * 64,
            generation="generation-123",
            internal_gpu="1002:150e",
            internal_connector="eDP-1",
            egpu_binding_sha256="b" * 64,
            original_config=None,
            expected_config=GamescopeLaunchConfig("a" * 64, "portable", "eDP-1"),
            expires_at=100.0,
        )
        if terminal:
            store.consume()
            store.publish_gamescope_launch(operation_id, "c" * 32)
            store.consume_steam()

    def test_inspect_distinguishes_old_current_both_and_neither(self):
        self._create(self.runtime_old)
        self._create(self.user_current)
        status = self.migration.inspect()
        self.assertEqual(status.state("runtime"), LocationState.OLD_ONLY)
        self.assertEqual(status.state("user"), LocationState.CURRENT_ONLY)

        self._create(self.runtime_current)
        self.user_current.rename(self.user_old)
        self.assertEqual(self.migration.inspect().state("runtime"), LocationState.BOTH)
        self.user_old.rmdir()
        self.assertEqual(self.migration.inspect().state("user"), LocationState.NEITHER)

    def test_old_only_moves_whole_directories_and_preserves_exact_bytes(self):
        payload = b"\x00\xffexact-state\r\n"
        self._create(self.runtime_old, {"nested/claim-history.bin": payload})
        self._create(self.user_old, {"preferences.json": b'{"value":1}\n'})

        status = self.migration.apply()

        self.assertEqual(status.journal_phase, "committed")
        self.assertFalse(self.runtime_old.exists())
        self.assertFalse(self.user_old.exists())
        self.assertEqual((self.runtime_current / "nested/claim-history.bin").read_bytes(), payload)
        self.assertEqual((self.user_current / "preferences.json").read_bytes(), b'{"value":1}\n')
        self.assertEqual(json.loads(self.journal.read_text())["completed"], ["runtime", "user"])

    def test_current_only_and_neither_are_idempotent_without_a_journal(self):
        self._create(self.runtime_current, {"keep": b"current"})

        first = self.migration.apply()
        second = self.migration.apply()

        self.assertEqual(first, second)
        self.assertEqual(first.state("runtime"), LocationState.CURRENT_ONLY)
        self.assertEqual(first.state("user"), LocationState.NEITHER)
        self.assertFalse(self.journal.exists())
        self.assertEqual((self.runtime_current / "keep").read_bytes(), b"current")

    def test_both_roots_refuse_without_changing_either(self):
        self._create(self.runtime_old, {"old": b"old"})
        self._create(self.runtime_current, {"new": b"new"})

        with self.assertRaisesRegex(IdentityMigrationError, "both exist"):
            self.migration.apply()

        self.assertEqual((self.runtime_old / "old").read_bytes(), b"old")
        self.assertEqual((self.runtime_current / "new").read_bytes(), b"new")
        self.assertFalse(self.journal.exists())

    def test_transition_power_claim_reset_and_portable_markers_all_block(self):
        blockers = (
            "active-transition.json",
            "whole-dock-claim.json",
            "whole-dock-reset.pending",
            "dock-power-sleep.json",
            "portable-vulkan-trial.json",
            "portable-vulkan-trial.consumed",
            "portable-vulkan-trial.steam-consumed",
            "portable-vulkan-trial.gamescope-launch",
        )
        for blocker in blockers:
            with self.subTest(blocker=blocker):
                if self.runtime_old.exists():
                    for child in self.runtime_old.iterdir():
                        child.unlink()
                else:
                    self._create(self.runtime_old)
                (self.runtime_old / blocker).write_bytes(b"state")
                os.chmod(self.runtime_old / blocker, 0o600)
                with self.assertRaisesRegex(IdentityMigrationError, "blocks identity migration"):
                    self.migration.apply()
                self.assertFalse(self.journal.exists())

    def test_terminal_portable_trial_quartet_moves_unchanged(self):
        self._create(self.runtime_old)
        self._arm_trial(self.runtime_old, terminal=True)
        before = {
            path.name: path.read_bytes()
            for path in self.runtime_old.glob("portable-vulkan-trial.*")
        }

        self.migration.apply()

        after = {
            path.name: path.read_bytes()
            for path in self.runtime_current.glob("portable-vulkan-trial.*")
        }
        self.assertEqual(after, before)

    def test_unconsumed_partial_mismatched_and_malformed_trial_states_refuse(self):
        mutations = ("unconsumed", "partial", "mismatched", "malformed")
        for index, mutation in enumerate(mutations):
            with self.subTest(mutation=mutation):
                parent = self.root / f"trial-{index}"
                parent.mkdir()
                old = parent / "old"
                current = parent / "current"
                self._create(old)
                self._arm_trial(old, terminal=mutation != "unconsumed")
                if mutation == "partial":
                    (old / "portable-vulkan-trial.gamescope-launch").unlink()
                elif mutation == "mismatched":
                    (old / "portable-vulkan-trial.consumed").write_text("wrong")
                elif mutation == "malformed":
                    (old / "portable-vulkan-trial.json").write_text("not-json")
                uid = os.geteuid() if hasattr(os, "geteuid") else None
                allowed = None if uid is None else frozenset((uid,))
                move = DirectoryMove("trial", old, current, allowed)
                migration = IdentityMigration(
                    (move,),
                    parent / "journal.json",
                    token_factory=lambda: "e" * 32,
                )
                with self.assertRaisesRegex(IdentityMigrationError, "portable Vulkan trial"):
                    migration.apply()
                self.assertTrue(old.exists())
                self.assertFalse(current.exists())

    @unittest.skipUnless(os.name == "posix", "requires POSIX identity semantics")
    def test_default_user_policy_accepts_root_and_session_user_with_mode_0755(self):
        runtime, user = default_moves(Path("/home/deck"), user_uid=1000)
        self.assertEqual(runtime.allowed_uids, frozenset((0,)))
        self.assertEqual(runtime.root_mode, 0o700)
        self.assertEqual(user.allowed_uids, frozenset((0, 1000)))
        self.assertEqual(user.root_mode, 0o755)

        base = self.root.stat()
        root_directory = list(base)
        root_directory[0] = stat.S_IFDIR | 0o755
        root_directory[4] = 1000
        root_file = list(base)
        root_file[0] = stat.S_IFREG | 0o644
        root_file[4] = 0
        IdentityMigration._validate_metadata(os.stat_result(root_directory), user, root=True)
        IdentityMigration._validate_metadata(os.stat_result(root_file), user, root=False)

        root_file[4] = 1001
        with self.assertRaisesRegex(IdentityMigrationError, "ownership"):
            IdentityMigration._validate_metadata(os.stat_result(root_file), user, root=False)

    def test_non_idle_or_unknown_tdp_journal_blocks_but_idle_is_migrated(self):
        self._create(self.runtime_old)
        tdp = self.runtime_old / "tdp-session.json"
        tdp.write_text(json.dumps({"schema": 1, "record": {"phase": "active"}}))
        os.chmod(tdp, 0o600)
        with self.assertRaisesRegex(IdentityMigrationError, "non-idle TDP"):
            self.migration.apply()

        tdp.write_text("not-json")
        with self.assertRaisesRegex(IdentityMigrationError, "cannot be proven idle"):
            self.migration.apply()

        tdp.write_text(json.dumps({"schema": 1, "record": None}))
        self.migration.apply()
        self.assertTrue((self.runtime_current / "tdp-session.json").exists())

    def test_symlink_wrong_mode_and_wrong_owner_refuse(self):
        self._create(self.runtime_old)
        if os.name == "posix":
            os.chmod(self.runtime_old, 0o755)
            with self.assertRaisesRegex(IdentityMigrationError, "unexpected mode"):
                self.migration.apply()
            os.chmod(self.runtime_old, 0o700)

            wrong_owner = DirectoryMove(
                "runtime",
                self.runtime_old,
                self.runtime_current,
                frozenset((self.runtime_old.stat().st_uid + 1,)),
            )
            migration = IdentityMigration((wrong_owner,), self.journal, token_factory=lambda: "c" * 32)
            with self.assertRaisesRegex(IdentityMigrationError, "ownership"):
                migration.apply()

        link = self.runtime_old / "link"
        try:
            link.symlink_to(self.root / "outside")
        except OSError:
            self.skipTest("symlink creation unavailable")
        with self.assertRaisesRegex(IdentityMigrationError, "symlink"):
            self.migration.apply()

    def test_held_lock_refuses_before_journal_or_rename(self):
        self._create(self.runtime_old, {"dock-mutation.lock": b""})

        def refuse_state_lock(path, *, create=False):
            if create:
                return None
            raise IdentityMigrationError("held lock blocks identity migration")

        with patch.object(
            IdentityMigration,
            "_acquire_lock",
            side_effect=refuse_state_lock,
        ):
            with self.assertRaisesRegex(IdentityMigrationError, "held lock"):
                self.migration.apply()
        self.assertTrue(self.runtime_old.exists())
        self.assertFalse(self.journal.exists())

    def test_external_and_state_locks_remain_held_through_rename(self):
        self._create(self.runtime_old, {"dock-mutation.lock": b""})
        descriptors = []
        observed = []
        real_rename = os.rename

        def acquire(path, *, create=False):
            descriptor = os.open(os.devnull, os.O_RDONLY)
            descriptors.append((path.name, descriptor))
            return descriptor

        def rename_while_locked(source, destination):
            self.assertEqual(
                {name for name, _ in descriptors},
                {"identity-migration.json.lock", "dock-mutation.lock"},
            )
            for _, descriptor in descriptors:
                os.fstat(descriptor)  # Both descriptors remain open at rename.
            observed.append(True)
            real_rename(source, destination)

        with patch.object(IdentityMigration, "_acquire_lock", side_effect=acquire), patch(
            "regear.delivery.identity_migration.os.rename", side_effect=rename_while_locked
        ):
            self.migration.apply()

        self.assertEqual(observed, [True])
        for _, descriptor in descriptors:
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    @unittest.skipUnless(os.name == "posix", "requires POSIX flock semantics")
    def test_concurrent_migration_acquisition_refuses(self):
        self._create(self.runtime_old)
        competitor = IdentityMigration(self.moves, self.journal, token_factory=lambda: "d" * 32)

        with self.migration._hold_external_lock():
            with self.assertRaisesRegex(IdentityMigrationError, "held lock"):
                competitor.apply()

    def test_cross_filesystem_move_refuses_before_rename(self):
        self._create(self.runtime_old, {"keep": b"state"})
        real_lstat = Path.lstat

        def changed_device(path):
            value = real_lstat(path)
            if path == self.runtime_current.parent:
                fields = list(value)
                fields[2] = value.st_dev + 1
                return os.stat_result(fields)
            return value

        with patch.object(Path, "lstat", changed_device):
            with self.assertRaisesRegex(IdentityMigrationError, "cross filesystems"):
                self.migration.apply()
        self.assertTrue(self.runtime_old.exists())
        self.assertFalse(self.runtime_current.exists())
        self.assertFalse(self.journal.exists())

    def test_resume_after_rename_before_phase_update(self):
        self._create(self.runtime_old, {"state": b"runtime"})
        self._create(self.user_old, {"state": b"user"})
        self._write_journal("applying")
        self.runtime_old.rename(self.runtime_current)

        status = self.migration.apply()

        self.assertEqual(status.journal_phase, "committed")
        self.assertEqual((self.runtime_current / "state").read_bytes(), b"runtime")
        self.assertEqual((self.user_current / "state").read_bytes(), b"user")

    def test_partial_rollback_moves_live_current_state_back(self):
        self._create(self.runtime_current, {"state": b"changed-after-move"})
        self._create(self.user_current, {"state": b"user-current"})
        self._write_journal("rolling_back", completed=("runtime", "user"))
        self.user_current.rename(self.user_old)  # Crash after the first reverse move.

        status = self.migration.rollback()

        self.assertEqual(status.journal_phase, "rolled_back")
        self.assertEqual((self.runtime_old / "state").read_bytes(), b"changed-after-move")
        self.assertEqual((self.user_old / "state").read_bytes(), b"user-current")
        self.assertFalse(self.runtime_current.exists())
        self.assertFalse(self.user_current.exists())
        self.assertEqual(self.migration.rollback(), status)

    def test_unknown_phase_and_mismatched_paths_refuse(self):
        self._create(self.runtime_old)
        self._write_journal("future-phase")
        with self.assertRaisesRegex(IdentityMigrationError, "unknown"):
            self.migration.apply()

        document = self._journal_document("prepared")
        document["moves"][0]["current"] = str(self.root / "unexpected")
        self.journal.write_text(json.dumps(document))
        with self.assertRaisesRegex(IdentityMigrationError, "do not match"):
            self.migration.apply()


if __name__ == "__main__":
    unittest.main()
