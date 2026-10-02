"""Level-triggered task reconciler for the GitHub coordination records.

Every run re-reads live GitHub state and moves each managed task as far as its
evidence allows, so a cancelled, replaced or duplicated run loses nothing: the
next run recomputes the same result. The planner is pure and takes a snapshot;
`GitHubFacts` gathers that snapshot and `apply` performs the actions through
the same guarded issue write the dispatch workflow uses. Record writers are
serialized in one concurrency group; agents' durable intents arrive as
`regear-update` comments, which no cancelled run can lose.

It automates handoffs only. Owners, independent reviewers, exact head/base
evidence, merge classes and hardware gates are unchanged, and the reconciler
never runs PR code, hardware commands, installs or releases. It is not an
identity service: like the dispatch workflow, it trusts repository writers.
"""
import argparse
import copy
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import github_coordination as gc  # noqa: E402

REQUIRED_CHECKS = ("foundation", "privileged-user-delivery")
# Check runs that the coordination workflows create for themselves.
COORDINATION_CHECKS = {"gate", "update", "reconcile"}
UPDATE_BLOCK = re.compile(r"^```regear-update[ \t]*\r?\n(.*?)^```[ \t]*$", re.M | re.S)
ACK = re.compile(r"<!-- regear:update-ack task=(\d+) comment=(\d+) -->")
REVIEW_BLOCK = re.compile(r"^```regear-review[ \t]*\r?\n(.*?)^```[ \t]*$", re.M | re.S)
MARKER = re.compile(r"<!-- regear:([a-z-]+) task=(\d+) head=([0-9a-f]{40}) base=([0-9a-f]{40}) -->")
WRITERS = {"admin", "maintain", "write"}
# Cross-agent review: the implementing family never reviews itself.
REVIEWER_FOR = {"claude": "codex-cloud", "codex-cloud": "claude", "codex-local": "claude"}
AUTO_MERGE_CLASSES = {"A"}
# Labels can only stop automation; they never grant authority.
HOLD_LABELS = {"merge-hold", "hold", "needs-decision"}
# Merge-authority surfaces: a PR touching any of these is never auto-merged,
# so coordination changes cannot bootstrap their own integration.
PROTECTED_PATHS = (".github/", "scripts/github_coordination.py", "scripts/coordination_orchestrator.py",
                   "AGENTS.md", "CLAUDE.md", "docs/CONTINUOUS_DEVELOPMENT.md", "docs/AGENT_COORDINATION.md",
                   "contracts/coordination-workers.json")
MIRRORS = ("task:", "agent:", "risk:", "hardware:")
TYPE_LABELS = {"bug", "enhancement", "documentation", "refactor", "test", "chore", "security"}
IMPLEMENTING = {"claimed", "in-progress", "changes-requested"}
WAITING = {"pr-open", "software-validated", "review-requested", "hardware-required",
           "hardware-validated", "ready-to-merge", "blocked"}
STUCK_HOURS = {"claimed": 168, "in-progress": 168, "pr-open": 24, "software-validated": 1,
               "review-requested": 24, "changes-requested": 48, "ready-to-merge": 6,
               "hardware-required": 72, "hardware-validated": 24, "blocked": 168}
PRIORITY = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def marker(kind, number, head, base):
    return f"<!-- regear:{kind} task={number} head={head} base={base} -->"


def has_marker(comments, kind, number, head, base):
    return any(m.groups() == (kind, str(number), head, base)
               for c in comments for m in MARKER.finditer(c.get("body") or ""))


def candidate_of(pr):
    return pr["head"]["sha"], pr["base"]["sha"]


def bound(record, name, head, base):
    item = record.get(name) or {}
    return item.get("head") == head and item.get("base") == base


def checks_state(check_runs):
    """Required CI for one exact head: success only when every required check
    passed and nothing else on the head failed or is still running."""
    runs = [r for r in check_runs if r.get("name") not in COORDINATION_CHECKS]
    by_name = {}
    for run in runs:
        by_name.setdefault(run.get("name"), []).append(run)
    # Allowlist, not denylist: startup_failure, stale or any future terminal
    # conclusion must never read as green.
    if any(r.get("status") == "completed" and r.get("conclusion") not in {"success", "neutral", "skipped"}
           for r in runs):
        return {"state": "failure", "url": None}
    if any(r.get("status") != "completed" for r in runs) or not all(name in by_name for name in REQUIRED_CHECKS):
        return {"state": "pending", "url": None}
    if not all(all(r.get("conclusion") == "success" for r in by_name[name]) for name in REQUIRED_CHECKS):
        return {"state": "failure", "url": None}
    return {"state": "success", "url": by_name[REQUIRED_CHECKS[0]][0].get("html_url")}


def review_submissions(comments, number):
    """Structured `regear-review` comments from repository writers, oldest first.

    Free-text comments, bots and non-writers are never review evidence."""
    found = []
    for comment in comments:
        if comment.get("is_bot") or comment.get("author_permission") not in WRITERS:
            continue
        for match in REVIEW_BLOCK.finditer(comment.get("body") or ""):
            try:
                item = gc.load_record(match.group(1))
            except (ValueError, TypeError):
                continue
            if not isinstance(item, dict) or item.get("task") != number:
                continue
            if item.get("result") not in {"PASS", "FAIL"}:
                continue
            if item.get("agent") not in REVIEWER_FOR:
                continue
            if not (isinstance(item.get("head"), str) and gc.SHA.fullmatch(item["head"])
                    and isinstance(item.get("base"), str) and gc.SHA.fullmatch(item["base"])
                    and isinstance(item.get("reviewer"), str) and gc.ID.fullmatch(item["reviewer"])):
                continue
            found.append(dict(item, url=comment["html_url"], created_at=comment.get("created_at", "")))
    return sorted(found, key=lambda item: item["created_at"])


def latest_review(record, comments, number, head, base):
    """Newest valid exact-candidate review by someone other than the owner,
    from the requested opposite agent family (cooperative declared identity)."""
    family = (record.get("review_request") or {}).get("reviewer_agent", REVIEWER_FOR[record["agent"]])
    valid = [s for s in review_submissions(comments, number)
             if s["head"] == head and s["base"] == base and s["reviewer"] != record["owner"]
             and s["agent"] == family]
    return valid[-1] if valid else None


def drop_candidate_evidence(record):
    for name in ("software", "review", "review_request", "hardware_evidence"):
        record.pop(name, None)


def hardware_card(number, record, pr, review):
    head, base = candidate_of(pr)
    return "\n".join([
        marker("hardware", number, head, base),
        f"## Ready for hardware: Task #{number}",
        "",
        f"- PR: #{pr['number']} ({pr['html_url']})",
        f"- Exact head / base: `{head}` / `{base}`",
        f"- Class: {record['class']} · owner `{record['owner']}`",
        f"- Software PASS: {record['software']['url']}",
        f"- Independent review PASS: {review['url']} (`{review['reviewer']}`)",
        "- Build: the controlled CI artifact for this exact head, or one local package under docs/CHAT_COORDINATION.md",
        "- Test, expected result, initial state, evidence and stop conditions: this issue's"
        " **Regression and hardware plan**",
        "- Class D additionally requires `procedure_approval` before any trial",
        "- Rollback: retain and verify the installed rollback ZIP, SHA-256 and configuration before installing",
        "",
        "Local Codex: `python scripts/github_coordination.py queue` confirms eligibility. Record "
        "PASS/FAIL/INCONCLUSIVE as `hardware_evidence` through the Agent coordination workflow.",
    ])


def update_intents(number, comments):
    """Unacknowledged `regear-update` comments from writers, oldest first.

    Comments are durable agent intent: unlike a pending workflow dispatch,
    GitHub cannot cancel them, and the serialized reconciler applies them
    with the same validation as the dispatch workflow."""
    acked = {int(m.group(2)) for c in comments for m in ACK.finditer(c.get("body") or "")
             if int(m.group(1)) == number}
    pending = []
    for comment in sorted(comments, key=lambda c: c.get("created_at") or ""):
        match = UPDATE_BLOCK.search(comment.get("body") or "")
        if not match or comment.get("id") in acked or comment.get("is_bot"):
            continue
        pending.append((comment, match.group(1)))
    return pending


def apply_intents(number, record, facts):
    """Apply pending intents in order; returns (record, ack comments)."""
    current, acks = record, []
    for comment, text in update_intents(number, facts.get("issue_comments") or []):
        try:
            gc.require(comment.get("author_permission") in WRITERS, "update requires a repository writer")
            intent = gc.load_record(text)
            gc.require(isinstance(intent, dict) and set(intent) == {"task", "expected_revision", "record"},
                       "update needs exactly task, expected_revision and record")
            gc.require(intent["task"] == number, "update names a different task")
            gc.require(type(intent["expected_revision"]) is int, "invalid expected_revision")
            current = gc.update(current, intent["record"], intent["expected_revision"], facts.get("others", []))
            verdict = f"APPLIED as revision {current['revision']} (`{current['status']}`)"
        except (ValueError, TypeError, KeyError) as exc:
            verdict = f"REFUSED: {exc}. Re-read the record and post a new update."
        acks.append({"kind": "comment", "target": number, "body": "\n".join([
            f"<!-- regear:update-ack task={number} comment={comment['id']} -->",
            f"Coordination update {comment['html_url']}: {verdict}"])})
    return current, acks


def label_plan(record, issue_labels, pr_labels=None):
    """Desired label sets, or None where nothing changes.

    One label per mirror namespace from the record; descriptive labels are
    kept. The PR also carries the issue's type, area and priority labels.
    Labels are a readable mirror only and never grant authority."""
    mirror = [f"task:{record['status']}", f"agent:{record['agent']}",
              f"risk:{record['class']}", f"hardware:{record['hardware']}"]

    def desired(current, extra):
        keep = [label for label in current if not label.startswith(MIRRORS)]
        return list(dict.fromkeys(keep + extra + mirror))
    issue = desired(issue_labels, ["agent-task"])
    result = [issue if set(issue) != set(issue_labels) else None, None]
    if pr_labels is not None:
        carried = [label for label in issue_labels
                   if label in TYPE_LABELS or label.startswith("area:") or re.fullmatch(r"P\d", label)]
        wanted = desired(pr_labels, carried)
        result[1] = wanted if set(wanted) != set(pr_labels) else None
    return tuple(result)


def plan(number, record, facts):
    """Pure transition planner for one task.

    `facts` keys: pr (open PR or None), pr_error, checks ({state,url}),
    comments (PR comments with author_permission/is_bot), issue_comments,
    labels (issue + PR), merged_pr, gate_error (check_pr on a would-be
    ready-to-merge record), behind_by, mergeable, others (other task records).
    Returns (new_record_or_None, side_actions, notes)."""
    old = record
    record, actions = apply_intents(number, record, facts)
    notes = []
    if record is not old:
        # Explicit agent intent wins this run; automatic steps follow next run.
        return record, actions, notes
    new = copy.deepcopy(record)
    status = new["status"]
    if status in gc.TERMINAL or status == "backlog":
        return None, actions, notes

    merged = facts.get("merged_pr")
    if merged:
        new["status"] = "merged"
        new["integration"] = {"pr": merged["number"], "sha": merged["merge_commit_sha"], "url": merged["html_url"]}
        return finish(old, new, facts), actions, notes

    pr = facts.get("pr")
    if facts.get("pr_error"):
        notes.append(facts["pr_error"])
        return None, actions, notes
    if pr is None:
        return None, actions, notes
    head, base = candidate_of(pr)
    if pr["head"]["ref"] != new["branch"]:
        notes.append("task/PR branch mismatch")
        return None, actions, notes

    # A new head or base invalidates every exact-candidate result.
    if new["status"] in gc.CANDIDATE and not bound(new, "software", head, base):
        new["status"] = "pr-open"
        drop_candidate_evidence(new)
        notes.append("candidate changed; software/review evidence invalidated")

    if new["status"] in {"claimed", "in-progress"} and not pr.get("draft"):
        new["status"] = "pr-open"

    checks = facts.get("checks") or {"state": "pending"}
    if new["status"] == "pr-open" and not pr.get("draft"):
        if checks["state"] == "success":
            new["status"] = "software-validated"
            new["software"] = {"result": "PASS", "head": head, "base": base, "url": checks["url"]}
        elif checks["state"] == "failure":
            notes.append("required CI failed on the exact head")

    comments = facts.get("comments") or []
    # The newest valid exact-candidate review governs every candidate state, so
    # a FAIL posted after readiness withdraws merge or hardware authorization.
    if new["status"] in gc.CANDIDATE and not pr.get("draft"):
        review = latest_review(new, comments, number, head, base)
        if review and review["url"] != (new.get("review") or {}).get("url"):
            evidence = {"result": review["result"], "head": head, "base": base,
                        "url": review["url"], "reviewer": review["reviewer"]}
            new["review"] = evidence
            if review["result"] == "PASS" and new["status"] not in {
                    "software-validated", "review-requested", "changes-requested"}:
                pass  # already accepted; the newer PASS only refreshes evidence
            elif review["result"] == "FAIL":
                new["status"] = "changes-requested"
                if not has_marker(comments, "rework", number, head, base):
                    actions.append({"kind": "comment", "target": pr["number"], "body": "\n".join([
                        marker("rework", number, head, base),
                        f"Review FAIL for Task #{number} at `{head[:12]}`: {review['url']}",
                        f"Routed back to owner `{new['owner']}`. Push a fix; the new head is re-validated "
                        "and re-reviewed automatically."])})
            elif new["hardware"] == "required":
                new["status"] = "hardware-required"
                if not has_marker(facts.get("issue_comments") or [], "hardware", number, head, base):
                    actions.append({"kind": "comment", "target": number,
                                    "body": hardware_card(number, new, pr, evidence)})
            else:
                new["status"] = "ready-to-merge"
        elif new["status"] == "software-validated":
            reviewer_agent = REVIEWER_FOR[new["agent"]]
            new["status"] = "review-requested"
            new["review_request"] = {"head": head, "base": base, "reviewer_agent": reviewer_agent}
            if not has_marker(comments, "review-request", number, head, base):
                actions.append({"kind": "comment", "target": pr["number"], "body": "\n".join([
                    marker("review-request", number, head, base),
                    f"**Independent review requested** ({reviewer_agent})",
                    "",
                    f"Task: #{number} · PR: #{pr['number']} · Class {new['class']} · hardware {new['hardware']}",
                    f"Head: `{head}`",
                    f"Base: `{base}`",
                    f"Owner (cannot review): `{new['owner']}`",
                    f"Scope: {', '.join(new['scope'])}",
                    "",
                    "Review this exact candidate according to AGENTS.md, then reply with one "
                    f"`regear-review` block with `\"agent\": \"{reviewer_agent}\"` "
                    "(see docs/CONTINUOUS_DEVELOPMENT.md#review)."])})

    if new["status"] == "hardware-validated":
        promoted = dict(copy.deepcopy(new), status="ready-to-merge")
        try:
            gc.check(promoted, pr, facts.get("others", []))
            new = promoted
        except ValueError as exc:
            notes.append(f"hardware-validated but not mergeable: {exc}")

    if new["status"] == "ready-to-merge" and old["status"] == "ready-to-merge" and new == old:
        decision = merge_decision(number, new, pr, facts)
        notes.extend(decision["blockers"])
        actions.extend(decision["actions"])

    return finish(old, new, facts), actions, notes


def finish(old, new, facts):
    if new == old:
        return None
    new["revision"] = old["revision"] + 1
    return gc.update(old, new, old["revision"], facts.get("others", []))


def merge_decision(number, record, pr, facts):
    """Automatic integration only for eligible Class A; everything else waits
    for the assigned integration driver. Returns blockers and actions."""
    head, base = candidate_of(pr)
    blockers, actions = [], []
    if record["class"] not in AUTO_MERGE_CLASSES or record["hardware"] != "not-required":
        blockers.append(f"class {record['class']} is integrated by the assigned driver, not automatically")
    if record.get("auto_merge") is False:
        blockers.append("task opted out of automatic integration")
    if HOLD_LABELS & set(facts.get("labels") or []):
        blockers.append("merge-hold/hold/needs-decision label present")
    files = facts.get("files")
    if files is None:
        blockers.append("changed files unknown")
    elif any(path.startswith(PROTECTED_PATHS) for path in files):
        blockers.append("PR changes protected coordination/merge-authority paths; integrate manually")
    if pr.get("draft"):
        blockers.append("draft PR")
    if facts.get("gate_error"):
        blockers.append(f"coordination gate: {facts['gate_error']}")
    if (facts.get("checks") or {}).get("state") != "success":
        blockers.append("required CI is not green on the exact head")
    behind = facts.get("behind_by")
    if behind is None or behind > 0:
        blockers.append("head does not contain the current base branch tip")
        if behind and not has_marker(facts.get("comments") or [], "update-base", number, head, base):
            actions.append({"kind": "comment", "target": pr["number"], "body": "\n".join([
                marker("update-base", number, head, base),
                f"Task #{number} is ready to merge but `{pr['base']['ref']}` has moved. Owner "
                f"`{record['owner']}`: merge the current base into the branch (no rebase/force-push). "
                "The new head is re-validated and re-reviewed automatically."])})
    if facts.get("mergeable") is not True:
        blockers.append("GitHub does not report the PR as mergeable")
    if not blockers:
        actions.append({"kind": "merge", "pr": pr["number"], "sha": head, "task": number})
    return {"blockers": blockers, "actions": actions}


# -- agent work discovery and stuck-work visibility (pure) --------------------

def next_actions(agent, session, tasks, now=None):
    """What a newly started agent session should do, most urgent first.

    `tasks` rows: {number, record, labels, updated_at, pr}. No GitHub writes."""
    work = []
    mine = [t for t in tasks if t["record"]["owner"] == session]
    for t in mine:
        r = t["record"]
        if r["status"] == "changes-requested":
            work.append(dict(kind="rework", task=t["number"], detail=(r.get("review") or {}).get("url")))
        elif r["status"] in {"claimed", "in-progress"}:
            work.append(dict(kind="implement", task=t["number"], detail=r["branch"]))
    for t in tasks:
        r = t["record"]
        request = r.get("review_request") or {}
        if (r["status"] == "review-requested" and r["owner"] != session
                and request.get("reviewer_agent", REVIEWER_FOR[r["agent"]]) == agent):
            pr = t.get("pr")
            work.append(dict(kind="review", task=t["number"], pr=pr and pr["number"],
                             head=request.get("head"), base=request.get("base"),
                             detail=f"Review Task #{t['number']} exact candidate according to AGENTS.md"))
        if agent == "codex-local" and r["status"] == "hardware-required":
            work.append(dict(kind="hardware", task=t["number"], detail="python scripts/github_coordination.py queue"))
        if agent == "codex-local" and r["status"] == "ready-to-merge" and (
                r["class"] not in AUTO_MERGE_CLASSES or r.get("auto_merge") is False):
            work.append(dict(kind="integrate", task=t["number"], detail=f"class {r['class']} integration driver"))
    implementing = sum(t["record"]["status"] in IMPLEMENTING for t in mine)
    waiting = sum(t["record"]["status"] in WAITING for t in mine)
    if implementing == 0 and waiting <= 1:
        active = [(t["number"], t["record"]) for t in tasks if t["record"]["status"] in gc.ACTIVE]
        for t in sorted(tasks, key=lambda t: (priority(t["labels"]), t["number"])):
            r = t["record"]
            if r["status"] != "backlog" or r["owner"] is not None or r["agent"] != agent:
                continue
            if any(gc.overlap(r["scope"], other["scope"]) or r["branch"] == other["branch"] for _, other in active):
                continue
            work.append(dict(kind="claim", task=t["number"], detail=f"claim at revision {r['revision']} then implement"))
            break
    return work


def priority(labels):
    return min((PRIORITY[label] for label in labels if label in PRIORITY), default=9)


def watchdog(tasks, now):
    """Tasks waiting longer than their state's normal window, plus hard faults."""
    rows = []
    for t in tasks:
        r = t["record"]
        limit = STUCK_HOURS.get(r["status"])
        age = (now - parse_time(t["updated_at"])).total_seconds() / 3600 if t.get("updated_at") else None
        problems = list(t.get("faults") or [])
        if limit is not None and age is not None and age > limit:
            problems.append(f"{r['status']} for {age:.0f}h (normal window {limit}h)")
        if problems:
            rows.append({"task": t["number"], "status": r["status"], "owner": r["owner"], "problems": problems})
    return rows


def parse_time(value):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# -- GitHub fact gathering and action application -----------------------------

class GitHubFacts:
    """Read-only snapshot helpers over `gc.GitHub`; caches permission lookups."""

    def __init__(self, github):
        self.github = github
        self.permissions = {}

    def managed_issues(self):
        result = []
        for issue in self.github.pages("issues?state=open"):
            if "pull_request" in issue or not any(l["name"] == "agent-task" for l in issue["labels"]):
                continue
            row = {"number": issue["number"], "body": issue["body"], "record": None,
                   "labels": [l["name"] for l in issue["labels"]], "updated_at": issue.get("updated_at")}
            try:
                row["record"] = gc.parse(issue["body"])
            except (ValueError, TypeError) as exc:
                row["error"] = f"invalid task record: {exc}"  # reported, never silently dropped
            result.append(row)
        return result

    def permission(self, login):
        if login not in self.permissions:
            try:
                self.permissions[login] = self.github.api(f"collaborators/{login}/permission")["permission"]
            except Exception:  # noqa: BLE001 - an unknown commenter is simply not a writer
                self.permissions[login] = "none"
        return self.permissions[login]

    def comments(self, number):
        rows = []
        for c in self.github.pages(f"issues/{number}/comments"):
            user = c.get("user") or {}
            bot = user.get("type") == "Bot" or str(user.get("login", "")).endswith("[bot]")
            rows.append({"id": c.get("id"), "body": c.get("body"), "html_url": c["html_url"],
                         "created_at": c.get("created_at"),
                         "is_bot": bot, "author_permission": "none" if bot else self.permission(user.get("login"))})
        return rows

    def checks(self, sha):
        data = self.github.api(f"commits/{sha}/check-runs?per_page=100")
        return checks_state(data.get("check_runs", []))

    def merged_pr(self, branch):
        owner = self.github.repo.split("/")[0]
        for pr in self.github.api(f"pulls?state=closed&head={owner}:{branch}&per_page=20") or []:
            if pr.get("merged_at"):
                return pr
        return None

    def files(self, number):
        names = []
        for item in self.github.pages(f"pulls/{number}/files"):
            names += [item["filename"]] + ([item["previous_filename"]] if "previous_filename" in item else [])
        return names

    def snapshot(self, issue, open_prs, all_records):
        number, record = issue["number"], issue["record"]
        facts = {"others": [(n, r) for n, r in all_records if n != number], "labels": list(issue["labels"]),
                 "issue_labels": list(issue["labels"]), "issue_comments": self.comments(number)}
        matches = []
        for pr in open_prs:
            try:
                if gc.task_number(pr.get("body")) == number:
                    matches.append(pr)
            except ValueError:
                continue
        if len(matches) > 1:
            facts["pr_error"] = "task has more than one open PR"
            return facts
        if record["status"] in gc.TERMINAL or record["status"] == "backlog":
            return facts
        if not matches:
            if record["status"] in gc.CANDIDATE | {"pr-open"}:
                facts["merged_pr"] = self.merged_pr(record["branch"])
            return facts
        pr = self.github.api(f"pulls/{matches[0]['number']}")
        facts["pr"] = pr
        facts["pr_labels"] = [l["name"] for l in pr.get("labels", [])]
        facts["labels"] += facts["pr_labels"]
        head = pr["head"]["sha"]
        facts["checks"] = self.checks(head)
        if record["status"] in gc.CANDIDATE | {"pr-open"}:
            facts["comments"] = self.comments(pr["number"])
        if record["status"] == "ready-to-merge":
            try:
                gc.check_pr(self.github, pr, all_records, open_prs)
            except (ValueError, KeyError, TypeError) as exc:
                facts["gate_error"] = str(exc)
            facts["files"] = self.files(pr["number"])
            compare = self.github.api(f"compare/{pr['base']['ref']}...{head}")
            facts["behind_by"] = compare.get("behind_by")
            facts["mergeable"] = pr.get("mergeable")
        return facts


def reconcile(github, dry_run=False, out=print):
    facts_source = GitHubFacts(github)
    issues = facts_source.managed_issues()
    open_prs = github.pages("pulls?state=open")
    records = [(i["number"], i["record"]) for i in issues if i["record"] is not None]
    report, changed = [], False
    for issue in issues:
        row = {"task": issue["number"], "status": (issue["record"] or {}).get("status"), "actions": [], "notes": []}
        if issue["record"] is None:
            row["error"] = issue["error"]
            report.append(row)
            continue
        try:
            # Reconciler writes trigger no workflow, so after a write the task is
            # re-read and planned again in this run (intent -> automatic step -> merge).
            for _ in range(3):
                facts = facts_source.snapshot(issue, open_prs, records)
                new, actions, notes = plan(issue["number"], issue["record"], facts)
                row["notes"] += notes
                if dry_run:
                    row["actions"] += [a["kind"] for a in actions] + (["update:" + new["status"]] if new else [])
                    break
                changed |= apply(github, issue, new, actions, facts, row)
                merges = [a for a in actions if a["kind"] == "merge"]
                if merges:
                    open_prs = github.pages("pulls?state=open")
                    changed |= merge_if_still_eligible(github, facts_source, issue, merges[0], open_prs, records, row)
                    break
                if new is None:
                    break
                fresh = github.api(f"issues/{issue['number']}")
                issue = dict(issue, body=fresh["body"], record=gc.parse(fresh["body"]),
                             labels=[l["name"] for l in fresh.get("labels", [])])
                records = [(n, issue["record"] if n == issue["number"] else r) for n, r in records]
        except (ValueError, KeyError, TypeError, gc.subprocess.CalledProcessError) as exc:
            # One task's failure never blocks the others; the next run retries from fresh state.
            row["error"] = str(exc)
        row["status"] = issue["record"]["status"]
        report.append(row)
    if changed and not dry_run:
        gc.refresh(github)
    out(json.dumps(report, indent=2))
    return report


def apply(github, issue, new, actions, facts, row):
    """Comments first (each idempotent by marker), then one CAS write, then
    label repair. A comment posted by a run whose write then loses the race is
    found by marker next time and not repeated; the record is recomputed."""
    changed = False
    for action in [a for a in actions if a["kind"] == "comment"]:
        github.api(f"issues/{action['target']}/comments", "POST", {"body": action["body"]})
        row["actions"].append(f"comment:#{action['target']}")
    current = issue["record"]
    if new is not None:
        body = gc.replace(issue["body"], new)
        gc.write_body(github, issue["number"], issue["body"], body, new)  # also mirrors issue labels
        row["actions"].append(f"update:{new['status']}@r{new['revision']}")
        current, changed = new, True
    issue_labels, pr_labels = label_plan(current, facts.get("issue_labels") or [], facts.get("pr_labels"))
    if issue_labels is not None and new is None:
        github.api(f"issues/{issue['number']}/labels", "PUT", {"labels": issue_labels})
        row["actions"].append("labels:issue")
    if pr_labels is not None:
        github.api(f"issues/{facts['pr']['number']}/labels", "PUT", {"labels": pr_labels})
        row["actions"].append("labels:pr")
    return changed


def merge_if_still_eligible(github, facts_source, issue, action, open_prs, records, row):
    """Re-read everything immediately before merging; merge only if a fresh
    plan from live state still produces this exact merge, then record it only
    after GitHub confirms the merge."""
    fresh = github.api(f"issues/{issue['number']}")
    current = dict(issue, body=fresh["body"], record=gc.parse(fresh["body"]),
                   labels=[l["name"] for l in fresh.get("labels", [])])
    facts = facts_source.snapshot(current, open_prs, records)
    _, actions, notes = plan(current["number"], current["record"], facts)
    if action not in actions:
        row["notes"].append("merge withdrawn on fresh re-validation: " + ("; ".join(notes) or "state changed"))
        return False
    # Fast-forward the base ref to the reviewed head with force=false. This is
    # the atomic exact-candidate guard: GitHub refuses unless the head still
    # descends from the current base tip, so a base that moved after the check
    # cannot be merged unreviewed, and the result is exactly the reviewed tree.
    # A protected branch that refuses direct ref updates leaves the task
    # ready-to-merge for the integration driver (reported by watchdog).
    ref = f"git/refs/heads/{facts['pr']['base']['ref']}"
    result = github.api(ref, "PATCH", {"sha": action["sha"], "force": False})
    gc.require(isinstance(result, dict) and (result.get("object") or {}).get("sha") == action["sha"],
               "GitHub did not confirm the fast-forward to the reviewed head")
    row["actions"].append(f"merge:#{action['pr']}")
    record = current["record"]
    merged = dict(copy.deepcopy(record), status="merged", revision=record["revision"] + 1,
                  integration={"pr": action["pr"], "sha": action["sha"], "url": facts["pr"]["html_url"]})
    merged = gc.update(record, merged, record["revision"], facts.get("others", []))
    gc.write_body(github, current["number"], current["body"], gc.replace(current["body"], merged), merged)
    row["actions"].append("update:merged")
    # GITHUB_TOKEN merges trigger no push workflows; request base-branch CI explicitly.
    for profile in ("development", "production"):
        try:
            github.api("actions/workflows/ci.yml/dispatches", "POST",
                       {"ref": facts["pr"]["base"]["ref"], "inputs": {"profile": profile}})
        except gc.subprocess.CalledProcessError:
            row["notes"].append(f"could not dispatch post-merge {profile} CI")
    return True


def gather_rows(github, with_faults=False):
    facts_source = GitHubFacts(github)
    issues = facts_source.managed_issues()
    open_prs = github.pages("pulls?state=open")
    rows = []
    for issue in issues:
        if issue["record"] is None:
            if with_faults:
                rows.append({"number": issue["number"], "record": {"status": "invalid", "owner": None},
                             "labels": issue["labels"], "updated_at": None, "pr": None, "faults": [issue["error"]]})
            continue
        pr = None
        for candidate in open_prs:
            try:
                if gc.task_number(candidate.get("body")) == issue["number"]:
                    pr = candidate
            except ValueError:
                continue
        row = {"number": issue["number"], "record": issue["record"], "labels": issue["labels"],
               "updated_at": issue["updated_at"], "pr": pr, "faults": []}
        if with_faults and pr is not None and issue["record"]["status"] in gc.ACTIVE:
            detail = github.api(f"pulls/{pr['number']}")
            if facts_source.checks(detail["head"]["sha"])["state"] == "failure":
                row["faults"].append("required CI failed")
            if detail.get("mergeable") is False:
                row["faults"].append("PR has merge conflicts")
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["reconcile", "next", "watchdog"])
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--agent", choices=sorted(REVIEWER_FOR))
    parser.add_argument("--session")
    args = parser.parse_args()
    gc.require(bool(args.repo), "--repo OWNER/REPO required")
    github = gc.GitHub(args.repo)
    if args.command == "reconcile":
        dry = args.dry_run
        if not dry:
            try:
                gc.trusted(github, None)
            except ValueError as exc:
                # An untrusted trigger (e.g. a non-writer's comment) only observes.
                print(f"coordination: read-only reconcile ({exc})", file=sys.stderr)
                dry = True
        reconcile(github, dry_run=dry)
    elif args.command == "next":
        gc.require(args.agent and args.session and gc.ID.fullmatch(args.session), "--agent and --session required")
        print(json.dumps(next_actions(args.agent, args.session, gather_rows(github)), indent=2))
    else:
        rows = watchdog(gather_rows(github, with_faults=True), datetime.now(timezone.utc))
        text = json.dumps(rows, indent=2)
        print(text)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as handle:
                handle.write("## Coordination watchdog\n\n```json\n" + text + "\n```\n")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, gc.subprocess.CalledProcessError) as error:
        print(f"coordination: {error}", file=sys.stderr)
        sys.exit(1)
