"""Include the standalone hub regression suite in the repository's normal gate."""
import importlib.util
import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

HUB_DIR = Path(__file__).resolve().parents[1] / 'scripts' / 'agent_hub'
sys.path.insert(0, str(HUB_DIR))
import hub
sys.path.remove(str(HUB_DIR))


class CompiledMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'hub.sqlite3'
        self.store = hub.Hub(self.db)
        self.store.init()
        with self.store.connection(True) as db:
            sessions = {(row['owner'] or hub.MAINTAINER) for row in hub.APPROVED_TASKS.values()}
            sessions.add(hub.MAINTAINER)
            for session in sessions:
                db.execute('INSERT INTO sessions VALUES (?,?,?,?,?)',
                           (session, 'codex' if session.startswith('codex') else 'claude', session, 'fixture', hub.now()))
            for stream in {row['stream'] for row in hub.APPROVED_TASKS.values()}:
                db.execute('INSERT OR IGNORE INTO streams(id,title) VALUES (?,?)', (stream, stream))
            for row in hub.APPROVED_TASKS.values():
                self._insert(db, row)
            self._insert(db, hub.APPROVED_MAINTENANCE_ASSIGNMENT)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _insert(db, row):
        columns = tuple(row)
        db.execute(f"INSERT INTO tasks({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                   tuple(row[column] for column in columns))

    def rows_and_events(self):
        with self.store.connection() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM tasks ORDER BY id')]
            events = [dict(r) for r in db.execute('SELECT * FROM events ORDER BY seq')]
        return rows, events

    def test_closeout_exact_fixture_is_atomic_and_preserves_history(self):
        before = {key: copy.deepcopy(hub.APPROVED_TASKS[key]) for key in (
            'tdp-readiness-evidence-setup', 'tdp-lifecycle-gap-verification')}
        result = self.store.close_approved_auto_tdp_records(hub.MAINTAINER)
        self.assertEqual([(r['state'], r['rev']) for r in result['tasks']], [('done', 4), ('done', 7)])
        for row in result['tasks']:
            old = before[row['id']]
            for field in old:
                if field not in ('state', 'rev', 'updated', 'evidence'):
                    self.assertEqual(row[field], old[field])
            self.assertTrue(row['evidence'].startswith(old['evidence']))
            self.assertIn(hub.CLOSEOUT_EVIDENCE[row['id']], row['evidence'])
        self.assertEqual(self.rows_and_events()[1][-1]['action'], 'close_approved_auto_tdp_records')

    def test_closeout_rejects_every_mutated_field_without_any_mutation(self):
        key = 'tdp-lifecycle-gap-verification'
        for field in hub.APPROVED_TASKS[key]:
            with self.subTest(field=field):
                with self.store.connection(True) as db:
                    original = hub.APPROVED_TASKS[key][field]
                    changed = original + 'x' if isinstance(original, str) else original + 1
                    if field == 'stream':
                        db.execute('INSERT INTO streams(id,title) VALUES (?,?)', (changed, changed))
                    if field == 'owner':
                        db.execute('INSERT INTO sessions VALUES (?,?,?,?,?)', (changed, 'other', changed, 'fixture', hub.now()))
                    db.execute(f'UPDATE tasks SET {field}=? WHERE id=?', (changed, key))
                snapshot = self.rows_and_events()
                with self.assertRaises(hub.Conflict):
                    self.store.close_approved_auto_tdp_records(hub.MAINTAINER)
                self.assertEqual(self.rows_and_events(), snapshot)
                with self.store.connection(True) as db:
                    where_key = changed if field == 'id' else key
                    db.execute(f'UPDATE tasks SET {field}=? WHERE id=?', (original, where_key))

    def test_closeout_rejects_wrong_actor_support_record_and_replay(self):
        snapshot = self.rows_and_events()
        with self.assertRaises(hub.Conflict):
            self.store.close_approved_auto_tdp_records('claude-3e188980-234d-4e35-9a46-1b048630ba63')
        self.assertEqual(self.rows_and_events(), snapshot)
        with self.store.connection(True) as db:
            db.execute("UPDATE tasks SET evidence=evidence||'x' WHERE id='tdp-readiness-evidence-recovery-277'")
        changed = self.rows_and_events()
        with self.assertRaises(hub.Conflict):
            self.store.close_approved_auto_tdp_records(hub.MAINTAINER)
        self.assertEqual(self.rows_and_events(), changed)

    def test_operations_use_the_exact_compiled_conditional_consent(self):
        self.assertEqual(hub.CLOSEOUT_EXECUTION_AUTHORIZATION, hub.OPERATION_CONSENT)
        self.assertEqual(hub.RANGE_EXECUTION_AUTHORIZATION, hub.OPERATION_CONSENT)
        self.assertEqual(hub.OPERATION_CONSENT,
                         'https://github.com/ronnierosal/Re-Gear/issues/498#issuecomment-6069197182')
        self.assertEqual(hub.Hub._digest(hub.APPROVED_MAINTENANCE_ASSIGNMENT),
                         hub.MAINTENANCE_ASSIGNMENT_DIGEST)

    def test_closeout_concurrency_has_one_success_and_one_clean_failure(self):
        outcomes = []
        def run():
            try:
                self.store.close_approved_auto_tdp_records(hub.MAINTAINER)
                outcomes.append('ok')
            except hub.Conflict:
                outcomes.append('conflict')
        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertCountEqual(outcomes, ['ok', 'conflict'])
        self.assertEqual(sum(e['action'] == 'close_approved_auto_tdp_records' for e in self.rows_and_events()[1]), 1)

    def test_range_amendment_changes_only_branch_revision_and_timestamp(self):
        old = copy.deepcopy(hub.APPROVED_TASKS['tdp-runtime-expressible-range-admission'])
        result = self.store.amend_approved_auto_tdp_range_branch(hub.MAINTAINER)['task']
        self.assertEqual(result['branch'], hub.RANGE_NEW_BRANCH)
        self.assertEqual(result['rev'], 2)
        for field in old:
            if field not in ('branch', 'rev', 'updated'):
                self.assertEqual(result[field], old[field])
        snapshot = self.rows_and_events()
        with self.assertRaises(hub.Conflict):
            self.store.amend_approved_auto_tdp_range_branch(hub.MAINTAINER)
        self.assertEqual(self.rows_and_events(), snapshot)

    def test_range_amendment_rejects_every_mutated_field_and_wrong_assignment(self):
        key = 'tdp-runtime-expressible-range-admission'
        for field in hub.APPROVED_TASKS[key]:
            with self.subTest(field=field):
                original = hub.APPROVED_TASKS[key][field]
                changed = original + 'x' if isinstance(original, str) else (1 if original is None else original + 1)
                with self.store.connection(True) as db:
                    if field == 'stream':
                        db.execute('INSERT INTO streams(id,title) VALUES (?,?)', (changed, changed))
                    if field == 'owner':
                        db.execute('INSERT INTO sessions VALUES (?,?,?,?,?)', (changed, 'other', changed, 'fixture', hub.now()))
                    db.execute(f'UPDATE tasks SET {field}=? WHERE id=?', (changed, key))
                snapshot = self.rows_and_events()
                with self.assertRaises(hub.Conflict):
                    self.store.amend_approved_auto_tdp_range_branch(hub.MAINTAINER)
                self.assertEqual(self.rows_and_events(), snapshot)
                with self.store.connection(True) as db:
                    where_key = changed if field == 'id' else key
                    db.execute(f'UPDATE tasks SET {field}=? WHERE id=?', (original, where_key))
        with self.store.connection(True) as db:
            db.execute("UPDATE tasks SET state='cancelled', rev=99, paths='[\"unrelated/path\"]' WHERE id=?",
                       (hub.MAINTENANCE_TASK,))
        snapshot = self.rows_and_events()
        for operation in (self.store.amend_approved_auto_tdp_range_branch,
                          self.store.close_approved_auto_tdp_records):
            with self.assertRaises(hub.Conflict):
                operation(hub.MAINTAINER)
            self.assertEqual(self.rows_and_events(), snapshot)

    def test_range_concurrency_and_operation_isolation(self):
        outcomes = []
        def run():
            try:
                self.store.amend_approved_auto_tdp_range_branch(hub.MAINTAINER)
                outcomes.append('ok')
            except hub.Conflict:
                outcomes.append('conflict')
        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertCountEqual(outcomes, ['ok', 'conflict'])
        readiness = next(r for r in self.rows_and_events()[0] if r['id'] == 'tdp-readiness-evidence-setup')
        self.assertEqual(readiness, hub.APPROVED_TASKS[readiness['id']])

    def test_cli_round_trip_has_no_generic_target_or_authorization_arguments(self):
        script = HUB_DIR / 'hub.py'
        result = subprocess.run([sys.executable, str(script), '--db', str(self.db),
                                 'amend-approved-auto-tdp-range-branch', '--session', hub.MAINTAINER],
                                text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout)['task']['branch'], hub.RANGE_NEW_BRANCH)
        help_text = subprocess.run([sys.executable, str(script), '--db', str(self.db),
                                    'close-approved-auto-tdp-records', '--help'],
                                   text=True, capture_output=True, check=True).stdout
        for forbidden in ('--task', '--owner', '--state', '--authorization', '--force', '--delete', '--takeover'):
            self.assertNotIn(forbidden, help_text)



class RecoveryMirror497Tests(unittest.TestCase):
    """Only temporary databases; never invoke the installed workspace hub."""
    def setUp(self):
        from unittest.mock import patch
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = hub.Hub(Path(self.tmp.name) / 'fixture.sqlite3')
        self.store.init()
        self.actor = 'codex-local-coordination-recovery-20261008'
        self.recipient = 'codex-cloud-lifecycle-director-20261003'
        for session in (self.actor, self.recipient, 'codex-01a080fd', 'other'):
            self.store.register(session, 'codex', session, 'fixture')
        self.key = 'tdp-runtime-expressible-range-admission'
        self.row = self.store.apply('codex-01a080fd', dict(
            op='create_task', id=self.key, stream='auto-tdp', title='Fixture',
            branch='agent/codex-local/497-tdp-expressible-range-admission',
            paths=['backend/regear/delivery/tdp_runtime.py'],
            issue='https://github.com/ronnierosal/Re-Gear/issues/497'))
        self.row = self.store.apply('codex-01a080fd', dict(op='claim_task', id=self.key, rev=1))
        for _ in range(2):
            self.row = self.store.apply('codex-01a080fd', dict(op='update_task', id=self.key, rev=self.row['rev'], state='in_progress'))
        self.maintenance = self.store.apply(self.actor, dict(
            op='create_task', id='agent-hub-maintainer-recovery-mirror-532', stream='coordination',
            title='Fixture maintenance', branch='agent/codex-local/532-bounded-maintainer-recovery',
            paths=['scripts/agent_hub/hub.py']))
        self.maintenance = self.store.apply(self.actor, dict(op='claim_task', id=self.maintenance['id'], rev=1))
        self.canonical = dict(revision=7, owner=self.recipient, status='in-progress',
                              transfer=dict(from_='unused'))
        self.canonical['transfer'] = {'from':'codex-01a080fd','to':self.recipient,'accepted':True}
        self.receipt = {'issue':497, 'record':self.canonical,
                        'receipts':['https://github.com/ronnierosal/Re-Gear/issues/497#issuecomment-6101936371',
                                    'https://github.com/ronnierosal/Re-Gear/issues/497#issuecomment-6101972445',
                                    'https://github.com/ronnierosal/Re-Gear/issues/497#issuecomment-6101984876']}
        for name, value in {
            'RECOVERY497_PREIMAGE_DIGEST':hub.Hub._digest(self.row),
            'RECOVERY497_CANONICAL_DIGEST':hub.Hub._digest(self.canonical),
            'RECOVERY497_MAINTENANCE_DIGEST':hub.Hub._digest(self.maintenance),
            'RECOVERY497_EXECUTION_AUTHORIZATION':'fixture-separate-invocation-approval',
        }.items():
            patcher=patch.object(hub, name, value, create=True);patcher.start();self.addCleanup(patcher.stop)

    def snapshot(self):
        return self.store.status(), self.store.history()

    def invoke(self, actor=None, receipt=None):
        return self.store.mirror_accepted_497_recovery(actor or self.actor,
                                                   self.receipt if receipt is None else receipt)

    def refused_unchanged(self, callback):
        before=self.snapshot()
        with self.assertRaises((hub.Conflict, ValueError)):
            callback()
        self.assertEqual(before,self.snapshot())

    def test_ordinary_transfer_refuses_actual_maintenance_actor(self):
        self.refused_unchanged(lambda:self.store.apply(self.actor, dict(
            op='offer_transfer',kind='task',id=self.key,rev=4,to=self.recipient,note='No impersonation')))

    def test_success_changes_only_owner_revision_and_audits_actual_actor(self):
        result=self.invoke();after=result['task']
        self.assertEqual(after,dict(self.row,owner=self.recipient,rev=5))
        event=self.store.history()[0]
        self.assertEqual(event['actor'],self.actor)
        self.assertEqual(event['action'],'mirror_accepted_497_recovery')
        self.assertIn('maintainer-recovery',event['detail'])
        self.assertEqual(self.store.status()['transfers'],[])
        self.refused_unchanged(self.invoke)

    def test_wrong_actor_receipt_and_each_canonical_field_refused(self):
        self.refused_unchanged(lambda:self.invoke(actor='codex-01a080fd'))
        for field in self.receipt:
            changed=copy.deepcopy(self.receipt);changed[field]=None
            self.refused_unchanged(lambda:self.invoke(receipt=changed))
        for field in self.canonical:
            changed=copy.deepcopy(self.receipt);changed['record'][field]=None
            self.refused_unchanged(lambda:self.invoke(receipt=changed))

    def test_each_full_preimage_field_change_is_refused(self):
        for field in self.row:
            if field in ('id','owner','stream'):continue
            old=self.row[field];changed=old+1 if type(old) is int else old+'x'
            with self.store.connection(True) as db:
                db.execute(f'UPDATE tasks SET {field}=? WHERE id=?',(changed,self.key))
            self.refused_unchanged(self.invoke)
            with self.store.connection(True) as db:
                db.execute(f'UPDATE tasks SET {field}=? WHERE id=?',(old,self.key))

    def test_pending_transfer_collision_and_unregistered_recipient_refused(self):
        transfer=self.store.apply('codex-01a080fd',dict(op='offer_transfer',kind='task',id=self.key,rev=4,to=self.recipient,note='Fixture'))
        self.refused_unchanged(self.invoke)
        self.store.apply('codex-01a080fd',dict(op='cancel_transfer',id=transfer['id']))
        other=self.store.apply('other',dict(op='create_task',id='collision',stream='auto-tdp',title='Collision',branch='other/branch',paths=['backend/regear/delivery/tdp_runtime.py']))
        # Synthetic collision cannot be claimed normally; install it only in this fixture.
        with self.store.connection(True) as db:
            db.execute("UPDATE tasks SET owner='other',state='in_progress' WHERE id='collision'")
        self.refused_unchanged(self.invoke)
        with self.store.connection(True) as db:
            db.execute("UPDATE tasks SET state='cancelled' WHERE id='collision'")
            db.execute('DELETE FROM transfers')
            db.execute('DELETE FROM sessions WHERE id=?',(self.recipient,))
        self.refused_unchanged(self.invoke)

    def test_disabled_authority_and_maintenance_binding_refused(self):
        from unittest.mock import patch
        for name in ('RECOVERY497_EXECUTION_AUTHORIZATION','RECOVERY497_MAINTENANCE_DIGEST'):
            with patch.object(hub,name,None):self.refused_unchanged(self.invoke)

    def test_changed_owner_terminal_row_and_assignment_are_refused(self):
        for field,value in (('owner','other'),('state','done'),('state','cancelled')):
            with self.store.connection(True) as db:
                db.execute(f'UPDATE tasks SET {field}=? WHERE id=?',(value,self.key))
            self.refused_unchanged(self.invoke)
            with self.store.connection(True) as db:
                db.execute(f'UPDATE tasks SET {field}=? WHERE id=?',(self.row[field],self.key))
        with self.store.connection(True) as db:
            db.execute("UPDATE tasks SET note='changed' WHERE id=?",(self.maintenance['id'],))
        self.refused_unchanged(self.invoke)

    def test_cli_rejects_oversized_and_malformed_receipts_without_writes(self):
        receipt=Path(self.tmp.name)/'receipt.json'
        for content in ('x'*65537,'{', '\ud800'):
            receipt.write_bytes(content.encode('utf-8',errors='surrogatepass'))
            before=self.snapshot()
            result=subprocess.run([sys.executable,str(HUB_DIR/'hub.py'),'--db',str(self.store.path),
                                   'mirror-accepted-497-recovery','--session',self.actor,
                                   '--canonical-receipt',str(receipt)],capture_output=True,text=True)
            self.assertEqual(result.returncode,2)
            self.assertEqual(before,self.snapshot())

    def test_audit_failure_rolls_back_owner_and_revision(self):
        from unittest.mock import patch
        before=self.snapshot()
        with patch.object(self.store,'event',side_effect=RuntimeError('fixture audit failure')):
            with self.assertRaises(RuntimeError):self.invoke()
        self.assertEqual(before,self.snapshot())

    def test_concurrent_attempts_have_exactly_one_success(self):
        results=[]
        def run():
            try:self.invoke();results.append('ok')
            except hub.Conflict:results.append('conflict')
        threads=[threading.Thread(target=run) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertCountEqual(results,['ok','conflict'])

    def test_cli_disabled_and_no_generic_owner_or_target_options(self):
        cmd=[sys.executable,str(HUB_DIR/'hub.py'),'--db',str(self.store.path),
             'mirror-accepted-497-recovery','--session',self.actor]
        receipt=Path(self.tmp.name)/'receipt.json';receipt.write_text(json.dumps(self.receipt),encoding='utf-8')
        before=self.snapshot()
        result=subprocess.run(cmd+['--canonical-receipt',str(receipt)],capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertEqual(before,self.snapshot())
        help_result=subprocess.run(cmd+['--help'],capture_output=True,text=True)
        self.assertEqual(help_result.returncode,0)
        for forbidden in ('--owner','--target','--force','--authorization','--skip'):
            self.assertNotIn(forbidden,help_result.stdout)


def load_tests(loader, tests, pattern):
    sys.path.insert(0, str(HUB_DIR))
    try:
        spec = importlib.util.spec_from_file_location('regear_hub_tests', HUB_DIR / 'test_hub.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        suite = loader.loadTestsFromModule(module)
        suite.addTests(loader.loadTestsFromTestCase(CompiledMaintenanceTests))
        suite.addTests(loader.loadTestsFromTestCase(RecoveryMirror497Tests))
        return suite
    finally:
        sys.path.remove(str(HUB_DIR))
