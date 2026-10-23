"""Read-only owner-work discovery extracted from PR458/PR550.

Uses the current canonical parser/client unchanged. This is not a reconciler,
writer, reviewer router, worker launcher, hardware runner or merge driver. The
only CLI is `next`: JSON suggestions, never execution or claim acceptance.
No workflow installs or calls this module. Existing gates remain authoritative.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import github_coordination as gc  # noqa: E402

REQUIRED_CHECKS = ("foundation", "privileged-user-delivery")
COORDINATION_CHECKS = {"gate", "update", "reconcile"}
HOLD_LABELS = {"merge-hold", "hold", "needs-decision", "blocked"}
IMPLEMENTING = {"claimed", "in-progress"}
# Preserve stack compatibility without admitting a state into canonical policy.
# Current main rejects review-requested; only a separate schema change may enable it.
REPAIR_STATES = {"pr-open", "software-validated", "ready-to-merge", "review-requested"}
PRIORITY = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
MAX_CHECK_PAGES = 20


def priority(row):
    return min((PRIORITY[label] for label in row["labels"] if label in PRIORITY), default=9), row["number"]


def checks_state(check_runs):
    """Software-check facts only; never certify coordination or merge readiness.

    Pending/unknown evidence takes precedence over an earlier failure so another
    run on the same head is not interrupted by a premature repair suggestion.
    """
    if not isinstance(check_runs, list) or any(not isinstance(r, dict) for r in check_runs):
        return {"state": "pending", "url": None}
    runs = [r for r in check_runs if r.get("name") not in COORDINATION_CHECKS]
    names = {r.get("name") for r in runs}
    known = {"success", "failure", "timed_out", "cancelled", "action_required",
             "startup_failure", "skipped", "neutral", "stale"}
    if (not all(name in names for name in REQUIRED_CHECKS)
            or any(r.get("status") != "completed" or r.get("conclusion") not in known for r in runs)):
        return {"state": "pending", "url": None}
    failed = {"failure", "timed_out", "cancelled", "action_required", "startup_failure", "stale"}
    if (any(r["conclusion"] in failed for r in runs)
            or any(r["conclusion"] != "success" for r in runs if r.get("name") in REQUIRED_CHECKS)):
        return {"state": "failure", "url": None}
    return {"state": "success", "url": next(r.get("html_url") for r in runs if r.get("name") == "foundation")}


class GitHubFacts:
    """GET-only facts for discovery; no publication or execution helpers."""

    def __init__(self, github):
        self.github = github

    def checks(self, head):
        gc.require(isinstance(head, str) and gc.SHA.fullmatch(head), "invalid candidate head")
        runs = []
        for page in range(1, MAX_CHECK_PAGES + 1):
            data = self.github.api(f"commits/{head}/check-runs?per_page=100&page={page}")
            items = data.get("check_runs") if isinstance(data, dict) else None
            if not isinstance(items, list) or len(items) > 100:
                return {"state": "pending", "url": None}
            runs.extend(items)
            if len(items) < 100:
                return checks_state(runs)
        return {"state": "pending", "url": None}


def gather_rows(github, with_faults=True):
    """Fresh canonical records and unique current PR evidence; all reads only.

    Inventory/read failure aborts discovery rather than suggesting a competing
    claim using incomplete ownership facts. No cached or stale fallback exists.
    """
    default = github.api("").get("default_branch")
    gc.require(gc.nonempty(default), "default branch unavailable")
    issues = github.pages("issues?state=open")
    pulls = github.pages("pulls?state=open")
    source, rows = GitHubFacts(github), []
    for issue in issues:
        labels = {l["name"] for l in issue.get("labels", [])}
        if "pull_request" in issue or "agent-task" not in labels:
            continue
        record = gc.parse(issue.get("body"))  # Current main schema and CRLF fix.
        matches = []
        for candidate in pulls:
            try:
                if gc.task_number(candidate.get("body")) == issue["number"]:
                    matches.append(candidate)
            except ValueError:
                continue
        pr = matches[0] if len(matches) == 1 else None
        row = dict(number=issue["number"], record=record, labels=sorted(labels), pr=pr, faults=[])
        if len(matches) > 1:
            row["faults"].append("multiple open PRs for task")
        if with_faults and pr is not None and record["status"] in gc.ACTIVE:
            detail = github.api(f"pulls/{pr['number']}")
            try:
                gc.require(gc.task_number(detail.get("body")) == issue["number"], "PR linkage changed")
                gc.require(detail.get("state") == "open", "PR is no longer open")
                gc.require(detail["head"]["ref"] == record["branch"], "task branch changed")
                gc.require(detail["base"]["ref"] == default, "candidate is stacked")
                gc.require(all(detail[side]["repo"]["full_name"] == github.repo for side in ("head", "base")),
                           "candidate repository changed")
                gc.require(all(isinstance(detail[side]["sha"], str) and gc.SHA.fullmatch(detail[side]["sha"])
                               for side in ("head", "base")), "invalid candidate revisions")
            except (ValueError, KeyError, TypeError):
                row["pr"] = None
                row["faults"].append("fresh PR identity or linkage unavailable")
                rows.append(row)
                continue
            row["pr"] = detail
            row["labels"] = sorted(labels | {l["name"] for l in detail.get("labels", [])})
            head, base = detail["head"]["sha"], detail["base"]["sha"]
            row["checks"] = source.checks(head)
            row["behind_by"] = github.api(f"compare/{base}...{head}").get("behind_by")
            if row["checks"]["state"] == "failure":
                row["faults"].append("required CI failed")
            if detail.get("mergeable") is False:
                row["faults"].append("PR has merge conflicts")
        rows.append(row)
    return rows


def next_actions(agent, session, tasks):
    """Bounded owner software work only; suggestions confer no write authority."""
    work = []
    mine = [t for t in tasks if t["record"]["owner"] == session]
    busy = [t for t in mine if t["record"]["status"] in IMPLEMENTING]
    for t in sorted(busy, key=priority):
        if t["record"]["agent"] == agent and not HOLD_LABELS.intersection(t["labels"]):
            work.append(dict(kind="implement", task=t["number"], detail=t["record"]["branch"]))
    repair_task = None
    if not busy:
        for t in sorted(mine, key=priority):
            r, pr = t["record"], t.get("pr")
            if (r["agent"] != agent or r["status"] not in REPAIR_STATES or r["status"] not in gc.ACTIVE
                    or HOLD_LABELS.intersection(t["labels"]) or not pr or pr.get("draft")
                    or pr.get("state") != "open" or pr["head"]["ref"] != r["branch"]):
                continue
            checks = (t.get("checks") or {}).get("state")
            if checks not in {"success", "failure"}:
                continue
            reasons = ["required CI failed"] if checks == "failure" else []
            behind = t.get("behind_by")
            if ((type(behind) is int and behind > 0) or "PR has merge conflicts" in t.get("faults", [])):
                reasons.append("base refresh required")
            if reasons:
                head, base = pr["head"]["sha"], pr["base"]["sha"]
                if not all(isinstance(sha, str) and gc.SHA.fullmatch(sha) for sha in (head, base)):
                    continue
                repair_task = t["number"]
                work.append(dict(kind="rework", task=t["number"], pr=pr["number"], head=head, base=base,
                                 reasons=reasons, detail=(
                                     "Repair this owned software candidate; merge the current base normally "
                                     "if needed (no rebase/force-push), then rerun checks and independent "
                                     "exact-head/base review. Preserve ownership, holds and hardware gates.")))
                break
    waiting = sum(t["record"]["status"] in gc.ACTIVE - IMPLEMENTING for t in mine)
    if not busy and repair_task is None and waiting <= 1:
        active = [t["record"] for t in tasks if t["record"]["status"] in gc.ACTIVE]
        for t in sorted(tasks, key=priority):
            r = t["record"]
            if (r["status"] != "backlog" or r["owner"] is not None or r["agent"] != agent
                    or r["class"] not in {"A", "B"} or r["hardware"] != "not-required"
                    or HOLD_LABELS.intersection(t["labels"])):
                continue
            if any(gc.overlap(r["scope"], other["scope"]) or r["branch"] == other["branch"] for other in active):
                continue
            work.append(dict(kind="claim", task=t["number"], detail=f"claim at revision {r['revision']} then implement"))
            break
    return work


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["next"])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--agent", required=True, choices=["codex-cloud", "codex-local", "claude"])
    parser.add_argument("--session", required=True)
    args = parser.parse_args()
    gc.require(gc.ID.fullmatch(args.session), "valid owner session required")
    github = gc.GitHub(args.repo)
    print(json.dumps(next_actions(args.agent, args.session, gather_rows(github)), indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, gc.subprocess.CalledProcessError):
        print("owner discovery unavailable; no work authorized", file=sys.stderr)
        sys.exit(1)
