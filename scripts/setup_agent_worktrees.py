"""Create and verify the shared multi-agent worktree layout without disturbing other agents.

Layout under <workspace>/Re-Gear:

    main/    integration checkout tracking the integration branch
    codex/   ChatGPT/Codex dedicated worktree
    claude/  Claude dedicated worktree

Every action is additive. This script never deletes, moves, resets, cleans,
force-checkouts, or rewrites anything, and it never inspects or edits the
contents of another agent's slot.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_BRANCH = "main"
AGENT_SLOTS = ("codex", "claude")
SLOTS = ("main", *AGENT_SLOTS)


def git(*args, cwd=None, check=True):
    result = subprocess.run(
        ["git", "-C", str(cwd or ROOT), *args],
        capture_output=True,
        text=True,
    )
    if check and result.returncode:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def git_out(*args, cwd=None):
    return git(*args, cwd=cwd).stdout.strip()


def resolves(revision, cwd=None):
    return git("rev-parse", "--verify", "--quiet", revision, cwd=cwd, check=False).returncode == 0


def worktrees(cwd=None):
    """Parsed `git worktree list --porcelain` records for the current repository."""
    records = []
    current: dict[str, object] = {}
    for line in git_out("worktree", "list", "--porcelain", cwd=cwd).splitlines():
        if not line:
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current["path"] = Path(value)
        elif key == "branch":
            current["branch"] = value.rpartition("refs/heads/")[2] or value
        else:
            current[key] = value or True
    if current:
        records.append(current)
    return records


def same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def branch_owner(branch: str, records) -> Path | None:
    for record in records:
        if record.get("branch") == branch:
            return record["path"]
    return None


def default_layout_root() -> Path | None:
    """The layout root is the parent of the checkout only when it already sits in a slot."""
    if ROOT.name in SLOTS:
        return ROOT.parent
    return None


def agent_branch(slot: str, scope: str) -> str:
    return INTEGRATION_BRANCH if slot == "main" else f"agent/{slot}-{scope}"


def start_point() -> str:
    for candidate in (f"origin/{INTEGRATION_BRANCH}", INTEGRATION_BRANCH):
        if resolves(candidate):
            return candidate
    return "HEAD"


def slot_state(path: Path, branch: str, records):
    """Classify a slot without reading anything inside another agent's directory."""
    registered = next((r for r in records if same_path(r["path"], path)), None)
    if registered is not None:
        return "registered", registered
    if path.exists():
        if not path.is_dir():
            return "blocked-file", None
        if any(path.iterdir()):
            return "occupied", None
        return "empty-directory", None
    owner = branch_owner(branch, records)
    if owner is not None:
        return "branch-elsewhere", owner
    return "missing", None


def describe_repository() -> list[str]:
    records = worktrees()
    status = git_out("status", "--porcelain")
    lines = [
        f"repository      {ROOT}",
        f"branch          {git_out('rev-parse', '--abbrev-ref', 'HEAD')}",
        f"head            {git_out('rev-parse', '--short', 'HEAD')}",
        f"worktree state  {'dirty (' + str(len(status.splitlines())) + ' paths)' if status else 'clean'}",
        "worktrees:",
    ]
    for record in records:
        lines.append(f"  {record['path']}  [{record.get('branch', 'detached')}]")
    return lines


def describe_layout(layout_root: Path, scope: str) -> tuple[list[str], list[tuple[str, Path, str]]]:
    """Report each slot and return the additive work that would create the missing ones."""
    records = worktrees()
    lines = [f"layout root     {layout_root}", "slots:"]
    actions: list[tuple[str, Path, str]] = []
    for slot in SLOTS:
        path = layout_root / slot
        branch = agent_branch(slot, scope)
        state, detail = slot_state(path, branch, records)
        if state == "registered":
            note = f"already a worktree on [{detail.get('branch', 'detached')}]"
        elif state == "occupied":
            note = "path exists with contents and is not a worktree of this repository; left untouched"
        elif state == "blocked-file":
            note = "path exists as a file; left untouched"
        elif state == "branch-elsewhere":
            note = f"branch {branch} is already checked out at {detail}; left untouched"
        else:
            note = f"would create worktree on [{branch}]"
            actions.append((slot, path, branch))
        lines.append(f"  {slot:<7} {path}")
        lines.append(f"          {state}: {note}")
    return lines, actions


def create_worktree(path: Path, branch: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if resolves(f"refs/heads/{branch}"):
        args = ["worktree", "add", str(path), branch]
    elif resolves(f"refs/remotes/origin/{branch}"):
        args = ["worktree", "add", "--track", "-b", branch, str(path), f"origin/{branch}"]
    else:
        args = ["worktree", "add", "-b", branch, str(path), start_point()]
    result = git(*args, check=False)
    if result.returncode:
        raise SystemExit(f"Refusing to continue: {result.stderr.strip()}")
    print(f"created {path} on [{branch}]")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["inspect", "plan", "apply"])
    parser.add_argument(
        "--layout-root",
        type=Path,
        help="Directory that holds main/, codex/ and claude/. Required unless this checkout already sits in a slot.",
    )
    parser.add_argument(
        "--scope",
        default="workspace",
        help="Task scope used in agent branch names, for example agent/claude-<scope>.",
    )
    parser.add_argument(
        "--slot",
        choices=SLOTS,
        action="append",
        help="Limit apply to these slots. Repeatable. Defaults to every missing slot.",
    )
    args = parser.parse_args()

    for line in describe_repository():
        print(line)

    if args.action == "inspect" and args.layout_root is None and default_layout_root() is None:
        print("\nNo layout root given and this checkout does not sit in a main/codex/claude slot.")
        return 0

    layout_root = args.layout_root or default_layout_root()
    if layout_root is None:
        raise SystemExit(
            "Pass --layout-root <path-to>/Re-Gear. This checkout is not inside an existing slot, "
            "and this script never moves an existing checkout."
        )

    print()
    lines, actions = describe_layout(layout_root.expanduser(), args.scope)
    for line in lines:
        print(line)

    if args.action != "apply":
        print()
        print(f"{len(actions)} slot(s) would be created." if actions else "Layout is already complete.")
        return 0

    wanted = [action for action in actions if not args.slot or action[0] in args.slot]
    if not wanted:
        print("\nNothing to create.")
        return 0
    print()
    for _, path, branch in wanted:
        create_worktree(path, branch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
