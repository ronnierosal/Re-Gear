from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch
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
            target = parent / "control"
            manager = self.manager(target)
            self.assertEqual(manager.ensure(), target)
            self.assertTrue(target.is_dir())
            self.assertEqual(
                stat.S_IMODE(manager._lstat(target).st_mode), STATE_DIRECTORY_MODE
            )
            self.assertEqual(manager.ensure(), target)

    def test_rejects_non_root_non_posix_relative_and_broad_paths(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "control"
            with self.assertRaisesRegex(ValueError, "POSIX root"):
                RootOwnedRuntimeState(
                    target, platform_name="nt", effective_uid=lambda: 0
                ).ensure()
            with self.assertRaisesRegex(ValueError, "POSIX root"):
                RootOwnedRuntimeState(
                    target, platform_name="posix", effective_uid=lambda: 1000
                ).ensure()
        with self.assertRaisesRegex(ValueError, "narrow absolute"):
            RootOwnedRuntimeState(Path("control"))
        with self.assertRaisesRegex(ValueError, "narrow absolute"):
            RootOwnedRuntimeState(Path(Path.cwd().anchor))

    def test_rejects_wrong_leaf_symlink_file_owner_and_mode(self):
        with tempfile.TemporaryDirectory() as root:
            parent = Path(root)
            with self.assertRaisesRegex(ValueError, "fixed Re-Gear"):
                self.manager(parent / "other")

            file_target = parent / "control"
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
                    parent / "control",
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
                    parent / "control",
                    platform_name="posix",
                    effective_uid=lambda: 0,
                    lstat=non_root_lstat,
                ).ensure()


class RuntimeStateInspectionTests(unittest.TestCase):
    """No actual root directory, device or mutating filesystem access."""
    target = ROOT / "fictional-runtime-parent" / "control"

    @staticmethod
    def metadata(mode=stat.S_IFDIR | 0o700, uid=0, inode=0):
        return os.stat_result((mode,inode,1,1,uid,0,0,0,0,0))

    def inspect(self, root=..., parent=..., *, platform="posix", uid=0):
        root = self.metadata() if root is ... else root
        parent = self.metadata() if parent is ... else parent
        parents=iter(parent) if type(parent) is list else None
        self.reads=[]
        def lstat(path):
            self.reads.append(path)
            value=(next(parents) if parents is not None else parent) if path==self.target.parent else root
            if isinstance(value,Exception):raise value
            return value
        with ExitStack() as stack:
            sinks=[stack.enter_context(patch(name,side_effect=AssertionError("inspection mutated state")))
                   for name in ("os.mkdir","os.chmod","os.open","os.fsync","os.rename","os.replace")]
            try:
                return RootOwnedRuntimeState(self.target,platform_name=platform,
                    effective_uid=lambda:uid,lstat=lstat).inspect_existing()
            finally:
                for sink in sinks:sink.assert_not_called()

    def test_inspects_existing_and_returns_none_only_for_absent_leaf(self):
        self.assertEqual(self.inspect(),self.target)
        self.assertEqual(self.reads,[self.target.parent,self.target,self.target.parent])
        self.assertIsNone(self.inspect(root=FileNotFoundError()))
        self.assertEqual(self.reads,[self.target.parent,self.target,self.target.parent])

    def test_missing_leaf_never_skips_parent_or_privilege_validation(self):
        for parent in (FileNotFoundError(), PermissionError(), self.metadata(uid=1000),
                       self.metadata(stat.S_IFLNK|0o700), self.metadata(stat.S_IFDIR|0o777)):
            with self.subTest(parent=type(parent).__name__), self.assertRaises(ValueError):
                self.inspect(root=FileNotFoundError(),parent=parent)
            self.assertEqual(self.reads,[self.target.parent])
        for platform,uid in (("nt",0),("posix",1000)):
            with self.assertRaises(ValueError):self.inspect(platform=platform,uid=uid)
            self.assertEqual(self.reads,[])

    def test_unsafe_or_denied_root_is_distinct_from_absence(self):
        for root in (PermissionError(),OSError(), self.metadata(uid=1000),
                     self.metadata(stat.S_IFREG|0o700),self.metadata(stat.S_IFLNK|0o700),
                     self.metadata(stat.S_IFDIR|0o755)):
            with self.subTest(root=type(root).__name__),self.assertRaises(ValueError):self.inspect(root=root)

    def test_no_second_stat_can_validate_a_replacement_root(self):
        # The inspected metadata is validated once, with no repair or retry that
        # could turn an unsafe first reading into a different accepted object.
        with self.assertRaises(ValueError):self.inspect(root=self.metadata(stat.S_IFLNK|0o700))
        self.assertEqual(self.reads.count(self.target),1)

    def test_parent_disappearance_or_replacement_never_reports_absent_root(self):
        for after in (FileNotFoundError(),PermissionError(),self.metadata(inode=2),
                      self.metadata(stat.S_IFLNK|0o700)):
            with self.subTest(after=type(after).__name__),self.assertRaises(ValueError):
                self.inspect(root=FileNotFoundError(),parent=[self.metadata(inode=1),after])

    def test_missing_metadata_is_uncertainty_not_proven_absence(self):
        for value in (None,{},object()):
            with self.assertRaises(ValueError):self.inspect(root=value)
            with self.assertRaises(ValueError):self.inspect(root=FileNotFoundError(),parent=value)


if __name__ == "__main__":
    unittest.main()
