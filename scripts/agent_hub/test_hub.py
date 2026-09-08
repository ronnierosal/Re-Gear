import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from hub import Hub, Conflict


class HubTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.hub = Hub(Path(self.temp.name) / 'hub.sqlite3')
        self.hub.init()
        for session, agent in [('lead', 'codex'), ('worker', 'claude'), ('other', 'codex')]:
            self.hub.register(session, agent, session, 'worktrees/' + session)
        self.do('lead', 'claim_stream', stream='egpu', rev=1)

    def do(self, actor, op, **kwargs):
        return self.hub.apply(actor, {'op': op, **kwargs})

    def task(self, key='t1', stream='egpu', paths=None, deps=None):
        return self.do('lead', 'create_task', id=key, stream=stream, title='A bounded task',
                       branch='codex/' + key, paths=['src/a.py'] if paths is None else paths,
                       dependencies=deps or [])

    def claim(self, key='t1', actor='lead'):
        return self.do(actor, 'claim_task', id=key, rev=1)

    def message(self, recipient='worker'):
        return self.do('lead', 'send', stream='egpu', to=recipient, subject='Review', body='Please review the bounded patch.')

    def test_init_preserves_existing_owner_and_messages(self):
        self.message()
        self.hub.init()
        status = self.hub.status()
        self.assertEqual('lead', next(s['owner'] for s in status['streams'] if s['id'] == 'egpu'))
        self.assertEqual(1, len(status['messages']))

    def test_session_id_cannot_be_silently_reassigned(self):
        with self.assertRaises(Conflict):
            self.hub.register('lead', 'claude', 'other', 'elsewhere')

    def test_new_stream_has_an_inbox_and_owner(self):
        stream = self.do('worker', 'create_stream', id='offline', title='Offline Readiness')
        self.assertEqual('worker', stream['owner'])
        self.do('lead', 'send', stream='offline', subject='First message', body='New inbox')
        self.assertEqual(1, len(self.hub.inbox('worker')['messages']))

    def test_read_is_explicit_and_recipient_scoped(self):
        message = self.message()
        for _ in range(2):
            self.assertEqual('unread', self.hub.inbox('worker')['messages'][0]['receipt'])
        with self.assertRaises(Conflict):
            self.do('other', 'receipt', id=message['id'], state='read')
        self.do('worker', 'receipt', id=message['id'], state='read')
        self.assertEqual('read', self.hub.inbox('worker')['messages'][0]['receipt'])
        self.do('worker', 'receipt', id=message['id'], state='acknowledged')
        with self.assertRaises(Conflict):
            self.do('worker', 'receipt', id=message['id'], state='read')

    def test_reply_requires_original_recipient_and_is_atomic(self):
        message = self.message()
        with self.assertRaises(ValueError):
            self.do('worker', 'send', stream='egpu', to='other', subject='Reply', body='x', reply_to=message['id'])
        self.assertEqual(1, len(self.hub.status()['messages']))
        self.do('worker', 'send', stream='egpu', to='lead', subject='Reply', body='Reviewed', reply_to=message['id'])
        self.assertEqual('replied', self.hub.inbox('worker')['messages'][0]['receipt'])

    def test_shared_inbox_unassigned_is_visible_but_not_acknowledged(self):
        m = self.do('lead', 'send', stream='auto-tdp', subject='Work', body='Pending lead')
        self.assertIn(m['id'], [m['id'] for m in self.hub.status()['messages']])
        with self.assertRaises(Conflict):
            self.do('worker', 'receipt', id=m['id'], state='read')
        self.do('worker', 'claim_stream', stream='auto-tdp', rev=1)
        self.assertEqual('unread', self.hub.inbox('worker')['messages'][0]['receipt'])

    def test_receipts_are_not_inherited_by_new_lead(self):
        m = self.do('worker', 'send', stream='egpu', subject='Shared', body='Pending')
        self.do('lead', 'receipt', id=m['id'], state='acknowledged')
        transfer = self.do('lead', 'offer_transfer', kind='stream', id='egpu', rev=2, to='other', note='New lead')
        self.do('other', 'accept_transfer', id=transfer['id'])
        self.assertEqual('unread', self.hub.inbox('other')['messages'][0]['receipt'])

    def test_worker_can_claim_without_taking_stream_and_only_owner_updates(self):
        self.task()
        self.claim(actor='worker')
        self.assertEqual('lead', self.hub.status()['streams'][0]['owner'])
        with self.assertRaises(Conflict):
            self.do('lead', 'update_task', id='t1', rev=2, state='blocked', note='Not mine')

    def test_two_agents_claim_same_task_only_one_wins(self):
        self.task()
        def attempt(actor):
            try:
                self.claim(actor=actor)
                return 'won'
            except Conflict:
                return 'conflict'
        with ThreadPoolExecutor(2) as pool:
            self.assertCountEqual(['won', 'conflict'], list(pool.map(attempt, ['worker', 'other'])))

    def test_scope_expansion_is_atomic_and_invalidates_evidence(self):
        self.task(); self.claim()
        self.task('t2', paths=['docs']); self.claim('t2', 'worker')
        before = self.hub.status()
        with self.assertRaises(Conflict):
            self.do('lead', 'update_task', id='t1', rev=2, paths=['src/a.py', 'docs/index.md'], note='Index needed')
        self.assertEqual(before, self.hub.status())
        self.do('lead', 'update_task', id='t1', rev=2, state='review', evidence='Old check')
        with self.assertRaises(Conflict):
            self.do('lead', 'update_task', id='t1', rev=3, paths=['src'], note='Widen scope')
        result = self.do('lead', 'update_task', id='t1', rev=3, state='in_progress', paths=['src'], note='Same task needs sibling helper')
        self.assertEqual('', result['evidence'])
        self.assertEqual(['src'], json.loads(result['paths']))

    def test_routine_task_can_finish_without_review_ceremony(self):
        self.task(); self.claim()
        result = self.do('lead', 'update_task', id='t1', rev=2, state='done', evidence='abc: tests passed; acceptance met')
        self.assertEqual('done', result['state'])

    def test_snapshot_contains_handoff_and_does_not_mutate(self):
        self.do('lead', 'create_task', id='handoff', stream='coordination', title='Voice handoff',
                branch='agent/handoff', note='Scope: docs. Done when: links pass. Next: inspect.')
        before = self.hub.status()
        snapshot = self.hub.snapshot()
        self.assertIn('owner: available', snapshot)
        self.assertIn('Done when: links pass', snapshot)
        self.assertIn('not a live claim store', snapshot)
        self.assertEqual(before, self.hub.status())

    def test_source_cli_requires_shared_database(self):
        source = Path(self.temp.name) / 'source' / 'hub.py'
        source.parent.mkdir()
        source.write_bytes(Path(__file__).with_name('hub.py').read_bytes())
        result = subprocess.run([sys.executable, '-B', str(source), 'init'],
                                text=True, capture_output=True)
        self.assertEqual(2, result.returncode)
        self.assertIn('shared workspace', result.stderr)

    def test_installed_cli_uses_shared_location_from_other_cwd(self):
        script = Path(self.temp.name) / 'agent-hub' / 'hub.py'
        script.parent.mkdir()
        script.write_bytes(Path(__file__).with_name('hub.py').read_bytes())
        result = subprocess.run([sys.executable, '-B', str(script), 'init'],
                                cwd=self.temp.name, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue((script.parent / 'data' / 'hub.sqlite3').is_file())

    def completed(self, key, note, stream='egpu', deps=None):
        self.task(key, stream=stream, paths=[], deps=deps)
        self.claim(key)
        return self.do('lead', 'update_task', id=key, rev=2, state='done',
                       note=note, evidence='abc: tests passed; PR merge must be checked independently')

    def test_docs_queue_routes_completed_work_and_preserves_unknowns(self):
        self.completed('none', 'Result: refactor\nDocumentation impact: none')
        self.completed('wiki', 'Result: behavior changed\r\nDocumentation impact: WiKi\r\n')
        self.completed('legacy', 'Old task with no impact marker')
        self.completed('invalid', 'Documentation impact: none, maybe Wiki')
        self.completed('ambiguous', 'Documentation impact: none\nDocumentation impact: Wiki')
        self.completed('docs-own', 'Documentation impact: Wiki', stream='documentation')
        self.task('unfinished', paths=[]); self.claim('unfinished')
        before, history = self.hub.status(), self.hub.history()
        rows = self.hub.docs_queue()['pending']
        self.assertEqual({'wiki': 'wiki', 'legacy': 'unassessed', 'invalid': 'unassessed', 'ambiguous': 'unassessed'},
                         {row['task']['id']: row['documentation_impact'] for row in rows})
        self.assertEqual(before, self.hub.status())
        self.assertEqual(history, self.hub.history())

    def test_docs_review_requires_marker_and_dependency_and_done(self):
        self.completed('source', 'Documentation impact: multiple')
        self.completed('unrelated', 'Other docs work', stream='documentation', deps=['source'])
        self.completed('wrong-link', 'Documentation review: source', stream='documentation')
        self.assertEqual(1, len(self.hub.docs_queue()['pending']))
        self.task('review', stream='documentation', paths=[], deps=['source']); self.claim('review')
        self.do('lead', 'update_task', id='review', rev=2, state='blocked',
                note='Documentation review: source\nPublication unavailable')
        self.assertEqual('blocked', self.hub.docs_queue()['pending'][0]['reviews'][0]['state'])
        self.do('lead', 'update_task', id='review', rev=3, state='cancelled',
                note='Documentation review: source\nSuperseded by successor')
        self.assertEqual(1, len(self.hub.docs_queue()['pending']))
        self.completed('successor', 'Documentation review: source\nReviewed: no public change needed.',
                       stream='documentation', deps=['source'])
        self.assertEqual([], self.hub.docs_queue()['pending'])

    def test_docs_queue_cli_and_batched_review(self):
        self.completed('readme', 'Documentation impact: README')
        self.completed('news', 'Documentation impact: Discussion')
        cmd = [sys.executable, '-B', str(Path(__file__).with_name('hub.py')), '--db', str(self.hub.path), 'docs-queue']
        result = subprocess.run(cmd, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(2, len(json.loads(result.stdout)['pending']))
        self.completed('batch', 'Documentation review: readme\nDocumentation review: news\nPublished with readback.',
                       stream='documentation', deps=['readme', 'news'])
        self.assertEqual([], self.hub.docs_queue()['pending'])

    def test_documentation_templates_round_trip(self):
        directory = Path(__file__).parent
        self.task('source-task-id', paths=[]); self.claim('source-task-id')
        completion = json.loads((directory / 'completion.example.json').read_text(encoding='utf-8-sig'))
        completion['id'] = 'source-task-id'
        self.hub.apply('lead', completion)
        self.assertEqual('wiki', self.hub.docs_queue()['pending'][0]['documentation_impact'])
        review = json.loads((directory / 'review.example.json').read_text(encoding='utf-8-sig'))
        self.hub.apply('worker', review)
        self.do('worker', 'claim_task', id=review['id'], rev=1)
        self.do('worker', 'update_task', id=review['id'], rev=2, state='done',
                note=review['note'] + '\nDecision: no public change; internal-only task.',
                evidence='Source reviewed; no public behavior change.')
        self.assertEqual([], self.hub.docs_queue()['pending'])

    def test_transfer_requires_acceptance_and_matching_revision(self):
        self.task(); self.claim()
        transfer = self.do('lead', 'offer_transfer', kind='task', id='t1', rev=2, to='worker', note='Own this test slice')
        self.assertEqual('lead', self.hub.status()['tasks'][0]['owner'])
        with self.assertRaises(Conflict):
            self.do('other', 'accept_transfer', id=transfer['id'])
        self.do('worker', 'accept_transfer', id=transfer['id'])
        self.assertEqual('worker', self.hub.status()['tasks'][0]['owner'])
        with self.assertRaises(Conflict):
            self.do('worker', 'accept_transfer', id=transfer['id'])

    def test_stale_transfer_does_not_overwrite_new_task_state(self):
        self.task(); self.claim()
        t = self.do('lead', 'offer_transfer', kind='task', id='t1', rev=2, to='worker', note='Handoff')
        self.do('lead', 'update_task', id='t1', rev=2, state='blocked', note='Changed contract')
        with self.assertRaises(Conflict):
            self.do('worker', 'accept_transfer', id=t['id'])
        self.assertEqual('lead', self.hub.status()['tasks'][0]['owner'])
        self.do('lead', 'cancel_transfer', id=t['id'])

    def test_two_concurrent_claims_only_one_wins(self):
        def attempt(actor):
            try:
                self.do(actor, 'claim_stream', stream='quick-access', rev=1)
                return 'won'
            except Conflict:
                return 'conflict'
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(attempt, ['worker', 'other']))
        self.assertCountEqual(['won', 'conflict'], results)

    def test_cross_workstream_directory_and_case_overlap(self):
        self.task(paths=['src']); self.claim()
        self.do('worker', 'claim_stream', stream='auto-tdp', rev=1)
        self.task('t2', 'auto-tdp', ['SRC/nested/b.py'])
        with self.assertRaises(Conflict):
            self.claim('t2', 'worker')
        self.assertIsNone(self.hub.status()['tasks'][1]['owner'])

    def test_concurrent_overlapping_tasks_only_one_claims(self):
        self.task('t1'); self.task('t2')
        def attempt(key):
            try:
                self.claim(key)
                return 'won'
            except Conflict:
                return 'conflict'
        with ThreadPoolExecutor(2) as pool:
            self.assertCountEqual(['won', 'conflict'], list(pool.map(attempt, ['t1', 't2'])))

    def test_dependencies_and_evidence_gate_done(self):
        self.task(); self.task('t2', paths=['src/b.py'], deps=['t1'])
        with self.assertRaises(Conflict): self.claim('t2')
        self.claim()
        with self.assertRaises(ValueError): self.do('lead', 'update_task', id='t1', rev=2, state='done')
        with self.assertRaises(ValueError): self.do('lead', 'update_task', id='t1', rev=2, state='review')
        reviewed = self.do('lead', 'update_task', id='t1', rev=2, state='review', evidence='Revision abc: targeted tests passed')
        done = self.do('lead', 'update_task', id='t1', rev=reviewed['rev'], state='done')
        self.assertEqual('done', done['state'])
        self.claim('t2')

    def test_unknown_and_self_dependencies_rejected(self):
        with self.assertRaises(ValueError): self.task(deps=['t1'])
        self.assertEqual([], self.hub.status()['tasks'])

    def test_return_to_work_invalidates_evidence(self):
        self.task(); self.claim()
        self.do('lead', 'update_task', id='t1', rev=2, state='review', evidence='Old tests')
        self.do('lead', 'update_task', id='t1', rev=3, state='in_progress')
        with self.assertRaises(ValueError): self.do('lead', 'update_task', id='t1', rev=4, state='review')

    def test_stale_update_preserves_state_and_event_log(self):
        self.task(); self.claim()
        before = len(self.hub.history())
        with self.assertRaises(Conflict): self.do('lead', 'update_task', id='t1', rev=1, state='blocked', note='Stale')
        self.assertEqual(before, len(self.hub.history()))
        self.assertEqual('in_progress', self.hub.status()['tasks'][0]['state'])

    def test_cancel_releases_scope_but_does_not_satisfy_dependency(self):
        self.task(); self.claim(); self.task('t2')
        self.do('lead', 'update_task', id='t1', rev=2, state='cancelled', note='Superseded')
        self.claim('t2')
        self.task('t3', paths=['elsewhere.py'], deps=['t1'])
        with self.assertRaises(Conflict): self.claim('t3')

    def test_paths_are_not_escape_hatches(self):
        for path in ['../main.py', '/main.py', 'C:/a', 'src/../a', 'src/*', './a']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.task(paths=[path])
        self.assertEqual([], self.hub.status()['tasks'])

    def test_dashboard_escapes_message_html_and_does_not_mark_read(self):
        self.do('lead', 'send', stream='egpu', to='worker', subject='<script>bad()</script>', body='<img src=x onerror=alert(1)>')
        destination = Path(self.temp.name) / 'dashboard.html'
        self.hub.export_html(destination)
        source = destination.read_text(encoding='utf-8')
        self.assertNotIn('<script>', source)
        self.assertIn('&lt;script&gt;', source)
        self.assertIn("default-src 'none'", source)
        self.assertEqual('unread', self.hub.inbox('worker')['messages'][0]['receipt'])

    def test_cli_round_trip_and_errors(self):
        cmd = [sys.executable, '-B', str(Path(__file__).with_name('hub.py')), '--db', str(self.hub.path)]
        result = subprocess.run(cmd + ['apply', '--session', 'lead'], input=json.dumps({'op': 'send', 'stream': 'egpu', 'to': 'worker', 'subject': 'CLI', 'body': 'Hello'}), text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('CLI', json.loads(result.stdout)['subject'])
        result = subprocess.run(cmd + ['apply', '--session', 'lead'], input='{}', text=True, capture_output=True)
        self.assertEqual(2, result.returncode)
        self.assertIn('error', json.loads(result.stderr))


if __name__ == '__main__':
    unittest.main()
