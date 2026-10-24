"""Current-schema owner discovery through a strictly GET-only fake GitHub API."""

import copy
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("owner_discovery", ROOT / "scripts/coordination_orchestrator.py")
o = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(o)
HEAD, BASE = "a" * 40, "b" * 40
OWNER = "owner-session"


def record(**changes):
    result = dict(schema=1, revision=2, owner=OWNER, agent="codex-cloud",
                  branch="agent/codex-cloud/7-task", status="pr-open",
                  hardware="not-required", validation="fixture software tests", scope=["docs/example.md"])
    result["class"] = "A"
    result.update(changes)
    if result["status"] in {"software-validated", "ready-to-merge"}:
        result["software"] = dict(result="PASS", head=HEAD, base=BASE, url="https://example.org/ci")
    return result


def pull(**changes):
    result = dict(number=12, body="Task: #7", state="open", draft=False, mergeable=True, labels=[],
                  head=dict(ref="agent/codex-cloud/7-task", sha=HEAD, repo=dict(full_name="owner/repo")),
                  base=dict(ref="main", sha=BASE, repo=dict(full_name="owner/repo")))
    result.update(changes)
    return result


def run(name, conclusion="success", status="completed"):
    return dict(name=name, conclusion=conclusion, status=status, html_url="https://example.org/ci")


class FakeGitHub:
    repo = "owner/repo"

    def __init__(self, task=None, pr=None, checks=None, behind=0):
        task = task or record()
        self.body = "Task prose\n```regear-task\n" + json.dumps(task) + "\n```"
        self.pull = pr or pull()
        self.list_pulls = [copy.deepcopy(self.pull)]
        self.labels = [{"name": "agent-task"}]
        self.check_pages = [checks if checks is not None else [run(n) for n in o.REQUIRED_CHECKS]]
        self.behind = behind
        self.calls = []

    def pages(self, path):
        self.calls.append(("GET", path))
        if path == "issues?state=open":
            return [dict(number=7, body=self.body, state="open", labels=self.labels)]
        if path == "pulls?state=open":
            return copy.deepcopy(self.list_pulls)
        raise AssertionError(path)

    def api(self, path, method="GET", payload=None):
        if method != "GET" or payload is not None:
            raise AssertionError("discovery attempted a write")
        self.calls.append((method, path))
        if path == "":
            return {"default_branch": "main"}
        if path == "pulls/12":
            return copy.deepcopy(self.pull)
        if path.startswith("commits/"):
            page = int(path.rsplit("page=", 1)[1])
            return {"check_runs": self.check_pages[page - 1] if page <= len(self.check_pages) else []}
        if path == f"compare/{BASE}...{HEAD}":
            return {"behind_by": self.behind}
        raise AssertionError(path)


class DiscoveryTests(unittest.TestCase):
    def actions(self, fake):
        return o.next_actions("codex-cloud", OWNER, o.gather_rows(fake))

    def test_real_cli_routes_exact_owned_failure_without_writes(self):
        f = FakeGitHub(checks=[run(n, "failure") for n in o.REQUIRED_CHECKS])
        output = io.StringIO()
        with patch.object(o.gc, "GitHub", return_value=f), patch.object(o.sys, "argv", [
                "discovery", "next", "--repo", "owner/repo", "--agent", "codex-cloud", "--session", OWNER]), \
                patch("sys.stdout", output):
            o.main()
        [action] = json.loads(output.getvalue())
        self.assertEqual(("rework", 7, 12, HEAD, BASE),
                         tuple(action[k] for k in ("kind", "task", "pr", "head", "base")))
        self.assertEqual(["required CI failed"], action["reasons"])
        self.assertTrue(f.calls)
        self.assertEqual({"GET"}, {method for method, _ in f.calls})

    def test_stale_base_and_conflicts_route_completed_ci_only(self):
        for status in ("pr-open", "software-validated", "ready-to-merge"):
            f = FakeGitHub(record(status=status), behind=1)
            [action] = self.actions(f)
            self.assertEqual(["base refresh required"], action["reasons"])
        f = FakeGitHub(pr=pull(mergeable=False))
        self.assertEqual(["base refresh required"], self.actions(f)[0]["reasons"])

    def test_review_requested_repair_requires_separately_admitted_canonical_state(self):
        task = record(status="review-requested")
        task["software"] = dict(result="PASS", head=HEAD, base=BASE, url="https://example.org/ci")
        f = FakeGitHub(task, behind=1)
        with self.assertRaises(ValueError):
            self.actions(f)  # Current main has not admitted this canonical state.
        # Compatibility with the preserved stack, not a production policy edit.
        with patch.object(o.gc, "ACTIVE", o.gc.ACTIVE | {"review-requested"}):
            [action] = self.actions(f)
        self.assertEqual(("rework", HEAD, BASE), (action["kind"], action["head"], action["base"]))
        self.assertEqual(["base refresh required"], action["reasons"])

    def test_pending_missing_unknown_and_mixed_running_checks_refuse_even_when_behind(self):
        for checks in ([], [run("foundation")], [run("foundation", None, "in_progress")],
                       [run("foundation", "failure"), run("privileged-user-delivery", None, "queued")],
                       [run("foundation", "mystery"), run("privileged-user-delivery")]):
            with self.subTest(checks=checks):
                self.assertEqual([], self.actions(FakeGitHub(checks=checks, behind=1)))

    def test_all_pages_are_read_and_running_page_defers_earlier_failure(self):
        first = [run(n) for n in o.REQUIRED_CHECKS] + [run("other")] * 98
        f = FakeGitHub(behind=1)
        f.check_pages = [first, [run("late", "failure")]]
        self.assertEqual(["required CI failed", "base refresh required"], self.actions(f)[0]["reasons"])
        self.assertTrue(any("page=2" in path for _, path in f.calls))
        first[0] = run("foundation", "failure")
        f.check_pages = [first, [run("late", None, "in_progress")]]
        self.assertEqual([], self.actions(f))

    def test_check_page_bound_is_unknown_instead_of_false_success(self):
        f = FakeGitHub(behind=1)
        f.check_pages = [[run(n) for n in o.REQUIRED_CHECKS] + [run("other")] * 98] * o.MAX_CHECK_PAGES
        self.assertEqual([], self.actions(f))

    def test_holds_drafts_blocked_other_owner_and_foreign_repo_are_passive(self):
        cases = [FakeGitHub(record(owner="other"), behind=1),
                 FakeGitHub(record(agent="claude"), behind=1),
                 FakeGitHub(record(status="blocked"), behind=1),
                 FakeGitHub(pr=pull(draft=True), behind=1),
                 FakeGitHub(pr=pull(state="closed"), behind=1)]
        for label in o.HOLD_LABELS:
            f = FakeGitHub(behind=1)
            f.pull["labels"] = [{"name": label}]
            cases.append(f)
            f = FakeGitHub(behind=1)
            f.labels.append({"name": label})
            cases.append(f)
        f = FakeGitHub(behind=1)
        f.pull["head"]["repo"]["full_name"] = "other/repo"
        cases.append(f)
        for f in cases:
            self.assertEqual([], self.actions(f))

    def test_duplicate_prs_fresh_linkage_drift_and_wrong_branch_fail_closed(self):
        f = FakeGitHub(behind=1)
        f.list_pulls.append(pull(number=13))
        self.assertEqual([], self.actions(f))
        f = FakeGitHub(behind=1)
        f.pull["body"] = "Task: #8"
        self.assertEqual([], self.actions(f))
        f = FakeGitHub(behind=1)
        f.pull["head"]["ref"] = "other-branch"
        self.assertEqual([], self.actions(f))

    def test_crlf_uses_unchanged_current_parser_and_duplicates_remain_invalid(self):
        f = FakeGitHub(pr=pull(body="Summary\r\nTask: #7\r\n"), behind=1)
        self.assertEqual("rework", self.actions(f)[0]["kind"])
        f.pull["body"] += "Task: #8\r\n"
        self.assertEqual([], self.actions(f))

    def test_read_failures_never_fall_back_to_backlog_claim(self):
        f = FakeGitHub(behind=1)
        f.body = "invalid canonical record"
        with self.assertRaises(ValueError):
            self.actions(f)
        f = FakeGitHub(behind=1)
        original = f.api
        def fail(path, method="GET", payload=None):
            if path.startswith("commits/"):
                raise ValueError("unavailable")
            return original(path, method, payload)
        f.api = fail
        with self.assertRaises(ValueError):
            self.actions(f)


class WorkSlotTests(unittest.TestCase):
    def row(self, number=7, **changes):
        row = dict(number=number, record=record(), labels=[], pr=pull(), faults=[],
                   checks={"state": "success"}, behind_by=1)
        row.update(changes)
        return row

    def test_one_stable_repair_consumes_slot_and_never_routes_integration(self):
        low = self.row(labels=["P2"])
        high = self.row(8, labels=["P1"])
        backlog = self.row(9, record=record(owner=None, status="backlog", revision=1,
                                          branch="agent/codex-cloud/9-task", scope=["docs/other.md"]))
        rows = [low, high, backlog]
        before = copy.deepcopy(rows)
        [action] = o.next_actions("codex-cloud", OWNER, rows)
        self.assertEqual(("rework", 8), (action["kind"], action["task"]))
        self.assertEqual([action], o.next_actions("codex-cloud", OWNER, list(reversed(rows))))
        self.assertEqual(before, rows)

    def test_owned_implementation_preempts_repair_and_backlog(self):
        busy = self.row(8, record=record(status="in-progress"))
        self.assertEqual(["implement"], [a["kind"] for a in o.next_actions("codex-cloud", OWNER, [self.row(), busy])])

    def test_one_waiting_candidate_may_claim_but_two_or_scope_collision_cannot(self):
        waiting = self.row(behind_by=0)
        backlog = self.row(9, record=record(owner=None, status="backlog", revision=1,
                                          branch="agent/codex-cloud/9-task", scope=["docs/other.md"]))
        self.assertEqual(["claim"], [a["kind"] for a in o.next_actions("codex-cloud", OWNER, [waiting, backlog])])
        second = self.row(8, behind_by=0)
        self.assertEqual([], o.next_actions("codex-cloud", OWNER, [waiting, second, backlog]))
        backlog["record"]["scope"] = waiting["record"]["scope"]
        self.assertEqual([], o.next_actions("codex-cloud", "new-owner", [waiting, backlog]))

    def test_no_family_hardware_review_or_merge_action_is_introduced(self):
        for status in ("blocked", "hardware-required", "hardware-validated"):
            rows = [self.row(record=record(status=status, hardware="required"))]
            self.assertEqual([], o.next_actions("codex-local", OWNER, rows))


if __name__ == "__main__":
    unittest.main()
