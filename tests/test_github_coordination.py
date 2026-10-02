"""Task arbitration and recorded-evidence gates; no network or hardware actions."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("coord", Path(__file__).parents[1] / "scripts/github_coordination.py")
c = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(c)
HEAD, BASE = "a" * 40, "b" * 40


def record(**changes):
    result = dict(schema=1, owner="codex-one", agent="codex-cloud", branch="agent/task",
                  status="in-progress", hardware="not-required", validation="unit tests",
                  scope=["docs/example.md"], revision=2)
    result["class"] = "A"
    result.update(changes)
    return result


def ev(**changes):
    return dict(dict(result="PASS", head=HEAD, base=BASE, url="https://example.org/evidence"), **changes)


def ready(**changes):
    return record(status="ready-to-merge", software=ev(), review=ev(reviewer="claude-reviewer"), **changes)


def pr(**changes):
    repo = {"full_name": "owner/repo"}
    result = dict(number=12, body="Task: #444", draft=False, html_url="https://example.org/pr",
                  head={"ref": "agent/task", "sha": HEAD, "repo": repo},
                  base={"sha": BASE, "repo": repo})
    result.update(changes)
    return result


class TaskTests(unittest.TestCase):
    def test_duplicate_json_owner_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate JSON"):
            c.load_record('{"owner":"one","owner":"two"}')

    def test_body_preserves_prose_and_exactly_one_block(self):
        body = "Before\n```regear-task\n" + json.dumps(record()) + "\n```\nAfter"
        changed = c.replace(body, record(revision=3))
        self.assertTrue(changed.startswith("Before\n"))
        self.assertTrue(changed.endswith("\nAfter"))
        self.assertEqual(c.parse(changed)["revision"], 3)
        for bad in ["no record", body + body, body.replace('"schema": 1', '"schema": true')]:
            with self.assertRaises(ValueError):
                c.parse(bad)

    def test_stale_revision_and_initial_claim(self):
        old = record(owner=None, status="backlog", revision=1)
        self.assertEqual(c.update(old, record(status="claimed"), 1, []), record(status="claimed"))
        with self.assertRaisesRegex(ValueError, "stale"):
            c.update(old, record(), 2, [])
        with self.assertRaisesRegex(ValueError, "initial claim"):
            c.update(old, record(), 1, [])

    def test_duplicate_claim_cannot_replace_owner(self):
        with self.assertRaisesRegex(ValueError, "transfer"):
            c.update(record(), record(owner="codex-two", revision=3), 2, [])

    def test_transfer_requires_prior_matching_offer_and_acceptance(self):
        offer = {"from": "codex-one", "to": "claude-two", "accepted": False}
        old = record(transfer=offer)
        new = record(owner="claude-two", agent="claude", transfer=dict(offer, accepted=True), revision=3)
        c.update(old, new, 2, [])
        new["transfer"]["accepted"] = False
        with self.assertRaises(ValueError):
            c.update(old, new, 2, [])

    def test_scope_and_branch_collisions(self):
        for other in [record(branch="another", scope=["docs"]), record(scope=["other"])]:
            with self.assertRaises(ValueError):
                c.update(record(), record(revision=3), 2, [(55, other)])
        c.collision(record(), [(55, record(status="merged"))])
        self.assertFalse(c.overlap(["docs/a"], ["docs/ab"]))

    def test_safe_paths_branches_and_fields(self):
        for changes in [{"scope": ["../secret"]}, {"branch": "$(echo bad)"}, {"scope": ["a\\b"]},
                        {"revision": True}, {"unexpected": 4}, {"owner": ["two", "owners"]}]:
            with self.assertRaises(ValueError):
                c.validate(record(**changes))

    def test_docs_only_positive(self):
        c.check(ready(), pr())

    def test_branch_and_task_line(self):
        with self.assertRaisesRegex(ValueError, "branch"):
            c.check(ready(branch="different"), pr())
        for body in ["Task: #444\nTask: #445", "Task: #444; echo bad", "Closes #444"]:
            with self.assertRaises(ValueError):
                c.task_number(body)

    def test_duplicate_pr_and_closed_task_rejected(self):
        class Fake:
            state = "open"

            def api(self, path):
                return {"state": self.state, "labels": [{"name": "agent-task"}],
                        "body": "```regear-task\n" + json.dumps(ready()) + "\n```"}
        fake = Fake()
        c.check_pr(fake, pr(), [], [pr()])
        with self.assertRaisesRegex(ValueError, "exactly one"):
            c.check_pr(fake, pr(), [], [pr(), pr(number=13)])
        fake.state = "closed"
        with self.assertRaisesRegex(ValueError, "open issue"):
            c.check_pr(fake, pr(), [], [pr()])

    def test_stale_software_review_and_self_review(self):
        for change in [{"software": ev(head="c" * 40)}, {"review": ev(base="c" * 40, reviewer="other")},
                       {"review": ev(reviewer="codex-one")}, {"software": ev(result="FAIL")}]:
            candidate = ready()
            candidate.update(change)
            with self.assertRaises(ValueError):
                c.check(candidate, pr())

    def test_bug_and_established_behavior(self):
        with self.assertRaisesRegex(ValueError, "regression"):
            c.check(ready(bug=True), pr())
        candidate = ready(bug=True, regression="new regression test before/after")
        candidate["class"] = "B"
        with self.assertRaisesRegex(ValueError, "behavior"):
            c.check(candidate, pr())
        candidate["behavior"] = "docs/GOLDEN_BEHAVIORS.md#golden-01"
        c.check(candidate, pr())

    def test_hardware_fail_unknown_cloud_and_stale(self):
        candidate = ready(hardware="required")
        candidate["class"] = "C"
        hw = ev(agent="codex-local", tester="local-session", tested_commit=HEAD, artifact="sha256:" + "d" * 64)
        candidate["hardware_evidence"] = hw
        c.check(candidate, pr())
        for change in [{"result": "FAIL"}, {"result": "INCONCLUSIVE"}, {"agent": "codex-cloud"},
                       {"tested_commit": BASE}, {"artifact": "latest.zip"}, {"head": BASE}]:
            failed = copy.deepcopy(candidate)
            failed["hardware_evidence"].update(change)
            with self.assertRaises(ValueError):
                c.check(failed, pr())
        candidate["class"] = "D"
        with self.assertRaisesRegex(ValueError, "approval"):
            c.check(candidate, pr())
        candidate["procedure_approval"] = "https://example.org/approval"
        c.check(candidate, pr())

    def test_advanced_status_needs_software(self):
        for state in ["software-validated", "hardware-required", "hardware-validated", "ready-to-merge"]:
            with self.assertRaises(ValueError):
                c.validate(record(status=state))

    def test_gh_uses_json_stdin_and_argument_array(self):
        with patch.object(c.subprocess, "run") as run:
            run.return_value.stdout = "{}"
            c.GitHub("owner/repo").api("issues/444", "PATCH", {"body": "$(evil)\n`evil`"})
            args, kwargs = run.call_args
            self.assertIsInstance(args[0], list)
            self.assertNotIn("shell", kwargs)
            self.assertEqual(json.loads(kwargs["input"])["body"], "$(evil)\n`evil`")

    def test_workflow_never_checks_out_pr_head_or_interpolates_inputs(self):
        root = Path(__file__).parents[1]
        for name in ["agent-coordination.yml", "coordination-gate.yml"]:
            text = (root / ".github/workflows" / name).read_text()
            self.assertIn("github.event.repository.default_branch", text)
            self.assertNotIn("github.event.pull_request.head", text)
            self.assertNotIn("${{ inputs.", text)
            self.assertIn("persist-credentials: false", text)

    def test_hardware_queue_checks_live_pr_revision(self):
        candidate = record(status="hardware-required", hardware="required", software=ev(), review=ev(reviewer="other"))
        class Fake:
            def tasks(self):
                return [(444, candidate)]

            def pages(self, path):
                return [pr()]
        self.assertTrue(c.queue(Fake())[0]["hardware_queue_ready"])
        candidate["software"]["head"] = BASE
        row = c.queue(Fake())[0]
        self.assertFalse(row["hardware_queue_ready"])
        self.assertIn("stale", row["queue_blocker"])

    def test_public_unmanaged_issues_do_not_poison_inventory(self):
        github = c.GitHub("owner/repo")
        issue = {"number": 444, "labels": [], "body": "```regear-task\ninvalid"}
        with patch.object(github, "pages", return_value=[issue]):
            self.assertEqual(github.tasks(), [])
            issue["labels"] = [{"name": "agent-task"}]
            with self.assertRaises(ValueError):
                github.tasks()

    def test_invalid_inventory_cannot_leave_success_status(self):
        class Fake:
            calls = []

            def pages(self, path):
                return [pr()]

            def tasks(self):
                raise ValueError("bad managed record")

            def api(self, path, method="GET", payload=None):
                self.calls.append(payload)
        fake = Fake()
        with self.assertRaises(ValueError):
            c.refresh(fake)
        self.assertEqual([x["state"] for x in fake.calls], ["pending", "failure"])

    def test_apply_creation_claim_readback_and_labels(self):
        class Fake:
            def __init__(self):
                self.body = "Existing ownership history stays here."
                self.labels = [{"name": "existing"}, {"name": "task:old"}]

            def api(self, path, method="GET", payload=None):
                if path == "":
                    return {"default_branch": "main"}
                if path == "collaborators/writer/permission":
                    return {"permission": "write"}
                if path == "issues/444/labels":
                    self.labels = [{"name": name} for name in payload["labels"]]
                    return self.labels
                if path == "issues/444":
                    if method == "PATCH":
                        self.body = payload["body"]
                    return {"body": self.body, "state": "open", "labels": self.labels}
                raise AssertionError(path)

            def pages(self, path):
                return []

            def tasks(self):
                return [(444, c.parse(self.body))]
        fake = Fake()
        new = record(owner=None, status="backlog", revision=1)
        event = {"inputs": {"issue": "444", "expected_revision": "0", "record_json": json.dumps(new)}}
        env = {"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/main", "GITHUB_ACTOR": "writer"}
        with patch.dict(c.os.environ, env), patch("builtins.print"):
            c.apply_event(fake, event)
            self.assertTrue(fake.body.startswith("Existing ownership history stays here."))
            self.assertIn({"name": "existing"}, fake.labels)
            self.assertIn({"name": "task:backlog"}, fake.labels)
            event["inputs"].update(expected_revision="1", record_json=json.dumps(record(status="claimed")))
            c.apply_event(fake, event)
            self.assertEqual(c.parse(fake.body)["owner"], "codex-one")
            with self.assertRaisesRegex(ValueError, "stale"):
                c.apply_event(fake, event)
        with patch.dict(c.os.environ, dict(env, GITHUB_REF="refs/heads/untrusted")):
            with self.assertRaisesRegex(ValueError, "default branch"):
                c.apply_event(fake, event)


if __name__ == "__main__":
    unittest.main()
