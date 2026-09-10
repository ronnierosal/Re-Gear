from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.delivery.runtime_state import (  # noqa: E402
    STATE_DIRECTORY_MODE,
    RootOwnedRuntimeState,
)


class RuntimeStateTests(unittest.TestCase):
    @staticmethod
    def _metadata(
        path: Path,
        *,
        permissions: int = 0o700,
        uid: int = 0,
    ) -> os.stat_result:
        value = path.lstat()
        mode = stat.S_IFMT(value.st_mode) | permissions
        return os.stat_result(
            (
                mode,
                value.st_ino,
                value.st_dev,
                value.st_nlink,
                uid,
                value.st_gid,
                value.st_size,
                value.st_atime,
                value.st_mtime,
                value.st_ctime,
            )
        )

    @classmethod
    def manager(cls, path: Path, *, root_mode: int = 0o700, root_uid: int = 0):
        def lstat(candidate: Path) -> os.stat_result:
            if candidate == path and candidate.exists() and not candidate.is_symlink():
                return cls._metadata(candidate, permissions=root_mode, uid=root_uid)
            return cls._metadata(candidate, permissions=0o700, uid=0)

        return RootOwnedRuntimeState(
            path,
            platform_name="posix",
            effective_uid=lambda: 0,
            lstat=lstat,
        )

    def test_creates_and_reuses_exact_root_only_directory(self):
        with tempfile.TemporaryDirectory() as root:
            parent = Path(root)
            target = parent / "handheld-dock-mode"
            manager = self.manager(target)
            self.assertEqual(manager.ensure(), target)
            self.assertTrue(target.is_dir())
            self.assertEqual(
                stat.S_IMODE(manager._lstat(target).st_mode), STATE_DIRECTORY_MODE
            )
            self.assertEqual(manager.ensure(), target)

    def test_rejects_non_root_non_posix_relative_and_broad_paths(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "handheld-dock-mode"
            with self.assertRaisesRegex(ValueError, "POSIX root"):
                RootOwnedRuntimeState(
                    target, platform_name="nt", effective_uid=lambda: 0
                ).ensure()
            with self.assertRaisesRegex(ValueError, "POSIX root"):
                RootOwnedRuntimeState(
                    target, platform_name="posix", effective_uid=lambda: 1000
                ).ensure()
        with self.assertRaisesRegex(ValueError, "narrow absolute"):
            RootOwnedRuntimeState(Path("handheld-dock-mode"))
        with self.assertRaisesRegex(ValueError, "narrow absolute"):
            RootOwnedRuntimeState(Path(Path.cwd().anchor))

    def test_rejects_wrong_leaf_symlink_file_owner_and_mode(self):
        with tempfile.TemporaryDirectory() as root:
            parent = Path(root)
            with self.assertRaisesRegex(ValueError, "fixed legacy"):
                self.manager(parent / "other")

            file_target = parent / "handheld-dock-mode"
            file_target.write_text("unsafe", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "real directory"):
                self.manager(file_target).ensure()
            file_target.unlink()

            real = parent / "real"
            real.mkdir()
            symlink_created = False
            try:
                file_target.symlink_to(real, target_is_directory=True)
                symlink_created = True
            except OSError:
                pass
            if symlink_created:
                with self.assertRaisesRegex(ValueError, "real directory"):
                    self.manager(file_target).ensure()
                file_target.unlink()

            file_target.mkdir()
            with self.assertRaisesRegex(ValueError, "0700"):
                self.manager(file_target, root_mode=0o755).ensure()
            with self.assertRaisesRegex(ValueError, "root owned"):
                self.manager(file_target, root_uid=1000).ensure()

    def test_rejects_group_world_writable_parent(self):
        with tempfile.TemporaryDirectory() as root:
            parent = Path(root)
            def unsafe_lstat(path: Path) -> os.stat_result:
                return self._metadata(path, permissions=0o777, uid=0)

            with self.assertRaisesRegex(ValueError, "group/world writable"):
                RootOwnedRuntimeState(
                    parent / "handheld-dock-mode",
                    platform_name="posix",
                    effective_uid=lambda: 0,
                    lstat=unsafe_lstat,
                ).ensure()

    def test_rejects_non_root_owned_parent(self):
        with tempfile.TemporaryDirectory() as root:
            parent = Path(root)

            def non_root_lstat(path: Path) -> os.stat_result:
                return self._metadata(path, permissions=0o700, uid=1000)

            with self.assertRaisesRegex(ValueError, "parent must be root owned"):
                RootOwnedRuntimeState(
                    parent / "handheld-dock-mode",
                    platform_name="posix",
                    effective_uid=lambda: 0,
                    lstat=non_root_lstat,
                ).ensure()


if __name__ == "__main__":
    unittest.main()
