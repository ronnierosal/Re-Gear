import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("coord", Path(__file__).resolve().parents[1] / "scripts/release_coordination.py")
coord = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coord)

class ReleaseCoordinationTests(unittest.TestCase):
    def test_shared_worktrees_reject_duplicate_versions_and_missing_ready_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            root.mkdir()
            def git(*args):
                return subprocess.check_output(["git", "-C", str(root), *args], text=True, stderr=subprocess.DEVNULL).strip()
            git("init")
            git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-m", "base")
            other = Path(directory) / "other"
            git("worktree", "add", "-b", "other", str(other))
            previous = coord.ROOT
            try:
                coord.ROOT = root
                coord.reserve("0.3.39")
                coord.ROOT = other
                with self.assertRaises(SystemExit): coord.reserve("0.3.39")
                with self.assertRaises(SystemExit): coord.reserve("0.3.40-offline.1")
                git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-m", "ready")
                git("update-ref", "refs/regear/ready/example", git("rev-parse", "HEAD"))
                with self.assertRaises(SystemExit): coord.reserve("0.3.40")
                coord.ROOT = root
                coord.reserve("0.3.40")
            finally:
                coord.ROOT = previous
