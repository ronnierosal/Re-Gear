"""Report file-level contention between concurrently open pull requests.

Parallel agents each work on their own branch, so Git only reports a conflict
once two branches reach `main`. This check surfaces the overlap earlier, while
the work is still in flight, so a driver can sequence the merges instead of
discovering the collision during integration.

The analysis is pure: `contended_files` takes an already-collected mapping of
pull request number to changed paths. Only `collect_open_pull_requests` talks to
the GitHub CLI, which keeps the reporting logic testable offline.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


def _gh_executable() -> str:
    """Resolve the GitHub CLI, which lives at different paths per platform."""
    resolved = shutil.which("gh")
    if resolved is None:
        raise RuntimeError("GitHub CLI (gh) was not found on PATH")
    return resolved

#: Paths whose concurrent edits are more damaging than an ordinary conflict.
#: Each entry maps a path prefix to the reason a driver should care.
RISK_CLASSES: tuple[tuple[str, str, str], ...] = (
    (
        "dist/",
        "build-artifact",
        "generated output verified byte-for-byte by CI; a rebuild on the second"
        " merge can silently discard the first pull request's frontend change",
    ),
    (
        "backend/hdm/adapters/steamos/commands.py",
        "safety-critical",
        "sole subprocess boundary; overlapping edits can widen executed command"
        " shapes without a single reviewer seeing the combined result",
    ),
    (
        "backend/hdm/domain/",
        "safety-critical",
        "pure decision layer; overlapping edits can compose into unreviewed"
        " state-machine behavior",
    ),
    (
        "main.py",
        "integration-point",
        "single plugin entry point; overlapping edits converge on one class",
    ),
    (
        "docs/WORK_QUEUE.md",
        "coordination",
        "ownership ledger; concurrent edits contest the record used to prevent"
        " this very class of collision",
    ),
    (
        "docs/CURRENT_STATE.md",
        "coordination",
        "deployment snapshot; concurrent edits produce contradictory claims",
    ),
    (
        "docs/OPERATOR_HANDOFF.md",
        "coordination",
        "handoff record; concurrent edits produce contradictory claims",
    ),
)


@dataclass(frozen=True, slots=True)
class Collision:
    """One path claimed by more than one open pull request."""

    path: str
    pull_requests: tuple[int, ...]
    risk: str
    reason: str

    @property
    def claim_count(self) -> int:
        return len(self.pull_requests)


def classify(path: str) -> tuple[str, str]:
    """Return the risk label and reason for `path`."""
    for prefix, risk, reason in RISK_CLASSES:
        if path == prefix or path.startswith(prefix):
            return risk, reason
    return "shared", "overlapping edits require a merge decision"


def contended_files(claims: Mapping[int, Sequence[str]]) -> tuple[Collision, ...]:
    """Return every path claimed by two or more pull requests.

    Ordering is deterministic: highest contention first, then path, so the
    report is stable enough to diff between runs.
    """
    owners: dict[str, set[int]] = {}
    for number, paths in claims.items():
        for path in paths:
            owners.setdefault(path, set()).add(int(number))
    collisions = []
    for path, numbers in owners.items():
        if len(numbers) < 2:
            continue
        risk, reason = classify(path)
        collisions.append(Collision(path, tuple(sorted(numbers)), risk, reason))
    return tuple(
        sorted(collisions, key=lambda item: (-item.claim_count, item.path))
    )


def _run_gh(argv: Sequence[str]) -> str:
    completed = subprocess.run(
        (_gh_executable(), *argv),
        capture_output=True,
        check=False,
        shell=False,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"gh {' '.join(argv)} failed: {completed.stderr.strip() or 'unknown error'}"
        )
    return completed.stdout


def collect_open_pull_requests(limit: int = 200) -> dict[int, tuple[str, ...]]:
    """Collect changed paths for every open pull request via the GitHub CLI."""
    listing = json.loads(
        _run_gh(("pr", "list", "--state", "open", "--limit", str(limit), "--json", "number"))
    )
    claims: dict[int, tuple[str, ...]] = {}
    for entry in listing:
        number = int(entry["number"])
        detail = json.loads(
            _run_gh(("pr", "view", str(number), "--json", "files"))
        )
        claims[number] = tuple(item["path"] for item in detail.get("files", ()))
    return claims


def render(collisions: Iterable[Collision]) -> str:
    collisions = tuple(collisions)
    if not collisions:
        return "No file-level contention between open pull requests."
    lines = [f"{len(collisions)} contended file(s) across open pull requests:", ""]
    for collision in collisions:
        owners = ", ".join(f"#{number}" for number in collision.pull_requests)
        lines.append(f"- {collision.path} [{collision.risk}]")
        lines.append(f"    claimed by {collision.claim_count}: {owners}")
        lines.append(f"    {collision.reason}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--claims",
        help="read a JSON object of {pull request number: [paths]} instead of"
        " querying the GitHub CLI",
    )
    parser.add_argument(
        "--risk",
        action="append",
        default=[],
        help="fail only when a contended path carries this risk label; repeatable",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero when contention is reported",
    )
    arguments = parser.parse_args(argv)

    if arguments.claims:
        with open(arguments.claims, encoding="utf-8") as handle:
            raw = json.load(handle)
        claims = {int(key): tuple(value) for key, value in raw.items()}
    else:
        try:
            claims = collect_open_pull_requests()
        except (OSError, RuntimeError, json.JSONDecodeError) as error:
            print(f"Could not collect open pull requests: {error}", file=sys.stderr)
            return 2

    collisions = contended_files(claims)
    if arguments.risk:
        selected = set(arguments.risk)
        reportable = tuple(item for item in collisions if item.risk in selected)
    else:
        reportable = collisions
    print(render(reportable))
    if arguments.strict and reportable:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
