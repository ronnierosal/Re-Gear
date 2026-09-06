#!/usr/bin/env python3
"""Reject unsafe Git state before a Re-Gear integration."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *args), cwd=ROOT, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )


def value(*args: str) -> str:
    result = git(*args)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def main() -> int:
    failures: list[str] = []
    try:
        branch = value("branch", "--show-current")
        git_dir = Path(value("rev-parse", "--git-dir"))
    except RuntimeError as error:
        print(f"integration preflight: {error}", file=sys.stderr)
        return 2

    if not branch:
        failures.append("detached HEAD is not an integration workspace")
    elif not branch.startswith("codex/integration-"):
        failures.append(f"branch {branch!r} is not named codex/integration-*")
    if not git_dir.is_absolute():
        git_dir = ROOT / git_dir
    for marker, description in {
        "CHERRY_PICK_HEAD": "an unfinished cherry-pick",
        "MERGE_HEAD": "an unfinished merge",
        "REBASE_HEAD": "an unfinished rebase",
    }.items():
        if (git_dir / marker).exists():
            failures.append(description)
    if value("status", "--porcelain"):
        failures.append("working tree is not clean")
    if git("diff", "--name-only", "--diff-filter=U").stdout.strip():
        failures.append("unresolved conflict paths are present")
    if git("merge-base", "--is-ancestor", "origin/main", "HEAD").returncode:
        failures.append("integration branch does not contain the current origin/main")

    if failures:
        print("integration preflight failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(f"integration preflight passed: {branch} at {value('rev-parse', '--short', 'HEAD')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
