"""Reconciler handoffs: review request, PASS/FAIL routing, stale evidence,
Class A integration and hardware gates. Deterministic; no network."""
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("orchestrator", ROOT / "scripts/coordination_orchestrator.py")
o = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(o)
gc = o.gc
HEAD, BASE, NEW = "a" * 40, "b" * 40, "c" * 40
OWNER, REVIEWER = "claude-owner", "codex-reviewer"
ENV = {"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/main", "GITHUB_ACTOR": "writer"}


def record(**changes):
    result = dict(schema=1, owner=OWNER, agent="claude", branch="agent/claude/7-task", status="pr-open",
                  hardware="not-required", validation="unit tests", scope=["docs/example.md"], revision=3)
    result["class"] = "A"
    result.update(changes)
    return result


def ev(head=HEAD, base=BASE, **changes):
    return dict(dict(result="PASS", head=head, base=base, url="https://example.org/ci"), **changes)


def at(status, **changes):
    """A record already holding software evidence for HEAD/BASE."""
    return record(status=status, software=ev(), **changes)


def pr(head=HEAD, base=BASE, **changes):
    repo = {"full_name": "owner/repo"}
    result = dict(number=12, body="Task: #7", draft=False, changed_files=1, html_url="https://example.org/pr/12",
                  head={"ref": "agent/claude/7-task", "sha": head, "repo": repo},
                  base={"ref": "main", "sha": base, "repo": repo}, mergeable=True, labels=[])
    result.update(changes)
    return result


GREEN = {"state": "success", "url": "https://example.org/ci"}


def review_comment(result="PASS", reviewer=REVIEWER, head=HEAD, base=BASE, task=7, permission="write",
                   created="2026-10-02T12:00:00Z", url="https://example.org/pr/12#review", bot=False):
    block = json.dumps({"task": task, "head": head, "base": base, "result": result, "reviewer": reviewer})
    return {"body": f"Findings...\n```regear-review\n{block}\n```", "html_url": url,
            "created_at": created, "author_permission": permission, "is_bot": bot}


def facts(**changes):
    return dict(dict(pr=pr(), checks=GREEN, comments=[], issue_comments=[], labels=[], others=[]), **changes)


class PlanTests(unittest.TestCase):
    def test_01_software_validated_requests_independent_review(self):
        new, actions, _ = o.plan(7, record(), facts())
        self.assertEqual(new["status"], "review-requested")
        self.assertEqual(new["software"], ev())
        self.assertEqual(new["review_request"], {"head": HEAD, "base": BASE, "reviewer_agent": "codex-cloud"})
        self.assertEqual(new["revision"], 4)
        [comment] = actions
        self.assertEqual(comment["target"], 12)
        self.assertIn(o.marker("review-request", 7, HEAD, BASE), comment["body"])
        self.assertIn("Task: #7", comment["body"])
        # Codex-implemented work is routed to Claude.
        new, _, _ = o.plan(7, record(agent="codex-cloud"), facts())
        self.assertEqual(new["review_request"]["reviewer_agent"], "claude")

    def test_02_owner_and_untrusted_reviews_never_count(self):
        waiting = at("review-requested", review_request={"head": HEAD, "base": BASE, "reviewer_agent": "codex-cloud"})
        for comment in [review_comment(reviewer=OWNER), review_comment(permission="read"),
                        review_comment(bot=True), review_comment(task=8),
                        {"body": "PASS, looks good", "html_url": "x", "author_permission": "write", "is_bot": False}]:
            new, _, _ = o.plan(7, waiting, facts(comments=[comment]))
            self.assertIsNone(new, comment)

    def test_03_exact_pass_reaches_ready_to_merge(self):
        waiting = at("review-requested")
        new, actions, _ = o.plan(7, waiting, facts(comments=[review_comment()]))
        self.assertEqual(new["status"], "ready-to-merge")
        self.assertEqual(new["review"], {"result": "PASS", "head": HEAD, "base": BASE,
                                         "url": "https://example.org/pr/12#review", "reviewer": REVIEWER})
        self.assertEqual(actions, [])
        gc.check(new, pr())  # the existing merge gate accepts the recorded evidence
        # A review of another head/base is not evidence for this candidate.
        for stale in [review_comment(head=NEW), review_comment(base=NEW)]:
            self.assertIsNone(o.plan(7, waiting, facts(comments=[stale]))[0])

    def test_04_changed_head_or_base_invalidates_review(self):
        accepted = at("ready-to-merge", review=ev(reviewer=REVIEWER))
        for changed in [pr(head=NEW), pr(base=NEW)]:
            new, _, notes = o.plan(7, accepted, facts(pr=changed, checks={"state": "pending"}))
            self.assertEqual(new["status"], "pr-open")
            self.assertNotIn("review", new)
            self.assertNotIn("software", new)
            self.assertIn("candidate changed; software/review evidence invalidated", notes)

    def test_05_fail_routes_back_to_owner(self):
        waiting = at("review-requested")
        new, actions, _ = o.plan(7, waiting, facts(comments=[review_comment(result="FAIL")]))
        self.assertEqual(new["status"], "changes-requested")
        self.assertEqual(new["review"]["result"], "FAIL")
        self.assertEqual(new["owner"], OWNER)
        [ack] = actions
        self.assertIn(o.marker("rework", 7, HEAD, BASE), ack["body"])
        rows = [{"number": 7, "record": new, "labels": [], "updated_at": None, "pr": pr()}]
        self.assertEqual(o.next_actions("claude", OWNER, rows)[0]["kind"], "rework")
        # A FAIL keeps the task out of the merge gate.
        with self.assertRaises(ValueError):
            gc.check(dict(new, status="ready-to-merge"), pr())

    def test_06_new_head_after_rework_requests_new_review(self):
        failed = at("changes-requested", review=ev(result="FAIL", reviewer=REVIEWER))
        old_markers = [{"body": o.marker("review-request", 7, HEAD, BASE), "html_url": "x", "is_bot": True}]
        new, actions, _ = o.plan(7, failed, facts(pr=pr(head=NEW), comments=old_markers))
        self.assertEqual(new["status"], "review-requested")
        self.assertEqual(new["software"]["head"], NEW)
        self.assertNotIn("review", new)
        [request] = actions
        self.assertIn(o.marker("review-request", 7, NEW, BASE), request["body"])

    def test_07_class_a_reaches_integration(self):
        accepted = at("ready-to-merge", review=ev(reviewer=REVIEWER))
        ready = facts(behind_by=0, mergeable=True)
        _, actions, notes = o.plan(7, accepted, ready)
        self.assertEqual(actions, [{"kind": "merge", "pr": 12, "sha": HEAD, "task": 7}], notes)
        blocked = {"hold label": dict(ready, labels=["hold"]), "draft": dict(ready, pr=pr(draft=True)),
                   "behind": dict(ready, behind_by=2), "conflict": dict(ready, mergeable=False),
                   "gate": dict(ready, gate_error="scope overlaps #9"), "ci": dict(ready, checks={"state": "pending"})}
        for name, case in blocked.items():
            self.assertFalse(any(a["kind"] == "merge" for a in o.plan(7, accepted, case)[1]), name)
        self.assertFalse(any(a["kind"] == "merge" for a in o.plan(7, dict(accepted, auto_merge=False), ready)[1]))
        # A moved base asks the owner once for a base merge.
        behind = o.plan(7, accepted, dict(ready, behind_by=2))[1]
        self.assertEqual([a["kind"] for a in behind], ["comment"])
        marked = dict(ready, behind_by=2, comments=[{"body": behind[0]["body"], "html_url": "x", "is_bot": True}])
        self.assertEqual(o.plan(7, accepted, marked)[1], [])

    def test_08_hardware_classes_cannot_bypass_the_gate(self):
        for risk in ["C", "D"]:
            waiting = at("review-requested", hardware="required", **{"class": risk})
            new, actions, _ = o.plan(7, waiting, facts(comments=[review_comment()]))
            self.assertEqual(new["status"], "hardware-required")
            [card] = actions
            self.assertEqual(card["target"], 7)
            self.assertIn("Ready for hardware: Task #7", card["body"])
            self.assertIn(HEAD, card["body"])
            forced = dict(new, status="ready-to-merge")
            decision = o.merge_decision(7, forced, pr(), facts(behind_by=0, mergeable=True))
            self.assertEqual(decision["actions"], [])
        b = at("ready-to-merge", review=ev(reviewer=REVIEWER), behavior="docs/GOLDEN_BEHAVIORS.md#g1", **{"class": "B"})
        self.assertEqual(o.merge_decision(7, b, pr(), facts(behind_by=0, mergeable=True))["actions"], [])
        rows = [{"number": 7, "record": b, "labels": [], "updated_at": None, "pr": pr()}]
        self.assertEqual(o.next_actions("codex-local", "local-session", rows)[0]["kind"], "integrate")

    def test_hardware_validated_promotes_only_with_exact_hardware_pass(self):
        hw = ev(agent="codex-local", tester="local", tested_commit=HEAD, artifact="sha256:" + "d" * 64)
        validated = at("hardware-validated", hardware="required", review=ev(reviewer=REVIEWER),
                       hardware_evidence=hw, **{"class": "C"})
        new, _, _ = o.plan(7, validated, facts())
        self.assertEqual(new["status"], "ready-to-merge")
        self.assertEqual(o.merge_decision(7, new, pr(), facts(behind_by=0, mergeable=True))["actions"], [])

    def test_12_reconciler_never_changes_owner(self):
        claimed = record(status="claimed")
        with self.assertRaisesRegex(ValueError, "transfer"):
            gc.update(claimed, dict(claimed, owner="second-owner", revision=4), 3, [])
        new, _, _ = o.plan(7, claimed, facts(checks={"state": "pending"}))
        self.assertEqual((new["owner"], new["status"]), (OWNER, "pr-open"))
        rows = [{"number": 7, "record": record(status="backlog", owner=None, revision=1), "labels": [],
                 "updated_at": None, "pr": None}]
        self.assertEqual(o.next_actions("claude", "s2", rows)[0]["kind"], "claim")
        rows[0]["record"] = claimed
        self.assertEqual(o.next_actions("claude", "s2", rows), [])

    def test_merged_pr_and_terminal_tasks(self):
        merged = {"number": 12, "merge_commit_sha": NEW, "html_url": "https://example.org/pr/12"}
        new, _, _ = o.plan(7, at("ready-to-merge", review=ev(reviewer=REVIEWER)), facts(pr=None, merged_pr=merged))
        self.assertEqual((new["status"], new["integration"]["sha"]), ("merged", NEW))
        self.assertEqual(o.plan(7, record(status="merged"), facts()), (None, [], []))

    def test_draft_and_failed_ci_wait(self):
        self.assertIsNone(o.plan(7, record(), facts(pr=pr(draft=True)))[0])
        # Returning a validated PR to draft withdraws it from review.
        self.assertEqual(o.plan(7, at("software-validated"), facts(pr=pr(draft=True))), (None, [], []))
        _, _, notes = o.plan(7, record(), facts(checks={"state": "failure"}))
        self.assertIn("required CI failed on the exact head", notes)

    def test_required_check_state(self):
        ok = [{"name": n, "status": "completed", "conclusion": "success", "html_url": n}
              for n in ["foundation", "privileged-user-delivery", "build_profiles (production)"]]
        self.assertEqual(o.checks_state(ok)["state"], "success")
        self.assertEqual(o.checks_state(ok[1:])["state"], "pending")
        self.assertEqual(o.checks_state(ok + [{"name": "x", "status": "in_progress"}])["state"], "pending")
        self.assertEqual(o.checks_state(ok + [{"name": "x", "status": "completed", "conclusion": "failure"}])["state"],
                         "failure")
        self.assertEqual(o.checks_state(ok + [{"name": "gate", "status": "in_progress"}])["state"], "success")

    def test_next_limits_work_in_progress_and_respects_scope(self):
        backlog = {"number": 9, "labels": ["P2"], "updated_at": None, "pr": None,
                   "record": record(status="backlog", owner=None, revision=1, branch="agent/claude/9-x", scope=["docs/b.md"])}
        waiting = {"number": 7, "labels": [], "updated_at": None, "pr": pr(), "record": at("review-requested")}
        self.assertEqual([w["kind"] for w in o.next_actions("claude", OWNER, [waiting, backlog])], ["claim"])
        second = dict(waiting, number=8, record=at("ready-to-merge", branch="agent/claude/8-y", scope=["docs/c.md"]))
        self.assertEqual(o.next_actions("claude", OWNER, [waiting, second, backlog]), [])
        busy = dict(waiting, record=record(status="in-progress"))
        self.assertEqual([w["kind"] for w in o.next_actions("claude", OWNER, [busy, backlog])], ["implement"])
        overlapping = dict(backlog, record=dict(backlog["record"], scope=["docs/example.md"]))
        self.assertEqual(o.next_actions("claude", "other", [waiting, overlapping]), [])
        review = o.next_actions("codex-cloud", REVIEWER, [dict(waiting, record=at(
            "review-requested", review_request={"head": HEAD, "base": BASE, "reviewer_agent": "codex-cloud"}))])
        self.assertEqual((review[0]["kind"], review[0]["head"]), ("review", HEAD))
        self.assertEqual(o.next_actions("claude", OWNER, [waiting]), [])

    def test_watchdog_reports_long_waits_and_faults(self):
        now = datetime(2026, 10, 3, tzinfo=timezone.utc)
        rows = [{"number": 7, "record": at("review-requested"), "updated_at": "2026-10-01T00:00:00Z"},
                {"number": 8, "record": at("review-requested"), "updated_at": "2026-10-02T23:00:00Z"},
                {"number": 9, "record": record(), "updated_at": "2026-10-02T23:00:00Z", "faults": ["required CI failed"]}]
        report = o.watchdog(rows, now)
        self.assertEqual([r["task"] for r in report], [7, 9])
        self.assertIn("normal window 24h", report[0]["problems"][0])


class FakeGitHub:
    """In-memory repository API for reconcile/apply; records every mutation."""

    repo = "owner/repo"

    def __init__(self, task, pull, checks=None, comments=None, behind_by=0):
        self.body = "Prose stays.\n```regear-task\n" + json.dumps(task) + "\n```"
        self.pull, self.check_runs = pull, checks if checks is not None else [
            {"name": n, "status": "completed", "conclusion": "success", "html_url": "https://example.org/ci"}
            for n in o.REQUIRED_CHECKS]
        self.comments = {12: list(comments or []), 7: []}
        self.behind_by, self.labels, self.mutations = behind_by, [{"name": "agent-task"}], []
        self.on_read, self.merged = None, False

    def tasks(self):
        return [(7, gc.parse(self.body))]

    def pages(self, path):
        if path == "issues?state=open":
            return [{"number": 7, "body": self.body, "labels": self.labels, "updated_at": "2026-10-02T00:00:00Z"}]
        if path == "pulls?state=open":
            return [] if self.merged or not self.pull else [self.pull]
        if path.startswith("issues/") and path.endswith("/comments"):
            return self.comments[int(path.split("/")[1])]
        if path.endswith("/files"):
            return [{"filename": "docs/example.md"}]
        raise AssertionError(path)

    def api(self, path, method="GET", payload=None):
        if method != "GET":
            self.mutations.append((method, path, payload))
        if path == "issues/7":
            if method == "PATCH":
                self.body = payload["body"]
            elif self.on_read:
                self.on_read()
            return {"number": 7, "body": self.body, "state": "open", "labels": self.labels}
        if path == "issues/7/labels":
            self.labels = [{"name": n} for n in payload["labels"]]
            return self.labels
        if path.startswith("issues/") and path.endswith("/comments"):
            self.comments[int(path.split("/")[1])].append(
                {"body": payload["body"], "html_url": "https://example.org/c", "user": {"login": "github-actions[bot]", "type": "Bot"}})
            return {}
        if path == "pulls/12":
            return self.pull
        if path.startswith("commits/"):
            return {"check_runs": self.check_runs}
        if path.startswith("collaborators/"):
            return {"permission": "write"}
        if path.startswith("compare/"):
            return {"behind_by": self.behind_by}
        if path == "pulls/12/merge":
            self.merged = True
            self.pull = dict(self.pull, merged_at="2026-10-02T13:00:00Z", merge_commit_sha=NEW)
            return {"sha": NEW, "merged": True}
        if path.startswith("pulls?state=closed"):
            return []
        if path.startswith("statuses/") or path.startswith("actions/workflows/"):
            return {}
        raise AssertionError((method, path))


def reconcile(fake):
    with patch.dict(o.os.environ, ENV):
        return o.reconcile(fake, out=lambda _: None)


class ReconcileTests(unittest.TestCase):
    def test_10_lost_race_acquires_nothing_and_rerun_recovers(self):
        fake = FakeGitHub(record(), pr())
        other_writer = "Prose stays.\n```regear-task\n" + json.dumps(record(revision=4, status="blocked")) + "\n```"

        def interleave():  # another writer lands between snapshot and write
            fake.body, fake.on_read = other_writer, None
        fake.on_read = interleave
        [row] = reconcile(fake)
        self.assertIn("issue changed during update", row["error"])
        self.assertEqual(gc.parse(fake.body)["status"], "blocked")
        # The next run starts from the new state instead of replaying stale intent.
        [row] = reconcile(fake)
        self.assertEqual(gc.parse(fake.body)["status"], "blocked")
        self.assertNotIn("error", row)

    def test_11_repeated_runs_post_one_review_request(self):
        fake = FakeGitHub(record(), pr())
        reconcile(fake)
        self.assertEqual(gc.parse(fake.body)["status"], "review-requested")
        reconcile(fake)
        reconcile(fake)
        requests = [c for c in fake.comments[12] if "regear:review-request" in c["body"]]
        self.assertEqual(len(requests), 1)
        self.assertEqual(gc.parse(fake.body)["revision"], 4)
        self.assertTrue(fake.body.startswith("Prose stays."))
        self.assertIn({"name": "task:review-requested"}, fake.labels)

    def test_09_stale_expected_revision_is_rejected(self):
        old = at("review-requested")
        with self.assertRaisesRegex(ValueError, "stale"):
            gc.update(old, dict(old, revision=5), 2, [])
        fake = FakeGitHub(old, pr())
        with self.assertRaisesRegex(ValueError, "changed"):
            gc.write_body(fake, 7, "an older body", "new body", old)

    def test_end_to_end_class_a_without_relaying(self):
        fake = FakeGitHub(record(), pr())
        reconcile(fake)  # CI green -> software evidence -> review requested
        fake.comments[12].append(dict(review_comment(), user={"login": "writer", "type": "User"}))
        reconcile(fake)  # PASS -> ready-to-merge -> merged in the same run
        final = gc.parse(fake.body)
        self.assertEqual(final["status"], "merged")
        self.assertEqual(final["integration"]["sha"], NEW)
        merges = [m for m in fake.mutations if m[1] == "pulls/12/merge"]
        self.assertEqual(merges, [("PUT", "pulls/12/merge", {"sha": HEAD, "merge_method": "merge"})])
        dispatched = [m[2]["inputs"]["profile"] for m in fake.mutations if m[1].startswith("actions/workflows/")]
        self.assertEqual(dispatched, ["development", "production"])

    def test_untrusted_dry_run_never_mutates(self):
        fake = FakeGitHub(record(), pr())
        with patch.dict(o.os.environ, ENV):
            [row] = o.reconcile(fake, dry_run=True, out=lambda _: None)
        self.assertEqual(fake.mutations, [])
        self.assertIn("update:review-requested", row["actions"])

    def test_workflow_runs_default_branch_code_in_its_own_group(self):
        text = (ROOT / ".github/workflows/coordination-orchestrator.yml").read_text()
        self.assertIn("github.event.repository.default_branch", text)
        self.assertIn("persist-credentials: false", text)
        self.assertNotIn("github.event.pull_request.head", text)
        self.assertNotIn("${{ inputs.", text)
        self.assertIn("group: coordination-orchestrator", text)
        gate = (ROOT / ".github/workflows/coordination-gate.yml").read_text()
        self.assertNotIn("group: github-task-record-writer", gate)


if __name__ == "__main__":
    unittest.main()
