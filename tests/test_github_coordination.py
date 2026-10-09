"""Task arbitration and recorded-evidence gates; no network or hardware actions."""
import copy
import importlib.util
import json
import subprocess
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
    result = dict(number=12, body="Task: #444", draft=False, changed_files=1, html_url="https://example.org/pr",
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
            files = [{"filename": "docs/example.md"}]

            def pages(self, path):
                return self.files

            def api(self, path):
                return {"state": self.state, "labels": [{"name": "agent-task"}],
                        "body": "```regear-task\n" + json.dumps(ready()) + "\n```"}
        fake = Fake()
        c.check_pr(fake, pr(), [], [pr()])
        with self.assertRaisesRegex(ValueError, "share this head"):
            c.check_pr(fake, pr(), [], [pr(), pr(number=13)])
        with self.assertRaisesRegex(ValueError, "share this head"):
            c.check_pr(fake, pr(), [], [pr(), pr(number=13, body="Task: #555")])
        for files in [[{"filename": "other.md"}], [{"filename": "docs/example.md", "previous_filename": "other.md"}], []]:
            fake.files = files
            with self.assertRaisesRegex(ValueError, "scope|inventory"):
                c.check_pr(fake, pr(), [], [pr()])
        fake.files = [{"filename": "docs/example.md"}]
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
            run.return_value.stdout = "HTTP/2.0 200 OK\n\n{}"
            c.GitHub("owner/repo").api("issues/444", "PATCH", {"body": "$(evil)\n`evil`"})
            args, kwargs = run.call_args
            self.assertIsInstance(args[0], list)
            self.assertNotIn("shell", kwargs)
            self.assertEqual(kwargs["encoding"], "utf-8")
            self.assertEqual(json.loads(kwargs["input"])["body"], "$(evil)\n`evil`")

    def test_pagination_uses_correct_url_separator(self):
        github = c.GitHub("owner/repo")
        with patch.object(github, "api", return_value=[]) as api:
            github.pages("pulls/445/files")
            api.assert_called_once_with("pulls/445/files?per_page=100&page=1")
        with patch.object(github, "api", return_value=[]) as api:
            github.pages("pulls?state=open")
            api.assert_called_once_with("pulls?state=open&per_page=100&page=1")

    def test_workflow_never_checks_out_pr_head_or_interpolates_inputs(self):
        root = Path(__file__).parents[1]
        for name in ["agent-coordination.yml", "coordination-gate.yml"]:
            text = (root / ".github/workflows" / name).read_text()
            self.assertIn("github.event.repository.default_branch", text)
            self.assertNotIn("github.event.pull_request.head", text)
            self.assertNotIn("${{ inputs.", text)
            self.assertIn("persist-credentials: false", text)

    def test_closing_duplicate_pr_refreshes_surviving_status(self):
        text = (Path(__file__).parents[1] / ".github/workflows/coordination-gate.yml").read_text()
        pr_events = text.split("pull_request_target:", 1)[1].split("issues:", 1)[0]
        self.assertIn("closed", pr_events)

    def test_hardware_queue_checks_live_pr_revision(self):
        candidate = record(status="hardware-required", hardware="required", software=ev(), review=ev(reviewer="other"))
        class Fake:
            pulls = [pr()]
            extra_tasks = []

            def tasks(self):
                return [(444, candidate)] + self.extra_tasks

            def pages(self, path):
                return self.pulls
        fake = Fake()
        self.assertTrue(c.queue(fake)[0]["hardware_queue_ready"])
        for changed_pr in [pr(draft=True), pr(head={"ref": "agent/task", "sha": HEAD, "repo": {"full_name": "fork/repo"}})]:
            fake.pulls = [changed_pr]
            self.assertFalse(c.queue(fake)[0]["hardware_queue_ready"])
        fake.pulls = [pr(), pr(number=13, body="Task: #555")]
        self.assertFalse(c.queue(fake)[0]["hardware_queue_ready"])
        fake.pulls = [pr()]
        fake.extra_tasks = [(555, record(branch="other"))]
        self.assertFalse(c.queue(fake)[0]["hardware_queue_ready"])
        fake.extra_tasks = []
        candidate["review"]["reviewer"] = candidate["owner"]
        self.assertFalse(c.queue(fake)[0]["hardware_queue_ready"])
        candidate["review"]["reviewer"] = "other"
        candidate["class"] = "D"
        self.assertFalse(c.queue(fake)[0]["hardware_queue_ready"])
        candidate["procedure_approval"] = "https://example.org/approved"
        self.assertTrue(c.queue(fake)[0]["hardware_queue_ready"])
        candidate["software"]["head"] = BASE
        row = c.queue(fake)[0]
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
                return [pr()] if path == 'pulls?state=open' else []

            def tasks(self):
                raise ValueError("bad managed record")

            def api(self, path, method="GET", payload=None):
                self.calls.append(payload)
        fake = Fake()
        with self.assertRaises(ValueError):
            c.refresh(fake)
        self.assertEqual([x["state"] for x in fake.calls], ["failure"])

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


class PublicationTests(unittest.TestCase):
    class Fake:
        def __init__(self, fail=(), inventory_error=None):
            self.pulls = [pr(), pr(number=13, body='Task: #445', head={**pr()['head'], 'sha': 'c' * 40, 'ref': 'agent/other'})]
            other = ready(branch='agent/other', scope=['docs/other.md'])
            other.update(software=ev(head='c'*40), review=ev(head='c'*40, reviewer='other'))
            self.records = [(444, ready()), (445, other)]
            self.fail, self.inventory_error = fail, inventory_error
            self.posts, self.checked = [], []
            self.statuses = {}

        def tasks(self):
            if self.inventory_error:
                raise self.inventory_error
            return self.records

        def pages(self, path):
            if path == 'pulls?state=open':
                return self.pulls
            if path.startswith('statuses/'):
                return self.statuses.get(path.split('/')[1], [])
            if path.startswith('pulls/'):
                number = int(path.split('/')[1])
                self.checked.append(number)
                return [{'filename': 'docs/example.md' if number == 12 else 'docs/other.md'}]
            raise AssertionError(path)

        def api(self, path, method='GET', payload=None):
            if path.startswith('statuses/') and method == 'POST':
                sha = path.split('/')[1]
                self.posts.append((sha, payload))
                if (sha, payload['state']) in self.fail:
                    raise subprocess.CalledProcessError(1, ['gh', 'api'], stderr='gh: rejected (HTTP 422)')
                self.statuses.setdefault(sha, []).insert(0, dict(payload))
                return {}
            if path.startswith('pulls/'):
                return next(p for p in self.pulls if p['number'] == int(path.split('/')[1]))
            if path.startswith('issues/'):
                r = dict(self.records)[int(path.split('/')[1])]
                return {'state': 'open', 'labels': [{'name': 'agent-task'}], 'body': '```regear-task\n'+json.dumps(r)+'\n```'}
            raise AssertionError(path)

    def test_rejected_pending_is_not_attempted_and_full_validation_runs(self):
        fake = self.Fake(fail={(HEAD, 'pending')})
        c.refresh(fake)
        self.assertEqual(fake.checked, [12, 13])
        self.assertIn(('c'*40, 'success'), [(sha, p['state']) for sha, p in fake.posts])
        self.assertNotIn('pending', [p['state'] for _, p in fake.posts])

    def test_failed_final_post_does_not_strand_next_pr(self):
        fake = self.Fake(fail={(HEAD, 'success')})
        with self.assertRaisesRegex(Exception, 'final'):
            c.refresh(fake)
        self.assertEqual(fake.checked, [12, 13])
        self.assertEqual(fake.posts[-1][1]['state'], 'success')

    def test_invalid_inventory_attempts_every_failure_and_never_success(self):
        fake = self.Fake(fail={(HEAD, 'failure')}, inventory_error=ValueError('invalid record'))
        with self.assertRaisesRegex(Exception, 'invalid record'):
            c.refresh(fake)
        self.assertEqual([p['state'] for _, p in fake.posts], ['failure', 'failure'])
        self.assertFalse(fake.checked)

    def test_real_validator_failure_remains_failure(self):
        fake = self.Fake()
        fake.records[1][1]['review']['reviewer'] = fake.records[1][1]['owner']
        c.refresh(fake)
        self.assertEqual(fake.posts[-1][1]['state'], 'failure')
        self.assertIn('independent reviewer', fake.posts[-1][1]['description'])

    def test_only_newest_exact_four_fields_deduplicates(self):
        payload = dict(context='coordination/pr', state='failure', description='no evidence', target_url='https://example.org/pr')
        for changes in ({}, {'state':'pending'}, {'context':'other'}, {'description':'different'}, {'target_url':None}):
            with self.subTest(changes=changes):
                fake = self.Fake()
                fake.statuses[HEAD] = [dict(payload, **changes)] + ([] if 'context' in changes else [dict(payload)])
                c.post_status(fake, HEAD, payload)
                self.assertEqual(len(fake.posts), 0 if not changes else 1)

    def test_newest_context_selection_and_absent_target(self):
        fake = self.Fake()
        payload = dict(context='coordination/pr', state='pending', description='refresh')
        fake.statuses[HEAD] = [dict(payload, context='other'), dict(payload, target_url=None)]
        c.post_status(fake, HEAD, payload)
        self.assertFalse(fake.posts)

    def test_status_read_failure_is_not_permission_to_post(self):
        fake = self.Fake()
        with patch.object(fake, 'pages', side_effect=subprocess.CalledProcessError(1, ['gh'])):
            with self.assertRaises(subprocess.CalledProcessError):
                c.post_status(fake, HEAD, dict(context='coordination/pr', state='pending', description='refresh'))
        self.assertFalse(fake.posts)

    def test_http_failure_exposes_bounded_sanitized_diagnostic(self):
        error = subprocess.CalledProcessError(1, ['gh'], output='private response', stderr='Authorization: Bearer secret\ngh: Validation Failed (HTTP 422)\nhttps://host/private?token=secret\nghp_abcdefghijklmnopqrstuvwxyz0123456789\n')
        with patch.object(c.subprocess, 'run', side_effect=error):
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                c.GitHub('owner/repo').api('statuses/'+HEAD, 'POST', {'private':'secret'})
        detail = str(raised.exception)
        self.assertIn('HTTP 422', detail)
        self.assertNotIn('secret', detail)
        self.assertNotIn('private response', detail)
        self.assertNotIn('ghp_', detail)
        self.assertLess(len(detail), 1000)

    def test_http_diagnostic_never_preserves_api_controlled_credential_text(self):
        for message in ('rejected {"token":"sensitive_value"}', 'credential=sensitive_value',
                        'Authorization: Bearer sensitive_value', 'https://host/?private=sensitive_value'):
            with self.subTest(message=message):
                error = subprocess.CalledProcessError(1, ['gh'], stderr=f'gh: {message} (HTTP 422)')
                with patch.object(c.subprocess, 'run', side_effect=error):
                    with self.assertRaises(subprocess.CalledProcessError) as raised:
                        c.GitHub('owner/repo').api('statuses/'+HEAD, 'POST', {})
                self.assertIn('HTTP 422', str(raised.exception))
                self.assertNotIn('sensitive_value', str(raised.exception))


class SuccessorRegressionTests(unittest.TestCase):
    def test_unchanged_final_success_revalidates_without_pending_or_posts(self):
        fake = PublicationTests.Fake()
        c.refresh(fake)
        fake.posts.clear()
        fake.checked.clear()
        fake.fail = {(HEAD, 'pending'), ('c' * 40, 'pending')}
        c.refresh(fake)
        self.assertEqual(fake.checked, [12, 13])
        self.assertEqual(fake.posts, [])

    def test_unchanged_final_failure_revalidates_without_posts(self):
        fake = PublicationTests.Fake()
        fake.records[1][1]['review']['reviewer'] = fake.records[1][1]['owner']
        c.refresh(fake)
        fake.posts.clear()
        fake.checked.clear()
        with patch.object(c, 'check_pr', wraps=c.check_pr) as check:
            c.refresh(fake)
        self.assertEqual(check.call_count, 2)
        self.assertEqual(fake.posts, [])

    def test_changed_gate_publishes_failure_then_success_without_pending(self):
        fake = PublicationTests.Fake()
        c.refresh(fake)
        fake.posts.clear()
        fake.records[1][1]['review']['reviewer'] = fake.records[1][1]['owner']
        c.refresh(fake)
        self.assertEqual([(sha, p['state']) for sha, p in fake.posts], [('c' * 40, 'failure')])
        fake.posts.clear()
        fake.records[1][1]['review']['reviewer'] = 'independent'
        c.refresh(fake)
        self.assertEqual([(sha, p['state']) for sha, p in fake.posts], [('c' * 40, 'success')])

    def test_evaluation_read_error_invalidates_old_success_and_aggregates(self):
        fake = PublicationTests.Fake()
        c.refresh(fake)
        fake.posts.clear()
        real_api = fake.api
        def api(path, method='GET', payload=None):
            if path == 'pulls/12':
                raise subprocess.CalledProcessError(1, ['gh'])
            return real_api(path, method, payload)
        with patch.object(fake, 'api', side_effect=api):
            with self.assertRaisesRegex(ValueError, 'evaluation'):
                c.refresh(fake)
        self.assertEqual(fake.statuses[HEAD][0]['state'], 'failure')
        self.assertEqual(fake.statuses['c' * 40][0]['state'], 'success')
        self.assertNotIn('pending', [p['state'] for _, p in fake.posts])

    def test_incomplete_file_inventory_still_fails_closed(self):
        fake = PublicationTests.Fake()
        fake.pulls[0]['changed_files'] = 2
        c.refresh(fake)
        self.assertEqual(fake.statuses[HEAD][0]['state'], 'failure')
        self.assertIn('incomplete PR file inventory', fake.statuses[HEAD][0]['description'])

    def test_head_change_cannot_publish_success_for_the_old_head(self):
        fake = PublicationTests.Fake()
        real_api = fake.api
        def api(path, method='GET', payload=None):
            result = real_api(path, method, payload)
            if path == 'pulls/12':
                return dict(result, head=dict(result['head'], sha='d' * 40))
            return result
        with patch.object(fake, 'api', side_effect=api):
            with self.assertRaisesRegex(ValueError, 'head changed'):
                c.refresh(fake)
        self.assertEqual(fake.statuses[HEAD][0]['state'], 'failure')
        self.assertNotIn('d' * 40, fake.statuses)
        self.assertEqual(fake.statuses['c' * 40][0]['state'], 'success')

    def test_inventory_failure_overwrites_previous_success_and_aggregates(self):
        fake = PublicationTests.Fake()
        c.refresh(fake)
        fake.posts.clear()
        fake.inventory_error = ValueError('invalid managed record')
        with self.assertRaisesRegex(ValueError, 'Invalid task inventory'):
            c.refresh(fake)
        self.assertEqual([p['state'] for _, p in fake.posts], ['failure', 'failure'])

    def test_evaluation_and_failure_publication_errors_both_reported(self):
        fake = PublicationTests.Fake(fail={(HEAD, 'failure')})
        real_api = fake.api
        def api(path, method='GET', payload=None):
            if path == 'pulls/12':
                raise subprocess.CalledProcessError(1, ['gh'])
            return real_api(path, method, payload)
        with patch.object(fake, 'api', side_effect=api):
            with self.assertRaises(ValueError) as raised:
                c.refresh(fake)
        self.assertIn('final evaluation', str(raised.exception))
        self.assertIn('final publication', str(raised.exception))
        self.assertEqual(fake.statuses['c' * 40][0]['state'], 'success')

    def test_header_success_is_stripped_before_json_and_requests_include(self):
        reply = subprocess.CompletedProcess([], 0, 'HTTP/2.0 200 OK\nX-Private: secret\r\n\r\n{"ok":true}', '')
        with patch.object(c.subprocess, 'run', return_value=reply) as run:
            self.assertEqual(c.GitHub('owner/repo').api('issues/444'), {'ok': True})
        self.assertIn('--include', run.call_args.args[0])

    def test_interim_headers_empty_body_and_bounded_malformed_headers(self):
        for text, expected in [('HTTP/1.1 100 Continue\r\n\r\nHTTP/2.0 204 No Content\r\nX: y\r\n\r\n', None),
                               ('HTTP/2.0 200 OK\n\n{}', {})]:
            with patch.object(c.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, text, '')):
                self.assertEqual(c.GitHub('owner/repo').api(''), expected)
        for text in ['\n\n{}', 'HTTP/2.0 200 OK\nBroken header\n\n{}', 'HTTP/2.0 200 OK\nX: '+ 's' * 65536 + '\n\n{}',
                     '{"private":"secret"}', 'HTTP/2.0 999 secret\n\n{}']:
            with self.subTest(text=text[:25]), patch.object(c.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, text, '')):
                with self.assertRaisesRegex(ValueError, 'HTTP response') as raised:
                    c.GitHub('owner/repo').api('')
                self.assertNotIn('secret', str(raised.exception))

    def test_header_error_without_cli_http_suffix_exposes_only_numeric_status(self):
        error = subprocess.CalledProcessError(1, ['gh'], output='HTTP/2.0 422 Unprocessable Entity\nX-Private: secret\n\n{"message":"secret","errors":"private"}', stderr='gh: secret')
        with patch.object(c.subprocess, 'run', side_effect=error):
            with self.assertRaises(c.GitHubAPIError) as raised:
                c.GitHub('owner/repo').api('statuses/'+HEAD, 'POST', {'token': 'secret'})
        self.assertIn('HTTP 422', str(raised.exception))
        self.assertNotIn('secret', repr(vars(raised.exception)))
        self.assertIsNone(raised.exception.output)

    def test_untrusted_body_cannot_forge_header_or_http_reason(self):
        for body in ['{"private":"HTTP/2.0 422"}', 'HTTP/2.0 422 secret\nBad header\n\nsecret',
                     'HTTP/2.0 422 secret\nX: '+ 's' * 65536 + '\n\nsecret']:
            error = subprocess.CalledProcessError(1, ['gh'], output=body, stderr='private')
            with patch.object(c.subprocess, 'run', side_effect=error):
                with self.assertRaises(c.GitHubAPIError) as raised:
                    c.GitHub('owner/repo').api('statuses/'+HEAD, 'POST', {})
            self.assertIn('HTTP summary unavailable', str(raised.exception))
            self.assertNotIn('secret', repr(vars(raised.exception)))

    def test_included_code_wins_over_conflicting_stderr_summary(self):
        error = subprocess.CalledProcessError(1, ['gh'], output='HTTP/2.0 403 Forbidden\n\n{}', stderr='gh: Validation Failed (HTTP 422)')
        with patch.object(c.subprocess, 'run', side_effect=error):
            with self.assertRaises(c.GitHubAPIError) as raised:
                c.GitHub('owner/repo').api('statuses/'+HEAD, 'POST', {})
        self.assertIn('HTTP 403', str(raised.exception))
        self.assertNotIn('422', str(raised.exception))


if __name__ == "__main__":
    unittest.main()
