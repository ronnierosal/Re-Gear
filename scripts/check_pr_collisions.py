"""Report file-level contention between concurrently open pull requests.

Parallel agents each work on their own branch, so Git only reports a conflict
once two branches reach `main`. This check surfaces the overlap earlier, while
the work is still in flight, so a driver can sequence the merges instead of
discovering the collision during integration.

The analysis is pure: `contended_files` takes an already-collected mapping of
pull request number to changed paths. Only `collect_open_pull_requests` talks to
the GitHub CLI, which keeps the reporting logic testable offline.

Two questions, two reports. `contended_files` answers "which paths do several
open pull requests both edit", which is the merge-sequencing question a driver
asks about the queue as a whole. `path_claims` answers the question an agent has
before it starts: "is anyone already claiming what I am about to touch". That
one deliberately reports a *single* claimant, which contention by definition
never does.

The single-claimant case matters most for a path that does not yet exist on the
base ref. Two pull requests editing one file is contention, and the answer is an
agreed edit order. One pull request creating a file that another agent is about
to create is not contention at all -- it is the same work done twice, and the
answer is to stop and read the other pull request. That distinction is why the
two reports are separate rather than one report with a lower threshold.
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
        "generated output that is no longer tracked; a pull request carrying"
        " dist/ has re-committed a build, which CI refuses, and a rebuild on the"
        " second merge can silently discard the first pull request's frontend"
        " change",
    ),
    (
        "backend/regear/adapters/steamos/commands.py",
        "safety-critical",
        "sole subprocess boundary; overlapping edits can widen executed command"
        " shapes without a single reviewer seeing the combined result",
    ),
    (
        "backend/regear/domain/",
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


#: Why each claim kind is being surfaced. A reader who cannot tell why a line
#: appeared classifies it as noise, and a report that reads as noise stops being
#: run at all -- so the kind carries its own justification.
CLAIM_KINDS: dict[str, str] = {
    "duplicate-work": "claimed but absent from the base ref: another agent is"
    " already building this. Read that pull request before writing anything",
    "contended": "claimed by several pull requests; agree an owner and an edit"
    " order before editing",
    "claimed": "claimed by one pull request that already edits this existing"
    " file; coordinate before overlapping edits",
}


@dataclass(frozen=True, slots=True)
class Claim:
    """Every open pull request claiming one path an agent asked about."""

    path: str
    pull_requests: tuple[int, ...]
    bases: tuple[str, ...]
    kind: str
    risk: str

    def __post_init__(self) -> None:
        if len(self.pull_requests) != len(self.bases):
            raise ValueError("every claiming pull request needs a base ref")

    @property
    def reason(self) -> str:
        return CLAIM_KINDS[self.kind]


def path_claims(
    claims: Mapping[int, Sequence[str]],
    paths: Iterable[str],
    *,
    present: Iterable[str],
    bases: Mapping[int, str] | None = None,
) -> tuple[Claim, ...]:
    """Return every open pull request claiming each of `paths`.

    `present` is the subset of `paths` that already exists on the base ref, so
    the caller supplies the Git lookup and this stays pure. A path absent from
    it is reported as duplicated work rather than contention, whatever the
    number of claimants.

    Paths nobody claims are omitted: the answer to "is anyone claiming this" is
    a list of claimants, and an empty line for every clean path would bury the
    ones that are not.
    """
    bases = bases or {}
    existing = set(present)
    owners: dict[str, set[int]] = {}
    for number, claimed in claims.items():
        for path in claimed:
            owners.setdefault(path, set()).add(int(number))

    found: list[Claim] = []
    for path in dict.fromkeys(paths):
        numbers = tuple(sorted(owners.get(path, ())))
        if not numbers:
            continue
        if path not in existing:
            kind = "duplicate-work"
        elif len(numbers) > 1:
            kind = "contended"
        else:
            kind = "claimed"
        risk, _ = classify(path)
        found.append(
            Claim(
                path,
                numbers,
                tuple(bases.get(number, "") for number in numbers),
                kind,
                risk,
            )
        )
    # Loudest first: duplicated work is the one a reader must not skim past.
    order = {"duplicate-work": 0, "contended": 1, "claimed": 2}
    return tuple(sorted(found, key=lambda item: (order[item.kind], item.path)))


def render_claims(claims: Iterable[Claim], asked: Iterable[str]) -> str:
    claims = tuple(claims)
    asked = tuple(dict.fromkeys(asked))
    if not claims:
        return f"No open pull request claims any of the {len(asked)} path(s) given."
    lines = [f"{len(claims)} of {len(asked)} path(s) are claimed:", ""]
    for claim in claims:
        owners = ", ".join(
            f"#{number}" + (f" (base {base})" if base else "")
            for number, base in zip(claim.pull_requests, claim.bases)
        )
        lines.append(f"- {claim.path} [{claim.kind}] [{claim.risk}]")
        lines.append(f"    claimed by {owners}")
        lines.append(f"    {claim.reason}")
    return "\n".join(lines)


def _run_gh(argv: Sequence[str], timeout: int = 60) -> str:
    completed = subprocess.run(
        (_gh_executable(), *argv),
        capture_output=True,
        check=False,
        shell=False,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"gh {' '.join(argv)} failed: {completed.stderr.strip() or 'unknown error'}"
        )
    return completed.stdout


def _decode_pages(payload: str) -> list[dict]:
    """Flatten `gh api --paginate` output.

    Pagination emits one JSON array per page, concatenated rather than merged,
    and older CLI versions have no --slurp. Decoding the stream keeps every
    page: a partial inventory would read as "no contention" and silently hide
    a claim, which is the failure this reporter exists to prevent.
    """
    decoder = json.JSONDecoder()
    entries: list[dict] = []
    index = 0
    while index < len(payload):
        if payload[index].isspace():
            index += 1
            continue
        page, index = decoder.raw_decode(payload, index)
        if not isinstance(page, list):
            raise RuntimeError(f"expected a JSON array page, got {type(page).__name__}")
        entries.extend(page)
    return entries


def _paginated(path: str, timeout: int = 120) -> list[dict]:
    return _decode_pages(_run_gh(("api", "--paginate", path), timeout=timeout))


def repository_slug() -> str:
    """The owner/name of the checkout's GitHub repository."""
    return json.loads(_run_gh(("repo", "view", "--json", "nameWithOwner")))["nameWithOwner"]


def collect_open_pull_requests(repository: str | None = None) -> dict[int, tuple[str, ...]]:
    """Collect changed paths for every open pull request via the GitHub CLI.

    Both inventories are paginated. `gh pr list --limit` and `gh pr view --json
    files` each cap their results and report the truncated set as if complete,
    so a busy queue or a wide pull request would drop claims without warning.
    """
    repository = repository or repository_slug()
    claims: dict[int, tuple[str, ...]] = {}
    for entry in _paginated(f"repos/{repository}/pulls?state=open&per_page=100"):
        number = int(entry["number"])
        files = _paginated(f"repos/{repository}/pulls/{number}/files?per_page=100")
        claims[number] = tuple(item["filename"] for item in files)
    return claims


def collect_open_pull_request_bases(repository: str | None = None) -> dict[int, str]:
    """Collect the base ref of every open pull request.

    Stacked pull requests legitimately repeat paths, so a reader needs the base
    to tell a stack from a duplicate. This is one extra listing call rather than
    a per-pull-request one, so it costs a page, not a queue.
    """
    repository = repository or repository_slug()
    return {
        int(entry["number"]): str(entry.get("base", {}).get("ref", ""))
        for entry in _paginated(f"repos/{repository}/pulls?state=open&per_page=100")
    }


def _git(*argv: str) -> subprocess.CompletedProcess:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git was not found on PATH")
    return subprocess.run(
        (git, *argv),
        capture_output=True,
        check=False,
        shell=False,
        text=True,
        timeout=30,
    )


def paths_present(paths: Iterable[str], ref: str = "origin/main") -> tuple[str, ...]:
    """Return which of `paths` already exist on `ref`.

    A path missing here is the signal that separates duplicated work from
    contention, so an unreadable ref must never read as "absent": it would
    relabel every ordinary claim as duplicated work and train a reader to
    ignore the loudest line in the report.

    The ref is therefore resolved once, up front, and a failure there raises.
    After that every per-path failure is unambiguous and means absent. The
    earlier version of this decided by matching `git`'s error text, which was
    wrong twice over: the strings differ from what the messages look like, and
    `git` distinguishes a path absent from the tree ("does not exist in") from
    one that is absent from the tree but present in the working copy ("exists
    on disk, but not in"). The second is the ordinary case for a file you are
    about to add -- the exact case this report exists to catch -- and it was
    being raised as a broken lookup. Error text is not a contract; the ref
    check is.
    """
    resolved = _git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if resolved.returncode != 0:
        raise RuntimeError(
            f"could not resolve {ref}: {resolved.stderr.strip() or 'no such ref'}"
        )
    return tuple(
        path
        for path in dict.fromkeys(paths)
        if _git("cat-file", "-e", f"{ref}:{path}").returncode == 0
    )


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
    parser.add_argument(
        "--claimants",
        nargs="+",
        metavar="PATH",
        default=[],
        help="report every open pull request claiming these paths, including a"
        " single claimant, and flag paths absent from --base as duplicated work",
    )
    parser.add_argument(
        "--base",
        default="origin/main",
        help="ref a claimed path must already exist on to count as contention"
        " rather than duplicated work (default: origin/main)",
    )
    parser.add_argument(
        "--present",
        nargs="*",
        metavar="PATH",
        default=None,
        help="treat exactly these paths as existing on the base ref instead of"
        " asking git; for offline use",
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

    if arguments.claimants:
        try:
            present = (
                tuple(arguments.present)
                if arguments.present is not None
                else paths_present(arguments.claimants, arguments.base)
            )
            bases = {} if arguments.claims else collect_open_pull_request_bases()
        except (OSError, RuntimeError, json.JSONDecodeError) as error:
            print(f"Could not resolve claims: {error}", file=sys.stderr)
            return 2
        found = path_claims(
            claims, arguments.claimants, present=present, bases=bases
        )
        print(render_claims(found, arguments.claimants))
        if arguments.strict and found:
            return 1
        return 0

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
