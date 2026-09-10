"""Exercise integration guards against real temporary Git repositories."""
import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "preflight", Path(__file__).resolve().parents[1] / "scripts/check_integration_preflight.py")
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


class IntegrationPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-b", "agent/integration-test")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("commit", "--allow-empty", "-m", "base")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")

    def git(self, *args):
        return subprocess.check_output(("git", *args), cwd=self.root, text=True,
                                       stderr=subprocess.STDOUT).strip()

    def check(self, expected, message=""):
        output = io.StringIO()
        with patch.object(preflight, "ROOT", self.root), contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            self.assertEqual(preflight.main(), expected, output.getvalue())
        self.assertIn(message, output.getvalue())

    def test_agent_prefixes(self):
        for branch in ("codex/integration-test", "claude/integration-test", "agent/integration-test"):
            with self.subTest(branch=branch):
                self.git("branch", "-m", branch)
                self.check(0)

    def test_nonintegration_and_empty_topic_rejected(self):
        for branch in ("main", "claude/feature", "agent/codex-integration-policy", "agent/integration-"):
            with self.subTest(branch=branch):
                self.git("branch", "-m", branch)
                self.check(1, "must use an integration prefix")

    def test_dirty_tree_rejected(self):
        (self.root / "untracked.txt").write_text("pending", encoding="utf-8")
        self.check(1, "working tree is not clean")

    def test_detached_head_rejected(self):
        self.git("checkout", "--detach")
        self.check(1, "detached HEAD")

    def test_stale_main_rejected(self):
        self.git("checkout", "--detach")
        self.git("commit", "--allow-empty", "-m", "new main")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("checkout", "agent/integration-test")
        self.check(1, "does not contain the current origin/main")

    def test_unfinished_operations_rejected(self):
        for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REBASE_HEAD"):
            with self.subTest(marker=marker):
                path = self.root / ".git" / marker
                path.write_text(self.git("rev-parse", "HEAD") + "\n", encoding="utf-8")
                try:
                    self.check(1, "unfinished")
                finally:
                    path.unlink()

    def test_linked_worktree_git_directory(self):
        with tempfile.TemporaryDirectory() as parent:
            linked = Path(parent) / "linked"
            self.git("worktree", "add", "-b", "claude/integration-linked", str(linked))
            original = self.root
            self.root = linked
            try:
                self.check(0)
                marker = Path(self.git("rev-parse", "--git-dir")) / "MERGE_HEAD"
                marker.write_text(self.git("rev-parse", "HEAD") + "\n", encoding="utf-8")
                try:
                    self.check(1, "unfinished merge")
                finally:
                    marker.unlink()
            finally:
                self.root = original
