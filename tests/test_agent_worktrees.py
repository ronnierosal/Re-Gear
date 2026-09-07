import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "agent_worktrees", Path(__file__).resolve().parents[1] / "scripts/setup_agent_worktrees.py"
)
worktrees = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worktrees)


class AgentWorktreeLayoutTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.layout = Path(self.directory.name) / "Re-Gear"
        self.repo = self.layout / "main"
        self.repo.mkdir(parents=True)
        self.git("init", "-b", "main")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-m", "base")
        previous = worktrees.ROOT
        worktrees.ROOT = self.repo
        self.addCleanup(setattr, worktrees, "ROOT", previous)

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], text=True, stderr=subprocess.DEVNULL).strip()

    def slots(self, scope="workspace"):
        _, actions = worktrees.describe_layout(self.layout, scope)
        return {slot for slot, _, _ in actions}

    def test_existing_checkout_is_recognised_and_agent_slots_are_created_once(self):
        self.assertEqual(self.slots(), {"codex", "claude"})

        worktrees.create_worktree(self.layout / "claude", "agent/claude-workspace")
        self.assertTrue((self.layout / "claude").is_dir())
        self.assertEqual(self.slots(), {"codex"})

        worktrees.create_worktree(self.layout / "codex", "agent/codex-workspace")
        self.assertEqual(self.slots(), set())

    def test_occupied_and_claimed_paths_are_left_untouched(self):
        occupied = self.layout / "codex"
        occupied.mkdir()
        (occupied / "codex-work-in-progress.txt").write_text("keep me", encoding="utf-8")

        # A directory that is not a worktree of this repository is never a create target.
        self.assertNotIn("codex", self.slots())
        self.assertEqual((occupied / "codex-work-in-progress.txt").read_text(encoding="utf-8"), "keep me")

        # git itself must refuse rather than the script forcing the checkout.
        with self.assertRaises(SystemExit):
            worktrees.create_worktree(occupied, "agent/codex-workspace")
        self.assertEqual((occupied / "codex-work-in-progress.txt").read_text(encoding="utf-8"), "keep me")

    def test_branch_checked_out_elsewhere_is_reported_not_reclaimed(self):
        elsewhere = Path(self.directory.name) / "elsewhere"
        self.git("worktree", "add", "-b", "agent/claude-workspace", str(elsewhere))

        self.assertNotIn("claude", self.slots())
        state, detail = worktrees.slot_state(self.layout / "claude", "agent/claude-workspace", worktrees.worktrees())
        self.assertEqual(state, "branch-elsewhere")
        self.assertTrue(worktrees.same_path(detail, elsewhere))

    def test_scope_names_the_agent_branch(self):
        self.assertEqual(worktrees.agent_branch("claude", "dock-telemetry"), "agent/claude-dock-telemetry")
        self.assertEqual(worktrees.agent_branch("main", "dock-telemetry"), "main")


if __name__ == "__main__":
    unittest.main()
