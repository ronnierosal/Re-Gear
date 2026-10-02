"""Execution boundaries for the optional GitHub Codex adapter (no paid calls)."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import codex_worker as worker

BASE = "a" * 40
HEAD = "b" * 40


def record(owner=None, status="backlog", agent="codex-cloud"):
    return dict(schema=1, owner=owner, agent=agent, branch="agent/codex-cloud/123-example",
                status=status, revision=1, scope=["backend/example.py"],
                validation="Regression and CI", hardware="not-required", **{"class": "A"})


def row(r=None, number=123, labels=()):
    return dict(number=number, record=r or record(), labels=list(labels), pr=None,
                updated_at="2026-10-02T00:00:00Z", faults=[])


def issue(r):
    return dict(state="open", body="```regear-task\n" + json.dumps(r) + "\n```", labels=[])


def report(result="PASS"):
    return dict(summary="Bounded software change", checks="unit tests PASS",
                limitations="No hardware tested", result=result, findings="none")


class FakeGitHub:
    repo = "ronnierosal/Re-Gear"

    def __init__(self, r=None):
        self.record = r or record()
        self.comments = []
        self.calls = []
        self.ack = True
        self.refused = False
        self.forged = False
        self.pr = dict(state="open", number=456, head=dict(sha=HEAD, repo=dict(full_name=self.repo)),
                       base=dict(sha=BASE, repo=dict(full_name=self.repo)), labels=[])

    def api(self, path, method="GET", payload=None):
        self.calls.append((path, method, payload))
        if path == "":
            return dict(default_branch="main")
        if path == "git/ref/heads/main":
            return dict(object=dict(sha=BASE))
        if path in {"issues/123", "issues/124"}:
            return issue(self.record)
        if path.startswith("commits/"):
            return dict(check_runs=[dict(name=name, status="completed", conclusion="success", html_url="https://github.com/ci")
                                    for name in worker.co.REQUIRED_CHECKS])
        if path in {"pulls/456", "pulls/457"}:
            return self.pr
        if path.endswith("/comments") and method == "POST":
            c = dict(id=len(self.comments) + 1, body=payload["body"], user=dict(login="writer", type="User"))
            self.comments.append(c)
            if "```regear-update" in c["body"] and self.ack:
                intent = json.loads(c["body"].split("\n")[1])
                body = f"<!-- regear:update-ack task=123 comment={c['id']} -->\n"
                body += "REFUSED: collision" if self.refused else f"APPLIED as revision {intent['record']['revision']}"
                self.comments.append(dict(id=100, body=body, user=dict(login="other[bot]" if self.forged
                                           else "github-actions[bot]", type="Bot")))
                if not self.refused:
                    self.record = intent["record"]
            return c
        raise AssertionError(path)

    def pages(self, path):
        return self.comments if "/comments" in path else []


class SelectionTests(unittest.TestCase):
    def test_disabled_never_reads_or_claims(self):
        github = FakeGitHub()
        self.assertEqual(worker.plan(github, False, "run")["reason"], "disabled")
        self.assertFalse(github.calls)

    def test_existing_chat_owner_is_never_taken(self):
        self.assertIsNone(worker.select([row(record("someone-else", "claimed"))]))

    def test_wip_is_delegated(self):
        rows = [row(record(worker.SESSION, "in-progress")), row(number=124)]
        action, _ = worker.select(rows)
        self.assertEqual((action["kind"], action["task"]), ("implement", 123))

    def test_hardware_and_protected_paths_not_automatic(self):
        for override in ({"class": "C", "hardware": "required"},
                         {"scope": ["scripts/codex_worker.py"]}, {"scope": [".github/workflows/ci.yml"]}):
            with self.subTest(override=override):
                self.assertIsNone(worker.select([row(dict(record(), **override))]))
        self.assertIsNone(worker.select([row(labels=["hold"])]))

    def test_unsupported_first_claim_does_not_hide_eligible_cloud_backlog(self):
        for override in ({"class": "C", "hardware": "required"}, {"scope": [".github/workflows/ci.yml"]}):
            first = row(dict(record(), **override), labels=["P0"])
            later = row(dict(record(), branch="agent/codex-cloud/124-later"), number=124, labels=["P2"])
            self.assertEqual(worker.select([first, later])[0]["task"], 124)

    def test_only_opposite_family_reviews(self):
        r = record("claude-worker", "review-requested", "claude")
        r["review_request"] = dict(head=HEAD, base=BASE, reviewer_agent="codex-cloud")
        task = row(r)
        task["pr"] = dict(number=456)
        self.assertEqual(worker.select([task])[0]["kind"], "review")
        task["record"]["agent"] = "codex-cloud"
        self.assertIsNone(worker.select([task]))

    def test_failed_ci_does_not_prevent_owned_rework(self):
        task = row(record(worker.SESSION, "changes-requested"))
        task["faults"] = ["required CI failed"]
        self.assertEqual(worker.select([task])[0]["kind"], "rework")

    def test_claim_and_implement_share_retry_fingerprint(self):
        action = dict(kind="claim", task=123, head=None)
        self.assertEqual(worker.fingerprint(action, record(), BASE),
                         worker.fingerprint(dict(action, kind="implement"), record(), BASE))


class IntentTests(unittest.TestCase):
    def test_accepted_claim_is_read_back(self):
        github = FakeGitHub()
        new = worker.intent(github, 123, github.record, dict(github.record, owner=worker.SESSION,
                             status="claimed"), polls=1, pause=lambda _: None)
        self.assertEqual(new["revision"], 2)
        self.assertEqual(github.record, new)
        self.assertTrue(all(method != "PATCH" for _, method, _ in github.calls))

    def test_pending_refused_and_forged_ack_never_authorize_work(self):
        for option in ("ack", "refused", "forged"):
            with self.subTest(option=option):
                github = FakeGitHub()
                setattr(github, option, option != "ack")
                with self.assertRaises(ValueError):
                    worker.intent(github, 123, github.record, dict(github.record, owner=worker.SESSION,
                                  status="claimed"), polls=1, pause=lambda _: None)

    def test_plan_claims_then_starts_only_after_accepted_updates(self):
        github = FakeGitHub()
        with patch.object(worker.co, "gather_rows", return_value=[row()]), patch.object(worker.time, "sleep"):
            plan = worker.plan(github, True, "https://github.com/run")
        self.assertEqual(plan["action"], "implement")
        self.assertEqual(plan["record"]["owner"], worker.SESSION)
        self.assertEqual(plan["record"]["status"], "in-progress")
        self.assertEqual(plan["record"]["revision"], 3)
        with patch.object(worker.co, "gather_rows", return_value=[row()]), patch.object(worker.time, "sleep"):
            # Simulate another planner against the same original candidate marker.
            github.record = record()
            worker.plan(github, True, "https://github.com/run2")
            github.record = record()
            self.assertIn("capped candidates", worker.plan(github, True, "run3")["reason"])


class PublicationTests(unittest.TestCase):
    def make_plan(self, github, action="review"):
        r = record("claude-worker", "review-requested", "claude") if action == "review" else record(worker.SESSION, "in-progress")
        if action == "review":
            r["software"] = dict(result="PASS", head=HEAD, base=BASE, url="https://github.com/ci")
        github.record = r
        return dict(action=action, task=123, record=copy.deepcopy(r), head=HEAD if action == "review" else None,
                    base=BASE, base_branch="main", pr=456 if action == "review" else None,
                    run_url="https://github.com/run", repo=github.repo)

    def test_exact_review_publishes_evidence_block_without_owner_change(self):
        github = FakeGitHub()
        plan = self.make_plan(github)
        worker.publish(github, plan, dict(files=[], report=report()))
        body = github.comments[-1]["body"]
        self.assertIn('"head": "' + HEAD, body)
        self.assertIn('"base": "' + BASE, body)
        self.assertIn('"agent": "codex-cloud"', body)
        self.assertEqual(github.record["owner"], "claude-worker")

    def test_changed_head_base_revision_and_hold_refuse(self):
        for change in ("head", "base", "revision", "hold"):
            github = FakeGitHub()
            plan = self.make_plan(github)
            if change in {"head", "base"}:
                github.pr[change]["sha"] = "c" * 40
            elif change == "revision":
                github.record["revision"] += 1
            else:
                github.pr["labels"] = [dict(name="hold")]
            with self.subTest(change=change), self.assertRaises(ValueError):
                worker.publish(github, plan, dict(files=[], report=report()))
            self.assertFalse(github.comments)

    def test_generated_authority_blocks_rejected(self):
        for text in ("```regear-review", "```regear-update", "<!-- regear:worker-attempt"):
            github = FakeGitHub()
            plan = self.make_plan(github)
            data = report()
            data["summary"] = text
            with self.assertRaises(ValueError):
                worker.publish(github, plan, dict(files=[], report=data))
            self.assertFalse(github.comments)

    def test_scope_modes_duplicates_and_review_edits_refused(self):
        for files in ([dict(path="../secret", mode="100644", content="x")],
                      [dict(path="AGENTS.md", mode="100644", content="x")],
                      [dict(path="backend/example.py", mode="120000", content="x")],
                      [dict(path="backend/example.py", mode="100644", content="x")] * 2,
                      [dict(path="backend/example.py", mode="100644", content="x")]):
            github = FakeGitHub()
            with self.subTest(files=files), self.assertRaises(ValueError):
                worker.publish(github, self.make_plan(github), dict(files=files, report=report()))
            self.assertFalse(github.comments)

    def test_empty_fail_and_missing_review_evidence_refused(self):
        for override in ({"result": "FAIL", "findings": ""}, {"checks": ""}, {"limitations": ""}):
            github = FakeGitHub()
            with self.assertRaises(ValueError):
                worker.publish(github, self.make_plan(github), dict(files=[], report=dict(report(), **override)))


class IntegrationTests(unittest.TestCase):
    def test_capped_review_is_skipped_and_public_comment_cannot_exhaust_budget(self):
        r = record("claude-worker", "review-requested", "claude")
        r["software"] = dict(result="PASS", head=HEAD, base=BASE, url="https://github.com/ci")
        r["review_request"] = dict(head=HEAD, base=BASE, reviewer_agent="codex-cloud")
        first, second = row(r), row(copy.deepcopy(r), number=124)
        first["pr"], second["pr"] = dict(number=456), dict(number=457)
        github = FakeGitHub(r)
        key = worker.fingerprint(dict(kind="review", task=123, head=HEAD, base=BASE), r, BASE)
        marker = f"<!-- regear:worker-attempt {key} -->"
        github.comments = [dict(body=marker, user=dict(login="writer")) for _ in range(worker.LIMIT)]
        with patch.object(worker.co, "gather_rows", return_value=[first, second]):
            plan = worker.plan(github, True, "run")
        self.assertEqual(plan["task"], 124)
        github.comments = [dict(body=marker, user=dict(login="public-commenter")) for _ in range(worker.LIMIT)]
        with patch.object(worker.co, "gather_rows", return_value=[first]):
            self.assertEqual(worker.plan(github, True, "run")["task"], 123)

    def test_real_git_baseline_and_fake_api_publication_preserve_prior_worker_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            worker.git(root, "init", "-q")
            worker.git(root, "config", "user.name", "test")
            worker.git(root, "config", "user.email", "test@example.com")
            (root / "backend").mkdir()
            (root / "backend/example.py").write_text("baseline\n")
            worker.git(root, "add", ".")
            worker.git(root, "commit", "-qm", "base")
            base = worker.git(root, "rev-parse", "HEAD").strip()
            (root / "backend/example.py").write_text("prior worker change\n")
            worker.git(root, "commit", "-qam", "prior worker")
            head = worker.git(root, "rev-parse", "HEAD").strip()
            github = FakeGitHub(dict(record(worker.SESSION, "in-progress"), scope=["backend"]))
            plan = dict(action="implement", task=123, record=copy.deepcopy(github.record),
                        base=base, head=head, pr=None, base_branch="main", run_url="run")
            original = github.api
            def api(path, method="GET", payload=None):
                if path.startswith("git/") and method in {"POST", "PATCH"}:
                    github.calls.append((path, method, payload))
                    return dict(sha="c" * 40)
                if path == "pulls" and method == "POST":
                    github.calls.append((path, method, payload))
                    return dict(number=999)
                return original(path, method, payload)
            github.api = api
            bundle = dict(files=[dict(path="backend/new.py", mode="100644", content="new\n")], report=report())
            with patch.object(worker.Path, "cwd", return_value=root), \
                    patch.object(worker, "default_head", return_value=("main", base)), \
                    patch.object(worker, "branch_head", return_value=head):
                worker.publish(github, plan, bundle)
            tree = next(payload for path, _, payload in github.calls if path == "git/trees")
            self.assertEqual(tree["base_tree"], worker.git(root, "rev-parse", base + "^{tree}").strip())
            self.assertEqual({entry["path"] for entry in tree["tree"]}, {"backend/example.py", "backend/new.py"})
            ref = next(payload for path, method, payload in github.calls if path.startswith("git/refs/heads/"))
            self.assertIs(ref["force"], False)
            commit = next(payload for path, _, payload in github.calls if path == "git/commits")
            self.assertEqual(commit["parents"], [head, base])
            self.assertFalse(any("merge" in path or "statuses" in path for path, _, _ in github.calls))


class ExportTests(unittest.TestCase):
    def test_real_diff_includes_new_files_and_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q", temp], check=True)
            subprocess.run(["git", "-C", temp, "-c", "user.name=test", "-c", "user.email=test@example.com",
                            "commit", "--allow-empty", "-qm", "baseline"], check=True)
            base = worker.git(temp, "rev-parse", "HEAD").strip()
            (root / "backend").mkdir()
            (root / "backend/example.py").write_text("print('example')\n")
            (root / worker.REPORT).write_text(json.dumps(report()))
            output = root / "bundle.json"
            worker.export(temp, dict(action="implement", record=record()), base, output)
            data = json.loads(output.read_text())
            self.assertEqual(data["files"][0]["path"], "backend/example.py")
            output.unlink()
            (root / "backend/example.py").unlink()
            (root / "backend/example.py").symlink_to("/etc/passwd")
            worker.git(temp, "add", "backend/example.py")
            with self.assertRaisesRegex(ValueError, "symlink"):
                worker.changed_files(temp, base, record()["scope"])

    def test_workflow_no_model_write_token_and_artifact_identity(self):
        path = Path(__file__).resolve().parents[1] / ".github/workflows/codex-worker.yml"
        text = path.read_text()
        work = text.split("  work:", 1)[1].split("  publish:", 1)[0]
        self.assertNotIn("REGEAR_CODEX_GITHUB_TOKEN", work)
        self.assertIn("artifact-ids:", work)
        self.assertIn("permission-profile: ':workspace'", work)
        self.assertNotIn("pull_request_target:", text)
        self.assertIn("cancel-in-progress: false", text)


if __name__ == "__main__":
    unittest.main()
